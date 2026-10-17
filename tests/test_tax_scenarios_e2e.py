"""End-to-end scenarios for the country-neutral taxation pipeline."""

from datetime import date
from decimal import Decimal
import pytest
from app.schemas.fiscal import FiscalDocumentCreate, ImportBatchCreate, ImportMappingCreate
from app.services.importer import normalize_and_validate, read_rows
from app.services import reports as reports_service
from app.taxation import FiscalClassifier, TaxDefinition, TaxEngine, TaxProfile, TaxRule, TaxValidationError, TaxableOperation
from app.taxation.fiscal_adapter import document_to_operations

def make_profile(*taxes, rules=(), version_id="profile-v1", start=date(2026, 1, 1), end=None):
    return TaxProfile(
        jurisdiction="configured", regime=None, effective_from=start, effective_until=end,
        version_id=version_id, taxes=tuple(taxes), rules=tuple(rules), precision=2, rounding="HALF_UP",
    )

def tax(code, rate, *, category="TAXABLE", compound=False, priority=0, eligible=None):
    return TaxDefinition(code, f"Configured {code}", rate=Decimal(str(rate)), category=category, is_compound=compound, priority=priority, eligible_for_input_credit=eligible)

def component(code="TAX_A", amount="10", category="TAXABLE", base="100", **extra):
    return {"id": extra.pop("id", f"component-{code}"), "tax_code": code, "tax_type": "percentage",
            "category": category, "amount": Decimal(amount), "taxable_base": Decimal(base), **extra}

def document(*components, direction="INPUT", issue_date=date(2026, 1, 10), total="110", status="ACTIVE"):
    return {
        "id": "document-1", "document_type": "INVOICE", "direction": direction,
        "issue_date": issue_date, "status": status, "currency": "USD", "taxable_base": Decimal("100"),
        "total": Decimal(total), "taxes": list(components), "lines": [],
    }

def test_scenario_a_standard_output_tax_is_traced():
    profile = make_profile(tax("TAX_A", "10"))
    result = TaxEngine().calculate({"taxable_base": Decimal("100"), "document_type": "GENERIC"}, profile, at_date=date(2026, 1, 10))

    assert result.tax_debit == Decimal("10.00")
    assert result.details[0]["tax_code"] == "TAX_A"
    assert result.details[0]["tax_rate"] == Decimal("10")
    assert result.details[0]["taxable_base"] == Decimal("100")
    assert result.details[0]["profile_version"] == "profile-v1"

def test_scenarios_b_to_d_input_credit_net_and_carry_forward():
    profile = make_profile(
        tax("TAX_A", "10", eligible=True),
        rules=(TaxRule({"field": "tax_category", "operator": "eq", "value": "TAXABLE"}, scope="INPUT_TAX",
                       result={"eligible_for_input_credit": True}),),
    )
    eligible = document(component(amount="20", base="200"))
    operations = document_to_operations(eligible, profile)
    result = TaxEngine().calculate_period(operations, profile, tax_debit=Decimal("50"))

    assert (result.tax_credit, result.net_tax, result.tax_payable, result.carry_forward) == (
        Decimal("20.00"), Decimal("30.00"), Decimal("30.00"), Decimal("0.00"))

    excess = TaxEngine().calculate_period(
        [TaxableOperation(tax_amount=Decimal("50"), tax_category="TAXABLE", tax_code="TAX_A", document_direction="INPUT", eligible_for_input_credit=True)], profile, tax_debit=Decimal("20"))

    assert (excess.tax_credit, excess.net_tax, excess.tax_payable, excess.carry_forward) == (
        Decimal("50.00"), Decimal("-30.00"), Decimal("0.00"), Decimal("30.00"))

@pytest.mark.parametrize("category", ["ZERO_RATED", "EXEMPT", "NON_TAXABLE"])
def test_scenarios_e_to_g_keep_non_standard_categories_without_tax(category):
    profile = make_profile(tax("TAX_A", "10", category=category))
    doc = document(component(amount="0", category=category, base="1000"), total="1000")
    operations = document_to_operations(doc, profile)
    result = TaxEngine().calculate_period(operations, profile, tax_debit=Decimal("0"))

    assert operations[0].tax_category == category
    assert operations[0].taxable_base == Decimal("1000")
    assert result.tax_credit == Decimal("0.00")
    assert result.details[0]["tax_category"] == category

    if category == "NON_TAXABLE":
        assert result.details[0]["classification_reason"] == "NON_TAXABLE_OPERATION"

