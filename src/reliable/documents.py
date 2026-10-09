"""Explicit source-block selections for inspected manuals. No universal layout claims."""
import hashlib
from pathlib import Path
import fitz
from src.io_utils import digest, read_json, write_json
from src.reliable.sections import clean_with_map, _section, now


def parse_selection(pdf, profile, output="data/library/sections"):
    pdf = Path(pdf)
    document_id = "DOC_" + hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages, sections = [], []
    wanted = sorted({s["page"] for s in profile["sections"]})
    with fitz.open(pdf) as doc:
        total_pages = len(doc)
        for number in wanted:
            if not 1 <= number <= len(doc):
                raise ValueError(f"Invalid selected page: {number}")
            page = doc[number - 1]
            blocks = []
            for b in page.get_text("blocks", sort=False):
                if b[6] != 0:
                    continue
                cleaned, mapping = clean_with_map(b[4])
                blocks.append({"paragraph_id": f"P{number}_B{b[5]}", "page": number,
                               "bbox": list(b[:4]), "original_text": b[4], "cleaned_text": cleaned,
                               "clean_to_original": mapping, "issues": []})
            pages.append({"page": number, "width": page.rect.width, "height": page.rect.height,
                          "original_text": page.get_text(sort=False), "blocks": blocks})
    for spec in profile["sections"]:
        blocks = next(p["blocks"] for p in pages if p["page"] == spec["page"])
        selected = []
        for selector in spec["include"]:
            matches = [b for b in blocks if selector in b["cleaned_text"]]
            if len(matches) != 1:
                raise ValueError(f"{pdf.name}, {spec['id']}: selector {selector!r} matched {len(matches)} blocks; inspect layout")
            if matches[0] not in selected:
                selected.append(matches[0])
        section = _section(document_id, pdf.name, spec["id"], spec["title"], selected,
                           ["selected_source_blocks_not_entire_document", *spec.get("issues", [])])
        section["context"] = spec.get("context", "Section title is an editorial navigation label, not evidence. Use the source paragraphs.")
        sections.append(section)
    used = {p["paragraph_id"] for s in sections for p in s["paragraphs"]}
    payload = {"parser_version": "pymupdf-selected-blocks-v1", "segmentation_version": "inspected-block-profile-v1",
               "cleaning_version": "whitespace-only-v1", "pymupdf_version": fitz.VersionBind,
               "profile": profile, "document_id": document_id, "document_name": pdf.name,
               "total_document_pages": total_pages, "selected_pages": wanted, "pages": pages, "sections": sections,
               "coverage": "Selected technical passages only; other pages have not been extracted",
               "excluded_blocks": [{"paragraph_id": b["paragraph_id"], "page": p["page"], "reason": "outside inspected selection"}
                                   for p in pages for b in p["blocks"] if b["paragraph_id"] not in used]}
    batch_id = digest(payload)[:24]
    target = Path(output) / f"{batch_id}.json"
    if not target.exists():
        write_json(target, {**payload, "batch_id": batch_id, "created_at": now(), "source_path": str(pdf.resolve())})
    return target, read_json(target)


def process_library(plan_path, output="data/library", extract_live=False, max_sections=3):
    from src.reliable.pipeline import extract
    plan = read_json(plan_path)
    entries = []
    for profile in plan["documents"]:
        entry = {"document_name": Path(profile["pdf"]).name, "profile_id": profile["id"]}
        try:
            path, batch = parse_selection(profile["pdf"], profile, Path(output) / "sections")
            entry.update(batch_path=str(path), selected_sections=len(batch["sections"]),
                         total_pages=batch["total_document_pages"], selected_pages=batch["selected_pages"], status="parsed")
            if extract_live:
                # A per-document error does not erase or conceal other completed documents.
                entry["run"] = str(extract(path, Path(output) / "runs", max_sections=max_sections))
                entry["status"] = "extracted"
        except (ValueError, RuntimeError, OSError) as exc:
            entry.update(status="needs_attention", message=str(exc))
        entries.append(entry)
        print(entry, flush=True)
    payload = {"created_at": now(), "plan": str(plan_path), "documents": entries}
    path = Path(output) / "batches" / f"{digest(payload)[:24]}.json"
    write_json(path, payload)
    return path
