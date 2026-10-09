"""Groq extraction with durable raw responses and content-addressed resume."""
import json
import os
from pathlib import Path
from pydantic import ValidationError
from src.extraction.prompts import PROMPT
from src.extraction.schemas import Chunk, Extraction, TechnicalRecord
from src.io_utils import digest, read_json, write_json
from src.validation.normalizer import normalize_record
from src.validation.validator import validate_record
from src.validation.evidence import recover_evidence

DEFAULT_MODEL = "openai/gpt-oss-120b"
VERSION = "technical-fmea-v1"


def make_client():
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    key = os.environ.get("GROQ_API_KEY")
    if not key or key == "your_groq_api_key_here":
        raise ValueError("Set GROQ_API_KEY in your local .env or environment")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=90, max_retries=2)


def groq_completion(client, chunk, model):
    response = client.chat.completions.create(
        model=model, temperature=0, seed=42, max_completion_tokens=8192,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": PROMPT + "\nSchema:\n" + json.dumps(Extraction.model_json_schema())},
                  {"role": "user", "content": json.dumps(chunk.model_dump(), ensure_ascii=False)}],
    )
    choice = response.choices[0]
    return {"content": choice.message.content, "finish_reason": choice.finish_reason}


def fingerprint(record):
    # Deduplicate identical evidence from overlapping chunks without dropping raw candidates.
    def without_chunk_ids(value):
        if isinstance(value, dict):
            return {k: without_chunk_ids(v) for k, v in value.items() if k != "chunk_id"}
        if isinstance(value, list):
            return [without_chunk_ids(v) for v in value]
        return value
    return digest(without_chunk_ids(record.model_dump()))


def validate_response(raw, chunk, response_id):
    result = {"response_id": response_id, "chunk_id": chunk.chunk_id, "candidates": [], "issues": []}
    if raw.get("finish_reason") != "stop":
        result["issues"].append("Incomplete/refused response; raw output preserved")
        return result
    try:
        payload = json.loads(raw["content"])
        if not isinstance(payload, dict) or set(payload) != {"records"} or not isinstance(payload["records"], list):
            raise ValueError("Expected an object containing only a records list")
    except (ValueError, TypeError, KeyError) as exc:
        result["issues"].append(f"Malformed output: {type(exc).__name__}")
        return result
    for index, value in enumerate(payload["records"]):
        candidate = {"candidate_id": "CAND_" + digest([response_id, index])[:24],
                     "review_status": "pending", "validation_status": "invalid",
                     "raw_record": value, "record": None, "issues": []}
        try:
            record = normalize_record(TechnicalRecord.model_validate(value))
            record, repairs = recover_evidence(record, chunk)
            candidate["evidence_repairs"] = repairs
            candidate["record"] = record.model_dump()
            candidate["issues"] = validate_record(record, {chunk.chunk_id: chunk})
            if not candidate["issues"]:
                candidate["validation_status"] = "valid"
        except ValidationError as exc:
            candidate["issues"] = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
        result["candidates"].append(candidate)
    return result


def extract_batch(batch_path, output_root, model=None, complete=None, max_chunks=None):
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    model = model or os.environ.get("GROQ_MODEL", DEFAULT_MODEL)
    batch = read_json(batch_path)
    chunks = [Chunk.model_validate(c) for c in batch["chunks"]]
    if not chunks:
        raise ValueError("No extractable chunks; review parsing issues first")
    config = {"version": VERSION, "model": model, "prompt": PROMPT,
              "schema": Extraction.model_json_schema(), "temperature": 0, "seed": 42,
              "max_completion_tokens": 8192, "response_format": "json_object"}
    run_id = digest([config, [c.model_dump() for c in chunks]])[:24]
    run_dir = Path(output_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # A second process must not send the same run's chunks concurrently.
    import fcntl
    with (run_dir / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("This extraction run is already active") from exc
        manifest = {"run_id": run_id, "config": config, "chunks": [c.model_dump() for c in chunks]}
        write_json(run_dir / "manifest.json", manifest)
        client = None
        sent = 0
        for chunk in chunks:
            response_id = digest([config, chunk.model_dump()])
            raw_path = run_dir / "raw" / f"{response_id}.json"
            result_path = run_dir / "validated" / f"{response_id}.json"
            if raw_path.exists():
                raw = read_json(raw_path)
            else:
                if max_chunks is not None and sent >= max_chunks:
                    break
                try:
                    if complete is None:
                        client = client or make_client()
                        raw = groq_completion(client, chunk, model)
                    else:
                        raw = complete(chunk, model)
                    write_json(raw_path, raw)
                    sent += 1
                except Exception as exc:
                    # Do not persist exception text, headers or credentials.
                    write_json(run_dir / "last_error.json", {"chunk_id": chunk.chunk_id,
                               "error_type": type(exc).__name__, "status_code": getattr(exc, "status_code", None)})
                    raise RuntimeError(f"Extraction paused ({type(exc).__name__}); rerun the same command to resume. Run: {run_dir}") from None
            # Revalidation is local; even malformed responses never trigger automatic API calls.
            write_json(result_path, validate_response(raw, chunk, response_id))
        refresh_index(run_dir)
    return run_dir


def refresh_index(run_dir):
    candidates, issues, seen = [], [], {}
    for path in sorted((Path(run_dir) / "validated").glob("*.json")):
        result = read_json(path)
        issues.extend({"response_id": result["response_id"], "issue": i} for i in result["issues"])
        for candidate in result["candidates"]:
            if candidate["validation_status"] == "valid":
                key = fingerprint(TechnicalRecord.model_validate(candidate["record"]))
                if key in seen:
                    candidate["validation_status"] = "duplicate"
                    candidate["duplicate_of"] = seen[key]
                else:
                    seen[key] = candidate["candidate_id"]
            candidates.append(candidate)
    write_json(Path(run_dir) / "index.json", {"candidates": candidates, "issues": issues})
    return candidates
