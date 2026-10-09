"""python -m src.reliable.cli: isolated one-PDF pilot. Legacy commands remain unchanged."""
import argparse
import json
from pathlib import Path
from src.io_utils import read_json, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("parse")
    p.add_argument("--pdf", required=True)
    p.add_argument("--output", default="data/pilot/sections")
    p = commands.add_parser("extract")
    p.add_argument("--sections", required=True)
    p.add_argument("--output", default="data/pilot/runs")
    p.add_argument("--model")
    p.add_argument("--max-sections", type=int, default=15)
    p.add_argument("--section-id", action="append")
    p = commands.add_parser("inspect")
    p.add_argument("--run", required=True)
    p = commands.add_parser("report")
    p.add_argument("--run", required=True)
    p = commands.add_parser("review")
    p.add_argument("--run", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--decision", required=True, choices=["accepted", "rejected", "uncertain"])
    p.add_argument("--reviewer", required=True)
    p.add_argument("--reviewer-kind", choices=["human", "assistant"], default="human")
    p.add_argument("--note", required=True)
    p = commands.add_parser("build")
    p.add_argument("--run", required=True)
    p.add_argument("--allow-assistant", action="store_true", help="Explicitly labeled assistant-verified draft; not human approval")
    p = commands.add_parser("reference-template")
    p.add_argument("--sections", required=True)
    p.add_argument("--output", required=True)
    p = commands.add_parser("evaluate")
    p.add_argument("--run", required=True)
    p.add_argument("--reference", required=True)
    p = commands.add_parser("library")
    p.add_argument("--plan", default="config/document_profiles.json")
    p.add_argument("--output", default="data/library")
    p.add_argument("--extract", action="store_true")
    p.add_argument("--max-sections", type=int, default=3)
    p = commands.add_parser("view")
    p.add_argument("--runs", nargs="+", default=["data/pilot/runs", "data/library/runs"])
    p.add_argument("--output", default="fmea_view")
    p = commands.add_parser("ontology", help="Export a draft ontology from reviewed statements")
    p.add_argument("--runs", nargs="+", default=["data/pilot/runs", "data/library/runs"])
    p.add_argument("--output", default="data/ontology")
    p.add_argument("--allow-assistant", action="store_true", help="Include accepted assistant source checks in the draft")
    p = commands.add_parser("serve")
    p.add_argument("--directory", default="fmea_view")
    p.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.command == "library":
            from src.reliable.documents import process_library
            print(process_library(args.plan, args.output, args.extract, args.max_sections))
        elif args.command == "view":
            from src.reliable.viewer import generate
            print(generate(args.runs, args.output))
        elif args.command == "ontology":
            from src.reliable.ontology import generate
            print(generate(args.runs, args.output, args.allow_assistant))
        elif args.command == "serve":
            from functools import partial
            from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
            handler = partial(SimpleHTTPRequestHandler, directory=str(Path(args.directory).resolve()))
            print(f"FMEA viewer: http://127.0.0.1:{args.port}", flush=True)
            ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
        elif args.command == "parse":
            from src.reliable.sections import parse_pdf
            path, batch = parse_pdf(args.pdf, args.output)
            print(f"Sections: {path}\nCount: {len(batch['sections'])}")
        elif args.command == "extract":
            from src.reliable.pipeline import extract
            print("Run:", extract(args.sections, args.output, args.model, args.max_sections, section_ids=args.section_id))
        elif args.command == "inspect":
            from src.reliable.pipeline import inspect, latest_review
            result = inspect(args.run)
            for section in result["results"]:
                print(section["section_id"], "output issues:", section["issues"])
                for c in section["candidates"]:
                    decision = latest_review(args.run, c)
                    print(c["candidate_id"], c["category"], "schema:", c["schema_valid"], "evidence:", c["evidence_valid"],
                          "review:", decision["decision"] if decision else "pending", c["issues"], c["warnings"])
                    print(json.dumps({"record": c["record"], "source_spans": c["resolved_evidence"]}, ensure_ascii=False))
            print(f"Responses: {result['responses']}/{result['total_sections']}")
        elif args.command == "report":
            from src.reliable.report import report
            print(report(args.run))
        elif args.command == "review":
            from src.reliable.pipeline import review
            print(json.dumps(review(args.run, args.candidate, args.decision, args.reviewer, args.note, args.reviewer_kind), indent=2))
        elif args.command == "build":
            from src.reliable.fmea import build
            folder, payload = build(args.run, args.allow_assistant)
            print(f"FMEA: {folder} ({len(payload['records'])} rows)")
        elif args.command == "reference-template":
            from src.reliable.evaluate import template
            if Path(args.output).exists():
                raise ValueError("Reference already exists; choose a new output path")
            write_json(args.output, template(read_json(args.sections)))
            print(args.output)
        else:
            from src.reliable.evaluate import evaluate
            path, report = evaluate(args.run, args.reference)
            print(path)
            print(json.dumps(report["totals"], indent=2))
            print("Coverage:", report["response_coverage"], "Reference:", report["reference_status"])
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
