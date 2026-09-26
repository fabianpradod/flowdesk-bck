"""Behavior tests on SQLite by default, or an explicitly supplied disposable PostgreSQL DB.

CHAT_TEST_DATABASE_URL must point at a disposable database named flowdesk_chat_test.
The PostgreSQL run exercises the same queries, tenant DDL, constraints and retention job.
"""
import asyncio
import base64
from copy import deepcopy
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies.ai import get_chat_provider
from app.api.dependencies.auth import get_current_user, get_db
from app.integrations.chat_provider import ChatCompletion, ToolCall
from app.models.companies import Company
from app.models.tenant.registry import build_tenant_metadata
from app.schemas.chat import ChatRequest
from app.services.chat import answer_chat
from app.services.chat_maintenance import maintain_chat, upgrade_chat_tables
from app.services.chat_store import ChatActor, ConversationStore, RETENTION, utcnow
from app.services.chat_tools import BusinessTools
from app.tenancy.runtime import get_tenant_tables
from app.utils.exceptions import AppError
from main import app


@pytest.fixture
def database():
    url = os.getenv("CHAT_TEST_DATABASE_URL")
    if url:
        assert make_url(url).database == "flowdesk_chat_test", "Use only the disposable chat test database"
        engine = create_engine(url)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    companies = [uuid4(), uuid4()]
    schemas = [f"tenant_{identity.hex}" for identity in companies]
    owners = [uuid4(), uuid4()]
    with engine.begin() as connection:
        for schema in ["global", *schemas]:
            if engine.dialect.name == "sqlite":
                connection.execute(text(f"ATTACH DATABASE ':memory:' AS \"{schema}\""))
            else:
                connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        Company.__table__.create(connection, checkfirst=True)
        metadata = build_tenant_metadata(schemas[0])
        metadata.tables["global.users"].create(connection, checkfirst=True)
        connection.execute(insert(metadata.tables["global.users"]), [{"id": owner} for owner in owners])
        for company_id, schema in zip(companies, schemas):
            metadata = build_tenant_metadata(schema)
            metadata.create_all(connection, tables=[t for t in metadata.sorted_tables if t.schema == schema])
            connection.execute(insert(Company.__table__).values(id=company_id, name="Test company", schema_name=schema,
                               is_active=True, created_at=datetime.now(timezone.utc)))
    session = Session(engine)
    actor = ChatActor(owners[0], schemas[0])
    yield SimpleNamespace(engine=engine, db=session, actor=actor, other_owner=ChatActor(owners[1], schemas[0]),
                          other_tenant=ChatActor(owners[0], schemas[1]), company_ids=companies)
    session.close()
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            for schema in schemas:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(Company.__table__.delete().where(Company.id.in_(companies)))
            connection.execute(metadata.tables["global.users"].delete().where(metadata.tables["global.users"].c.id.in_(owners)))
    engine.dispose()


def save(store, *, conversation=None, now=None, question="Sales?", answer="A reply"):
    return store.append_turn(conversation=conversation, question=question, answer=answer,
                             sources=[], limitations=[], now=now)


@pytest.fixture
def business(database):
    db, actor = database.db, database.actor
    tables = get_tenant_tables(actor.schema_name)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    product, customer, sale, draft, movement = [uuid4() for _ in range(5)]
    db.execute(insert(tables["producto"]).values(id=product, sku="SAFE-SKU", nombre="Widget", precio_venta=25,
               stock_actual=3, stock_minimo=5, unidad_medida="unidad", is_active=True, created_at=now, updated_at=now))
    db.execute(insert(tables["cliente"]).values(id=customer, nombre="SECRET CUSTOMER", correo="private@example.com",
               telefono="555-1234", direccion="Secret street", is_active=True, created_at=now, updated_at=now))
    for identity, state, total in [(sale, "completada", 100), (draft, "borrador", 900)]:
        db.execute(insert(tables["venta"]).values(id=identity, usuario_id=actor.user_id, cliente_id=customer,
                   fecha=now, subtotal=90, descuento=5, impuesto=15, total=total, estado=state, created_at=now, updated_at=now))
    db.execute(insert(tables["detalle_venta"]).values(id=uuid4(), venta_id=sale, producto_id=product,
               cantidad=4, precio_unitario=25, subtotal=100))
    db.execute(insert(tables["movimiento_inventario"]).values(id=movement, producto_id=product, usuario_id=actor.user_id,
               tipo_movimiento="salida", fecha=now, cantidad=4, stock_anterior=7, stock_resultante=3,
               motivo="DO NOT EXPOSE THIS NOTE"))
    db.commit()
    return customer


