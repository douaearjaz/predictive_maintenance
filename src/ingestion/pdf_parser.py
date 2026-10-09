"""Read trusted PDFs with PyMuPDF; preserve physical (1-based) page numbers."""
import hashlib
from pathlib import Path
import fitz
from src.ingestion.chunker import chunk_page
from src.io_utils import digest, write_json


def parse_directory(pdf_dir, output_dir, chunk_size=1500, overlap=300):
    if not 0 <= overlap < chunk_size:
        raise ValueError("Require 0 <= overlap < chunk_size")
    files = sorted(Path(pdf_dir).rglob("*.pdf"))
    if not files:
        raise ValueError(f"No trusted PDFs found in {pdf_dir}")
    chunks, documents, issues = [], [], []
    seen = {}
    for path in files:
        name = path.relative_to(pdf_dir).as_posix()
        document_id = "DOC_" + hashlib.sha256(path.read_bytes()).hexdigest()
        if document_id in seen:
            issues.append({"document_name": name, "status": "duplicate_pdf", "canonical": seen[document_id]})
            continue
        try:
            with fitz.open(path) as doc:
                pages = [page.get_text(sort=True) for page in doc]
                documents.append({"document_id": document_id, "document_name": name,
                                  "path": str(path.resolve()), "pages": len(pages)})
            seen[document_id] = name
            for page, text in enumerate(pages, 1):
                if not text.strip():
                    issues.append({"document_name": name, "page": page, "status": "no_text_review_required"})
                chunks.extend(chunk_page(text, document_id, name, page, chunk_size, overlap))
        except Exception as exc:
            issues.append({"document_name": name, "status": "parse_error", "error_type": type(exc).__name__})
    payload = {"parser_version": "page-text-v1", "chunk_size": chunk_size, "overlap": overlap,
               "documents": documents, "chunks": [c.model_dump() for c in chunks], "issues": issues}
    batch_id = digest(payload)[:24]
    target = Path(output_dir) / f"{batch_id}.json"
    write_json(target, payload)
    return target, payload