def test_scenarios_h_i_multiple_and_compound_taxes_are_separate_decimal_components():
    profile = make_profile(tax("TAX_A", "10", priority=0), tax("TAX_B", "5", compound=True, priority=1))
    result = TaxEngine().calculate({"taxable_base": Decimal("100")}, profile, at_date=date(2026, 1, 10))

    assert [(item["tax_code"], item["amount"], item["taxable_base"]) for item in result.details] == [
        ("TAX_A", Decimal("10.00"), Decimal("100")), ("TAX_B", Decimal("5.50"), Decimal("110.00"))]

    assert result.tax_debit == Decimal("15.50")

def test_scenarios_j_l_withholding_effects_remain_separate_from_credit():
    profile = make_profile(tax("TAX_A", "10"), rules=(
        TaxRule({"field": "withholding_type", "operator": "eq", "value": "configured"}, scope="WITHHOLDING",
                result={"withholding_effect": "REDUCE_PAYABLE"}),
    ))
    informational = TaxableOperation(tax_amount=Decimal("5"), tax_category="WITHHOLDING", tax_code="RET", is_withholding=True, withholding_type="other", withholding_effect="INFORMATIONAL")
    reduced = TaxableOperation(tax_amount=Decimal("10"), tax_category="WITHHOLDING", tax_code="RET", is_withholding=True, withholding_type="configured")
    result = TaxEngine().calculate_period([informational, reduced], profile, tax_debit=Decimal("50"))

    assert result.withholding_tax == Decimal("15.00")
    assert result.tax_credit == Decimal("0.00")
    assert result.tax_payable == Decimal("40.00")
    assert result.details[0]["withholding_effect"] == "INFORMATIONAL"
    assert result.details[1]["withholding_effect"] == "REDUCE_PAYABLE"

    credit_profile = make_profile(tax("TAX_A", "10"), rules=(
        TaxRule(None, scope="WITHHOLDING", result={"withholding_effect": "INCREASE_CREDIT"}),
    ))
    credit_result = TaxEngine().calculate_period([
        TaxableOperation(tax_amount=Decimal("10"), tax_category="WITHHOLDING", tax_code="RET", is_withholding=True)
    ], credit_profile, tax_debit=Decimal("20"))

    assert credit_result.withholding_tax == Decimal("10.00")
    assert credit_result.tax_credit == Decimal("0.00")
    assert credit_result.tax_payable == Decimal("10.00")

def test_scenarios_m_n_temporal_profiles_are_selected_by_document_date():
    first = make_profile(tax("TAX_A", "10"), version_id="profile-a", start=date(2026, 1, 1), end=date(2026, 1, 15))
    second = make_profile(tax("TAX_A", "20"), version_id="profile-b", start=date(2026, 1, 15))
    classifier = FiscalClassifier()

    assert classifier.classify(document(issue_date=date(2026, 1, 10)), first).profile_version == "profile-a"
    assert classifier.classify(document(issue_date=date(2026, 1, 20)), second).profile_version == "profile-b"

    old = TaxEngine().calculate({"taxable_base": Decimal("100")}, first, at_date=date(2026, 1, 10))
    new = TaxEngine().calculate({"taxable_base": Decimal("100")}, second, at_date=date(2026, 1, 20))

    assert (old.tax_debit, new.tax_debit) == (Decimal("10.00"), Decimal("20.00"))

def test_scenario_n_period_crossing_versions_resolves_each_operation_date():
    first = make_profile(
        tax("TAX_A", "10", eligible=True), version_id="profile-a", start=date(2026, 1, 1), end=date(2026, 1, 15),
        rules=(TaxRule(None, scope="INPUT_TAX", result={"eligible_for_input_credit": True}),),
    )
    second = make_profile(
        tax("TAX_A", "20", eligible=False), version_id="profile-b", start=date(2026, 1, 15),
        rules=(TaxRule(None, scope="INPUT_TAX", result={"eligible_for_input_credit": False}),),
    )
    operations = [
        TaxableOperation(tax_amount=Decimal("10"), tax_category="TAXABLE", tax_code="TAX_A", document_direction="INPUT", operation_date=date(2026, 1, 10)),
        TaxableOperation(tax_amount=Decimal("20"), tax_category="TAXABLE", tax_code="TAX_A", document_direction="INPUT", operation_date=date(2026, 1, 20)),
    ]
    result = TaxEngine().calculate_period(
        operations, first, tax_debit=Decimal("50"), start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
        profile_resolver=lambda operation_date: first if operation_date < date(2026, 1, 15) else second,
    )

    assert result.tax_credit == Decimal("10.00")
    assert {detail["profile_version"] for detail in result.details} == {"profile-a", "profile-b"}