class ScriptedProvider:
    name = "test"

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []

    async def complete(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            step = step()
        return step


def reply(content="Sales are 100."):
    return ChatCompletion(content, (), {"role": "assistant", "content": content})


def query(name="sales_metrics", arguments=None, count=1):
    calls = tuple(ToolCall(f"call-{i}", name, arguments or {}) for i in range(count))
    return ChatCompletion(None, calls, {"role": "assistant", "content": None, "reasoning_content": "INTERNAL REASONING",
        "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}} for c in calls]})


def run(database, provider, conversation_id=None, message="Analyze sales"):
    return asyncio.run(answer_chat(ChatRequest(message=message, conversation_id=conversation_id),
                       db=database.db, actor=database.actor, provider=provider))


def test_tool_chat_saves_reopenable_history_and_backend_sources(database, business):
    provider = ScriptedProvider(query(), reply())
    result = run(database, provider)
    assert result.sources[0].tool == "sales_metrics"
    assert result.sources[0].start_date == utcnow().date() - timedelta(days=29)
    assert result.expires_at - result.created_at == RETENTION
    payload = provider.requests[1]["messages"][-1]
    assert json.loads(payload["content"])["data"]["net_sales"] == "100.00"
    assert provider.requests[1]["messages"][-2]["reasoning_content"] == "INTERNAL REASONING"
    detail = ConversationStore(database.db, database.actor).detail(result.conversation_id)
    assert [m.role for m in detail.messages] == ["user", "assistant"]
    assert detail.messages[-1].sources == result.sources
    assert "INTERNAL REASONING" not in detail.model_dump_json()


def test_followup_uses_saved_messages_and_extends_expiry(database):
    store = ConversationStore(database.db, database.actor)
    identity, _, _, expires = save(store, now=utcnow() - timedelta(days=10))
    provider = ScriptedProvider(reply())
    result = run(database, provider, identity, "And this month?")
    assert result.expires_at > expires
    assert [m["role"] for m in provider.requests[0]["messages"]] == ["system", "user", "assistant", "user"]
    assert store.load(identity)["revision"] == 2


@pytest.mark.parametrize("which", ["other_owner", "other_tenant"])
def test_other_users_and_tenants_cannot_read_append_or_delete(database, which):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    intruder = ConversationStore(database.db, getattr(database, which))
    assert intruder.list().items == []
    assert intruder.history(identity) == ([], False)
    for operation in [lambda: intruder.detail(identity), lambda: intruder.delete(identity)]:
        with pytest.raises(AppError) as error:
            operation()
        assert error.value.status_code == 404
    provider = ScriptedProvider(reply())
    with pytest.raises(AppError) as error:
        asyncio.run(answer_chat(ChatRequest(message="read it", conversation_id=identity), db=database.db,
                               actor=getattr(database, which), provider=provider))
    assert error.value.status_code == 404
    assert provider.requests == []


def test_expiry_reads_do_not_extend_retention_and_cleanup_cascades(database):
    store = ConversationStore(database.db, database.actor)
    expired = save(store, now=utcnow() - timedelta(days=16))[0]
    current = save(store)[0]
    before = store.load(current)["expires_at"]
    assert len(store.list().items) == 1
    store.detail(current)
    assert store.load(current)["expires_at"] == before
    with pytest.raises(AppError) as error:
        store.load(expired)
    assert error.value.status_code == 404
    database.db.rollback()
    # Inactive companies still get retention cleanup.
    with database.engine.begin() as connection:
        connection.execute(update(Company).where(Company.id == database.company_ids[0]).values(is_active=False))
    assert maintain_chat(database.engine) == 1
    assert database.db.scalar(select(func.count()).select_from(store.messages)) == 2


def test_delete_removes_messages_and_prevents_resurrection(database):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    stale = store.load(identity)
    store.delete(identity)
    assert database.db.scalar(select(func.count()).select_from(store.messages)) == 0
    with pytest.raises(AppError) as error:
        save(store, conversation=stale)
    assert error.value.status_code == 404


def test_concurrent_turn_conflict_does_not_overwrite_history(database):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    stale = store.load(identity)
    save(store, conversation=stale, answer="Winner")
    with pytest.raises(AppError) as error:
        save(store, conversation=stale, answer="Loser")
    assert error.value.status_code == 409
    assert [m.content for m in store.detail(identity).messages] == ["Sales?", "A reply", "Sales?", "Winner"]


def test_expiration_during_generation_does_not_revive_conversation(database):
    store = ConversationStore(database.db, database.actor)
    stamp = utcnow()
    identity = save(store, now=stamp)[0]
    stale = store.load(identity)
    with pytest.raises(AppError) as error:
        save(store, conversation=stale, now=stamp + RETENTION)
    assert error.value.status_code == 404


def test_history_and_pagination_bounds(database):
    store = ConversationStore(database.db, database.actor)
    ids = [save(store)[0] for _ in range(3)]
    first = store.list(limit=2)
    second = store.list(limit=2, cursor=first.next_cursor)
    assert len(first.items) == 2 and len(second.items) == 1
    assert set(x.id for x in first.items + second.items) == set(ids)
    for _ in range(12):
        save(store, conversation=store.load(ids[0]), question="Q" * 1000, answer="A" * 1000)
    history, truncated = store.history(ids[0])
    assert truncated and len(history) <= 20 and sum(len(m["content"]) for m in history) <= 16000
    assert history[0]["role"] == "user"
    page = store.detail(ids[0], limit=3)
    older = store.detail(ids[0], limit=3, cursor=page.next_cursor)
    assert not {m.id for m in page.messages} & {m.id for m in older.messages}


@pytest.mark.parametrize("cursor", ["invalid", "e30=", "WyJub3QiLCJhLXV1aWQiXQ==", "MA==",
    base64.b64encode(json.dumps(["2026-09-01T00:00:00+00:00", 123]).encode()).decode(),
    base64.b64encode(str(2**63).encode()).decode()])
def test_invalid_cursors_are_rejected(database, cursor):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    for operation in [lambda: store.list(cursor=cursor), lambda: store.detail(identity, cursor=cursor)]:
        with pytest.raises(AppError) as error:
            operation()
        assert error.value.status_code == 422


@pytest.mark.parametrize("name,field,value", [
    ("inventory_metrics", "retail_stock_value", "75.00"),
    ("inventory_products", "stock", "3.00"),
    ("inventory_trend", "net_change", "-4.00"),
    ("sales_metrics", "net_sales", "100.00"),
    ("sales_trend", "sales_count", 1),
    ("top_products", "quantity", "4.00"),
    ("customer_purchases", "purchase_count", 1),
])
def test_tools_return_correct_metrics_without_customer_pii(database, business, name, field, value):
    result = BusinessTools(database.db, database.actor).execute(name, {})
    data = json.loads(result.content)
    record = data["items"][0] if "items" in data else data
    assert Decimal(str(record[field])) == Decimal(str(value))
    for private in ["SECRET CUSTOMER", "private@example.com", "555-1234", "Secret street", "DO NOT EXPOSE"]:
        assert private not in result.content
    other = json.loads(BusinessTools(database.db, database.other_tenant).execute(name, {}).content)
    assert not other.get("items")
    assert other.get("sales_count", 0) == 0


@pytest.mark.parametrize("name,args", [
    ("execute_sql", {"sql": "DROP TABLE venta"}), ("sales_metrics", {"schema_name": "global"}),
    ("sales_metrics", {"start_date": "2026-01-01"}),
    ("sales_metrics", {"start_date": "2024-01-01", "end_date": "2026-01-01"}),
    ("sales_metrics", {"start_date": "2099-01-01", "end_date": "2099-01-01"}),
    ("customer_purchases", {"customer_id": "not a UUID"}),
    ("top_products", {"limit": 999}), ("top_products", {"limit": True}),
])
def test_tool_filters_cannot_expand_access_or_resource_limits(database, name, args):
    with pytest.raises(AppError) as error:
        BusinessTools(database.db, database.actor).execute(name, args)
    assert error.value.code == "invalid_tool_arguments"


def test_empty_metrics_and_bounded_monthly_trends(database):
    tools = BusinessTools(database.db, database.actor)
    assert json.loads(tools.execute("inventory_metrics", {}).content)["out_of_stock"] == 0
    today = utcnow().date()
    result = tools.execute("sales_trend", {"start_date": str(today - timedelta(days=90)), "end_date": str(today)})
    assert json.loads(result.content) == {"granularity": "month", "items": [],
        "missing_periods": "Periods without recorded activity are omitted; partial boundary months are possible."}


def test_provider_failure_leaves_no_partial_turn(database):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    before = store.detail(identity).model_dump()
    for conversation_id in [None, identity]:
        with pytest.raises(AppError):
            run(database, ScriptedProvider(AppError(503, "Unavailable", "ai_provider_unavailable")), conversation_id)
    assert store.detail(identity).model_dump() == before
    assert len(store.list().items) == 1


def test_invalid_tool_arguments_can_be_corrected(database, business):
    provider = ScriptedProvider(query(arguments={"schema_name": "other"}), query(), reply())
    result = run(database, provider)
    assert len(result.sources) == 1
    assert "invalid_tool_arguments" in provider.requests[1]["messages"][-1]["content"]


def test_tool_call_limit_aborts_without_saving(database):
    with pytest.raises(AppError) as error:
        run(database, ScriptedProvider(query(count=7)))
    assert error.value.code == "ai_tool_limit"
    assert ConversationStore(database.db, database.actor).list().items == []


def test_last_round_disables_tools(database):
    provider = ScriptedProvider(query(), query(), query(), reply())
    run(database, provider)
    assert provider.requests[-1]["tools"] == []


def test_request_deadline_cancels_provider(database, monkeypatch):
    monkeypatch.setattr("app.services.chat.REQUEST_TIMEOUT", .01)
    class SlowProvider:
        async def complete(self, **_):
            await asyncio.sleep(1)
    with pytest.raises(AppError) as error:
        run(database, SlowProvider())
    assert error.value.status_code == 504
    assert ConversationStore(database.db, database.actor).list().items == []


def test_schema_upgrade_is_repeatable_and_preserves_history(database):
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    database.db.rollback()
    for _ in range(2):
        assert maintain_chat(database.engine, upgrade=True) == 0
    assert store.detail(identity).messages[-1].content == "A reply"
    with pytest.raises(ValueError):
        with database.engine.begin() as connection:
            upgrade_chat_tables(connection, 'global; DROP TABLE users')


@pytest.fixture
def api(database):
    user = SimpleNamespace(id=database.actor.user_id, role=SimpleNamespace(name="manager"),
                           company_id=database.company_ids[0], is_active=True,
                           company=SimpleNamespace(schema_name=database.actor.schema_name, is_active=True))
    provider = ScriptedProvider(query(), reply())
    app.dependency_overrides[get_db] = lambda: database.db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_chat_provider] = lambda: provider
    return TestClient(app), user, provider


def test_api_create_list_reopen_followup_delete(api, business):
    client, user, provider = api
    response = client.post("/api/v1/ai/chat", json={"message": "Sales?"})
    assert response.status_code == 200, response.text
    identity = response.json()["conversation_id"]
    assert client.get("/api/v1/ai/conversations").json()["items"][0]["id"] == identity
    detail = client.get(f"/api/v1/ai/conversations/{identity}")
    assert detail.status_code == 200 and len(detail.json()["messages"]) == 2
    user.role.name = "admin"
    provider.steps.append(reply())
    assert client.post("/api/v1/ai/chat", json={"message": "More?", "conversation_id": identity}).status_code == 200
    assert client.delete(f"/api/v1/ai/conversations/{identity}").status_code == 204
    assert client.get(f"/api/v1/ai/conversations/{identity}").status_code == 404


@pytest.mark.parametrize("restriction", ["employee", "superadmin", "inactive_company", "no_company"])
def test_api_enforces_access_before_provider_calls(api, restriction):
    client, user, provider = api
    if restriction == "inactive_company":
        user.company.is_active = False
    elif restriction == "no_company":
        user.company_id = None
    else:
        user.role.name = restriction
    assert client.post("/api/v1/ai/chat", json={"message": "Sales?"}).status_code == 403
    assert client.get("/api/v1/ai/conversations").status_code == 403
    assert client.get(f"/api/v1/ai/conversations/{uuid4()}").status_code == 403
    assert client.delete(f"/api/v1/ai/conversations/{uuid4()}").status_code == 403
    assert provider.requests == []


def test_api_rejects_client_context_injection_and_returns_safe_error(api):
    client, _, provider = api
    for extra in [{"tenant": "other"}, {"messages": []}, {"role": "system"}]:
        assert client.post("/api/v1/ai/chat", json={"message": "Sales?", **extra}).status_code == 422
    provider.steps = [AppError(503, "Chat provider API credit is unavailable", "ai_provider_quota_exhausted")]
    response = client.post("/api/v1/ai/chat", json={"message": "Sales?"})
    assert response.status_code == 503
    assert response.json()["code"] == "ai_provider_quota_exhausted"


def test_history_routes_work_without_provider_configuration(api):
    client, _, provider = api
    result = client.post("/api/v1/ai/chat", json={"message": "Sales?"})
    identity = result.json()["conversation_id"]
    def unavailable():
        raise AppError(503, "Not configured", "ai_provider_unavailable")
    app.dependency_overrides[get_chat_provider] = unavailable
    assert client.get("/api/v1/ai/conversations").status_code == 200
    assert client.get(f"/api/v1/ai/conversations/{identity}").status_code == 200
    assert client.delete(f"/api/v1/ai/conversations/{identity}").status_code == 204


def test_failed_message_insert_rolls_back_new_conversation(database):
    store = ConversationStore(database.db, database.actor)
    def fail_message_insert(_connection, _cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO") and "chat_message" in statement:
            raise RuntimeError("simulated message write failure")
    event.listen(database.engine, "before_cursor_execute", fail_message_insert)
    try:
        with pytest.raises(RuntimeError):
            save(store)
    finally:
        event.remove(database.engine, "before_cursor_execute", fail_message_insert)
    assert store.list().items == []
    assert database.db.scalar(select(func.count()).select_from(store.messages)) == 0


def test_upgrade_adds_missing_chat_tables_to_existing_tenant(database):
    tables = get_tenant_tables(database.actor.schema_name)
    with database.engine.begin() as connection:
        tables["chat_message"].drop(connection)
        tables["chat_conversation"].drop(connection)
        upgrade_chat_tables(connection, database.actor.schema_name)
        upgrade_chat_tables(connection, database.actor.schema_name)
    store = ConversationStore(database.db, database.actor)
    identity = save(store)[0]
    assert store.detail(identity).messages[-1].content == "A reply"


def test_queries_are_read_only_and_timeout_recovers_connection(database, monkeypatch):
    if database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL transaction protections")
    tools = BusinessTools(database.db, database.actor)
    def write_attempt(*_):
        database.db.execute(text(f'DELETE FROM "{database.actor.schema_name}".producto'))
        return {}, []
    monkeypatch.setattr(tools, "_query", write_attempt)
    with pytest.raises(AppError) as error:
        tools.execute("sales_metrics", {})
    assert error.value.code == "ai_data_unavailable"
    def slow_query(*_):
        database.db.execute(text("SELECT pg_sleep(0.1)"))
        return {}, []
    monkeypatch.setattr(tools, "_query", slow_query)
    with pytest.raises(AppError) as error:
        tools.execute("sales_metrics", {}, timeout_seconds=.01)
    assert error.value.code == "ai_data_unavailable"
    # Both failures rolled back their read-only transactions; persistence still works.
    assert save(ConversationStore(database.db, database.actor))[0]


def test_ranked_results_report_truncation_and_exact_customer_filter(database, business):
    tables = get_tenant_tables(database.actor.schema_name)
    now = utcnow().replace(tzinfo=None)
    database.db.execute(insert(tables["producto"]).values(id=uuid4(), sku="SECOND", nombre="Second", precio_venta=10,
        stock_actual=0, stock_minimo=8, unidad_medida="unidad", is_active=True, created_at=now, updated_at=now))
    database.db.commit()
    tools = BusinessTools(database.db, database.actor)
    result = tools.execute("inventory_products", {"limit": 1})
    assert json.loads(result.content)["truncated"]
    assert "first 1" in " ".join(result.limitations)
    result = tools.execute("customer_purchases", {"customer_id": str(business)})
    assert json.loads(result.content)["items"][0]["customer_id"] == str(business)
    assert json.loads(tools.execute("customer_purchases", {"customer_id": str(uuid4())}).content)["items"] == []


def test_history_model_context_omits_old_turns_and_marks_limitation(database):
    store = ConversationStore(database.db, database.actor)
    identity = save(store, question="OLD SECRET CONTEXT")[0]
    for _ in range(11):
        save(store, conversation=store.load(identity))
    provider = ScriptedProvider(reply())
    result = run(database, provider, identity)
    assert "OLD SECRET CONTEXT" not in json.dumps(provider.requests)
    assert any("history context is limited" in limit for limit in result.limitations)



def test_followup_context_preserves_prior_source_period(database, business):
    first = run(database, ScriptedProvider(query(), reply("Here is the result.")))
    provider = ScriptedProvider(reply("Follow-up"))
    run(database, provider, first.conversation_id, "Compare that same period")
    previous = provider.requests[0]["messages"][-2]["content"]
    assert str(first.sources[0].start_date) in previous
    assert str(first.sources[0].end_date) in previous
    assert "query tools again for fresh figures" in previous
    assert "INTERNAL REASONING" not in previous
