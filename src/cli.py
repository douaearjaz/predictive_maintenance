"""Run from the project root with python -m src.cli."""
import argparse
from pathlib import Path
from src.io_utils import read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    parse = commands.add_parser("parse")
    parse.add_argument("--documents", default="data/documents/trusted")
    parse.add_argument("--output", default="data/chunks")
    parse.add_argument("--chunk-size", type=int, default=1500)
    parse.add_argument("--overlap", type=int, default=300)
    extract = commands.add_parser("extract")
    extract.add_argument("--chunks", required=True)
    extract.add_argument("--output", default="data/candidates")
    extract.add_argument("--model")
    extract.add_argument("--max-chunks", type=int)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--run", required=True)
    review = commands.add_parser("review")
    review.add_argument("--run", required=True)
    review.add_argument("--candidate", required=True)
    review.add_argument("--decision", choices=["approved", "rejected", "uncertain"], required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", required=True)
    review.add_argument("--output", default="data/reviewed")
    build = commands.add_parser("build")
    build.add_argument("--run", required=True)
    build.add_argument("--reviews", default="data/reviewed")
    build.add_argument("--output", default="data/fmea")
    build.add_argument("--relations-output", default="data/causal")
    args = parser.parse_args()
    try:
        if args.command == "parse":
            from src.ingestion.pdf_parser import parse_directory
            path, payload = parse_directory(args.documents, args.output, args.chunk_size, args.overlap)
            print(f"Chunks: {path}\nCount: {len(payload['chunks'])}; parsing issues: {len(payload['issues'])}")
        elif args.command == "extract":
            from src.extraction.extractor import extract_batch
            if args.max_chunks is not None and args.max_chunks < 1:
                raise ValueError("--max-chunks must be positive")
            print("Run:", extract_batch(args.chunks, args.output, args.model, max_chunks=args.max_chunks))
        elif args.command == "inspect":
            from src.extraction.extractor import refresh_index
            candidates = refresh_index(args.run)
            for c in candidates:
                print(c["candidate_id"], c["validation_status"], "; ".join(c["issues"]))
            manifest = read_json(Path(args.run) / "manifest.json")
            completed = len(list((Path(args.run) / "validated").glob("*.json")))
            print(f"Responses: {completed}/{len(manifest['chunks'])}; inspect {args.run}/index.json for evidence and output-level issues")
        elif args.command == "review":
            from src.extraction.schemas import ReviewDecision
            from src.validation.review import record_decision
            decision = ReviewDecision(candidate_id=args.candidate, decision=args.decision,
                                      reviewer=args.reviewer, note=args.note)
            record_decision(args.run, args.output, decision)
            print("Recorded:", args.candidate, args.decision)
        else:
            from src.fmea.fmea_builder import build_fmea
            from src.causal.relation_builder import build_relations
            folder, records = build_fmea(args.run, args.reviews, args.output)
            relations_path = Path(args.relations_output) / folder.name / "relations.json"
            relations = build_relations(records, relations_path)
            print(f"FMEA: {folder} ({len(records)} records)\nCandidate relations: {relations_path} ({len(relations)})")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
