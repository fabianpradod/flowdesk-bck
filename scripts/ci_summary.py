"""Create a portable evidence summary from JUnit reports, including failed runs."""
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

reports = Path("reports")
reports.mkdir(exist_ok=True)
sha = os.getenv("GITHUB_SHA") or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
data = {
    "commit": sha,
    "run_url": f"https://github.com/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}" if os.getenv("GITHUB_RUN_ID") else "local",
    "event": os.getenv("GITHUB_EVENT_NAME", "local"),
    "attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
    "job": os.getenv("GITHUB_JOB", "local"),
    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    "suites": [],
}
for name in ("integration", "regression", "suite"):
    path = reports / f"{name}.xml"
    if not path.exists():
        continue
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures = [case for case in cases if case.find("failure") is not None or case.find("error") is not None]
    skipped = sum(case.find("skipped") is not None for case in cases)
    data["suites"].append({
        "name": name, "tests": len(cases), "passed": len(cases) - len(failures) - skipped,
        "failed": len(failures), "skipped": skipped,
        "failed_cases": [{"name": case.get("name"), "class": case.get("classname")} for case in failures],
    })
lines = ["# FlowDesk: evidencia de pruebas", "", f"Commit: `{sha}`", f"Ejecucion: {data['run_url']}", "",
         "| Suite | Total | Aprobadas | Fallidas | Omitidas |", "|---|---:|---:|---:|---:|"]
for suite in data["suites"]:
    lines.append(f"| {suite['name']} | {suite['tests']} | {suite['passed']} | {suite['failed']} | {suite['skipped']} |")
    for case in suite["failed_cases"]:
        lines.append(f"\nPrueba fallida: `{case['class']}::{case['name']}`\n")
if not data["suites"]:
    lines.append("\nNo se generaron reportes JUnit. Revisar los pasos de preparacion; esto no acredita una ejecucion exitosa.")
content = "\n".join(lines) + "\n"
(reports / "summary.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
(reports / "summary.md").write_text(content)
if os.getenv("GITHUB_STEP_SUMMARY"):
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as handle:
        handle.write(content)
print(content)