def test_scenario_o_ambiguous_same_priority_is_rejected_not_selected_arbitrarily():
    with pytest.raises(TaxValidationError, match="overlap"):
        make_profile(
            tax("TAX_A", "10"),
            rules=(TaxRule(None, scope="CLASSIFICATION", priority=1, result={"direction": "INPUT"}), TaxRule(None, scope="CLASSIFICATION", priority=1, result={"direction": "OUTPUT"})),)

def test_scenarios_p_q_csv_normalization_to_document_lines_and_components():
    content = b"Document,Date,Document Type,Type,Currency,Base,Tax A Code,Tax A Type,Tax A Category,Tax A,Tax B Code,Tax B Type,Tax B Category,Tax B,Total\nDOC-001,2026-01-10,INVOICE,OUTPUT,USD,100,TAX_A,percentage,TAXABLE,10,TAX_B,percentage,TAXABLE,5,115\n"
    headers, rows = read_rows(content, "CSV")
    normalized = normalize_and_validate(rows, {
        "Document": "document_number", "Date": "issue_date", "Document Type": "document_type",
        "Type": "direction", "Currency": "currency",
        "Base": "taxable_base", "Tax A Code": "taxes[0].tax_code", "Tax A Type": "taxes[0].tax_type",
        "Tax A Category": "taxes[0].category", "Tax A": "taxes[0].amount",
        "Tax B Code": "taxes[1].tax_code", "Tax B Type": "taxes[1].tax_type",
        "Tax B Category": "taxes[1].category", "Tax B": "taxes[1].amount", "Total": "total",
    })

    assert headers[0:5] == ["Document", "Date", "Document Type", "Type", "Currency"]
    assert not normalized["errors"]

    data = normalized["rows"][0]["data"]
    fiscal_document = FiscalDocumentCreate(**data)

    assert fiscal_document.document_number == "DOC-001"
    assert [item.amount for item in fiscal_document.taxes] == [Decimal("10"), Decimal("5")]
    assert fiscal_document.direction == "OUTPUT"

def test_scenario_r_historical_component_snapshot_is_not_recalculated_by_new_profile():
    old_document = document(component(amount="10"), total="110")
    new_profile = make_profile(tax("TAX_A", "20"), version_id="profile-new")
    operation = document_to_operations(old_document, new_profile)[0]

    assert operation.tax_amount == Decimal("10")
    assert operation.taxable_base == Decimal("100")

def test_scenario_u_period_result_and_imported_document_feed_the_existing_report_contract():
    imported = document(component(amount="20", base="200"), total="220")
    period = {"tax_debit": Decimal("50"), "tax_credit": Decimal("20"), "net_tax": Decimal("30"),
              "tax_payable": Decimal("30"), "carry_forward": Decimal("0"), "details": [
                  {"document_id": imported["id"], "taxable_base": Decimal("200"),
                   "tax_amount": Decimal("20"), "eligible_for_input_credit": True},
              ]}
    rows = reports_service._build_tax_purchase_rows([imported], "GENERAL_VAT", None)
    summary = reports_service._build_tax_summary(
        "GENERAL_VAT", [], {"fiscal_debit": Decimal("50")}, period_result=period, input_documents=[imported])

    assert rows[0][7:10] == [Decimal("100"), None, Decimal("220")]
    assert summary.rows[1][1] == Decimal("50.00")
    assert summary.rows[3][1] == Decimal("20.00")
    assert summary.rows[4][1] == Decimal("30.00")

def test_scenario_factories_cover_import_batch_and_mapping_without_country_defaults():
    batch = ImportBatchCreate(source_type="CSV", filename="generic.csv")
    mapping = ImportMappingCreate(name="Generic mapping", source_type="CSV", mapping={"Date": "issue_date"})

    assert batch.source_type == mapping.source_type == "CSV"
    assert mapping.mapping == {"Date": "issue_date"}