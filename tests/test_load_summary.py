import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent / "load" / "summarize_k6.py"
spec = importlib.util.spec_from_file_location("summarize_k6", SCRIPT_PATH)
summarize_k6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summarize_k6)

HEADER = "metric_name,timestamp,metric_value,check,error,error_code,expected_response,group,method,name,proto,scenario,service,status,subproto,tls_version,url,extra_tags,metadata"


def row(metric, timestamp, value, name, stage):
    return f"{metric},{timestamp},{value},,,,true,,GET,{name},HTTP/1.1,default,,200,,,url,stage={stage},"


@pytest.fixture
def k6_csv(tmp_path):
    lines = [HEADER, row("http_req_duration", 1, 5, "login", "setup")]
    for second, value in enumerate([10, 20, 30, 40], start=100):
        lines.append(row("http_req_duration", second, value, "products", "25"))
        lines.append(row("http_req_failed", second, 0, "products", "25"))
    lines.append(row("http_req_duration", 104, 100, "health", "25"))
    lines.append(row("http_req_failed", 104, 1, "health", "25"))
    lines.append(row("http_req_duration", 200, 999, "products", "ramp"))
    path = tmp_path / "run.csv"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_percentile_interpolates_between_ranks():
    assert summarize_k6.percentile([10, 20, 30, 40], 50) == 25
    assert summarize_k6.percentile([10, 20, 30, 40], 100) == 40
    assert summarize_k6.percentile([7], 95) == 7


def test_summary_groups_by_stage_and_endpoint(k6_csv):
    summary = summarize_k6.summarize(k6_csv)

    assert set(summary) == {"25"}
    products = summary["25"]["products"]
    assert products["requests"] == 4
    assert products["p50"] == 25
    assert products["max"] == 40
    assert products["errors"] == 0


def test_summary_skips_setup_and_ramps(k6_csv):
    summary = summarize_k6.summarize(k6_csv)

    assert "login" not in summary["25"]
    assert summary["25"]["all"]["max"] == 100


def test_summary_counts_failures_and_rate(k6_csv):
    summary = summarize_k6.summarize(k6_csv)

    overall = summary["25"]["all"]
    assert overall["requests"] == 5
    assert overall["errors"] == pytest.approx(20.0)
    assert overall["rps"] == pytest.approx(1.0)


def test_compare_reports_change_in_percent(k6_csv):
    before = summarize_k6.summarize(k6_csv)
    after = summarize_k6.summarize(k6_csv)
    after["25"]["all"]["p95"] = before["25"]["all"]["p95"] / 2

    table = summarize_k6.compare_table(before, after)

    assert "-50%" in table
