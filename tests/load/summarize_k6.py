"""Summarize the k6 CSV output of flowdesk_load.js, or compare two summaries.

Only requests made while a load level was held are counted (stage tag 25, 50 or
100); setup and ramps are skipped so each level is measured at a steady load.

    python tests/load/summarize_k6.py summary run.csv --json run.json
    python tests/load/summarize_k6.py compare before.json after.json --stage 50
"""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

STAGES = ("25", "50", "100")


def percentile(values: list[float], pct: float) -> float:
    """Linear interpolation between the closest ranks."""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * pct / 100
    low, high = math.floor(rank), math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _stats(durations: list[float], failures: int, seconds: int) -> dict:
    return {
        "requests": len(durations),
        "rps": len(durations) / max(seconds, 1),
        "p50": percentile(durations, 50),
        "p95": percentile(durations, 95),
        "p99": percentile(durations, 99),
        "max": max(durations, default=0.0),
        "errors": 100 * failures / max(len(durations), 1),
    }


def summarize(path: Path) -> dict:
    durations = defaultdict(list)
    failures = defaultdict(int)
    seconds = defaultdict(set)
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            tags = dict(item.split("=", 1) for item in row["extra_tags"].split("&") if "=" in item)
            stage = tags.get("stage")
            if stage not in STAGES:
                continue
            if row["metric_name"] == "http_req_duration":
                durations[(stage, row["name"])].append(float(row["metric_value"]))
                seconds[stage].add(int(row["timestamp"]))
            elif row["metric_name"] == "http_req_failed" and float(row["metric_value"]) > 0:
                failures[(stage, row["name"])] += 1

    summary = {}
    for stage in STAGES:
        names = sorted(name for (key_stage, name) in durations if key_stage == stage)
        if not names:
            continue
        hold = len(seconds[stage])
        summary[stage] = {
            name: _stats(durations[(stage, name)], failures[(stage, name)], hold) for name in names
        }
        summary[stage]["all"] = _stats(
            [value for name in names for value in durations[(stage, name)]],
            sum(failures[(stage, name)] for name in names),
            hold,
        )
    return summary


def summary_table(summary: dict) -> str:
    lines = [
        "| VUs | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for stage, endpoints in summary.items():
        s = endpoints["all"]
        lines.append(
            f"| {stage} | {s['requests']} | {s['rps']:.0f} | {s['p50']:.0f} | {s['p95']:.0f} "
            f"| {s['p99']:.0f} | {s['max']:.0f} | {s['errors']:.2f} |"
        )

    stages = list(summary)
    last = stages[-1]
    lines += [
        "",
        "| endpoint | " + " | ".join(f"p95 @{stage}" for stage in stages) + f" | p50 @{last} | p99 @{last} | share % |",
        "|---|" + "---|" * (len(stages) + 3),
    ]
    total = summary[last]["all"]["requests"]
    names = [name for name in summary[last] if name != "all"]
    for name in sorted(names, key=lambda n: summary[last][n]["p95"], reverse=True):
        p95s = " | ".join(f"{summary[stage].get(name, {}).get('p95', 0):.0f}" for stage in stages)
        s = summary[last][name]
        lines.append(f"| {name} | {p95s} | {s['p50']:.0f} | {s['p99']:.0f} | {100 * s['requests'] / total:.1f} |")
    return "\n".join(lines)


def _change(before: float, after: float) -> str:
    if not before:
        return "n/a"
    return f"{100 * (after - before) / before:+.0f}%"


def compare_table(before: dict, after: dict, endpoint_stage: str | None = None) -> str:
    stages = [stage for stage in STAGES if stage in before and stage in after]
    lines = [
        "| VUs | metric | before | after | change |",
        "|---|---|---|---|---|",
    ]
    for stage in stages:
        b, a = before[stage]["all"], after[stage]["all"]
        for metric in ("rps", "p50", "p95", "p99", "errors"):
            lines.append(f"| {stage} | {metric} | {b[metric]:.1f} | {a[metric]:.1f} | {_change(b[metric], a[metric])} |")

    # A level where one run stalled has no useful per endpoint numbers, so the
    # endpoint table can be pinned to another level.
    last = endpoint_stage or stages[-1]
    lines += [
        "",
        f"| endpoint | p95 before @{last} | p95 after @{last} | change |",
        "|---|---|---|---|",
    ]
    names = [name for name in before[last] if name != "all" and name in after[last]]
    for name in sorted(names, key=lambda n: before[last][n]["p95"], reverse=True):
        b, a = before[last][name]["p95"], after[last][name]["p95"]
        lines.append(f"| {name} | {b:.0f} | {a:.0f} | {_change(b, a)} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    summary_cmd = commands.add_parser("summary")
    summary_cmd.add_argument("csv", type=Path)
    summary_cmd.add_argument("--json", type=Path, help="Also write the summary as JSON")
    compare_cmd = commands.add_parser("compare")
    compare_cmd.add_argument("before", type=Path)
    compare_cmd.add_argument("after", type=Path)
    compare_cmd.add_argument("--stage", choices=STAGES, help="Load level for the endpoint table (default: highest)")
    args = parser.parse_args()

    if args.command == "summary":
        summary = summarize(args.csv)
        if args.json:
            args.json.write_text(json.dumps(summary, indent=2))
        print(summary_table(summary))
    else:
        before = json.loads(args.before.read_text())
        after = json.loads(args.after.read_text())
        print(compare_table(before, after, args.stage))


if __name__ == "__main__":
    main()
