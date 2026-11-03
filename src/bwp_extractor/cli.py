import argparse
from collections import Counter
import json
from pathlib import Path

from bwp_extractor.pipeline import ExtractionPipeline


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="bwp-extractor")
    sub = result.add_subparsers(dest="command", required=True)
    for name in ("inspect", "extract"):
        command = sub.add_parser(name)
        command.add_argument("input", type=Path)
        command.add_argument("--platform", choices=["android"], default="android")
        if name == "extract":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--names", type=Path)
            command.add_argument(
                "--patch", action="append", default=[],
                help="Archive relative name; repeat from low to high priority",
            )
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.command == "inspect":
        records, issues = ExtractionPipeline.inspect(args.input)
        summary = {
            "entries": len(records),
            "status": dict(Counter(r.status.value for r in records)),
            "kinds": dict(Counter(r.kind.value for r in records if r.kind)),
            "archive_issues": issues,
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if issues or any(r.status != "success" for r in records) else 0
    pipeline = ExtractionPipeline(args.output, args.names, args.patch)
    records = pipeline.run(args.input)
    counts = Counter(r.status.value for r in records)
    pipeline.store.write_json("reports/run.json", {
        "status": dict(counts),
        "kinds": dict(Counter(r.kind.value for r in records if r.kind)),
        "failures": [r.to_dict() for r in records if r.status != "success"],
        "archive_issues": pipeline.issues,
        "spine_issues": pipeline.spine_issues,
        "duplicates": pipeline.duplicates,
        "unresolved": sum(r.name_status == "unresolved" for r in records),
    })
    failed = counts["unsupported"] or counts["corrupt"] or counts["conversion_failed"]
    return 1 if failed or pipeline.issues else 0
