"""Auditable block segmentation for the Fluke 13-causes pilot, not a universal parser."""
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
import fitz
from src.io_utils import digest, read_json, write_json

PARSER_VERSION = "pymupdf-blocks-v2"
SEGMENTATION_VERSION = "fluke-13-causes-sections-v1"
CLEANING_VERSION = "whitespace-only-v1"


def now():
    return datetime.now(timezone.utc).isoformat()


def clean_with_map(text):
    """Only collapse whitespace; keep hyphens, spelling, units and punctuation."""
    chars, offsets = [], []
    for match in re.finditer(r"\S+", text):
        if chars:
            chars.append(" ")
            offsets.append(match.start() - 1)
        chars.extend(match.group())
        offsets.extend(range(match.start(), match.end()))
    return "".join(chars), offsets


def parse_pdf(pdf, output="data/pilot/sections"):
    pdf = Path(pdf)
    document_id = "DOC_" + hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages, sections = [], []
    with fitz.open(pdf) as doc:
        if len(doc) != 8 or "13 common causes" not in doc[0].get_text().lower():
            raise ValueError("This pilot profile supports only the eight-page Fluke 13-common-causes PDF")
        for page_number, page in enumerate(doc, 1):
            blocks = []
            for b in page.get_text("blocks", sort=False):
                if b[6] != 0:
                    continue
                cleaned, mapping = clean_with_map(b[4])
                blocks.append({"paragraph_id": f"P{page_number}_B{b[5]}", "page": page_number,
                               "bbox": list(b[:4]), "original_text": b[4], "cleaned_text": cleaned,
                               "clean_to_original": mapping,
                               "issues": ["line_end_hyphen_preserved"] if re.search(r"-\s*\n", b[4]) else []})
            pages.append({"page": page_number, "width": page.rect.width, "height": page.rect.height,
                          "original_text": page.get_text(sort=False), "blocks": blocks})
            if page_number == 1:
                selected = [b for b in blocks if b["bbox"][0] < 300 and b["bbox"][1] < 740]
                sections.append(_section(document_id, pdf.name, "overview", "Overview and contents", selected,
                                         ["overview_lists_are_mentions_not_causal_claims"]))
                continue
            headings = sorted([b for b in blocks if b["bbox"][0] < 100
                               and re.match(r"^\d{1,2}\s+[A-Za-z]", b["cleaned_text"])
                               and b["bbox"][3] - b["bbox"][1] > 20], key=lambda b: b["bbox"][1])
            for i, heading in enumerate(headings):
                number = int(heading["cleaned_text"].split()[0])
                end_y = headings[i + 1]["bbox"][1] if i + 1 < len(headings) else (430 if page_number == 8 else 750)
                body = sorted([b for b in blocks if b["bbox"][0] >= 260
                               and heading["bbox"][1] <= b["bbox"][1] < end_y], key=lambda b: b["bbox"][1])
                sections.append(_section(document_id, pdf.name, f"fault-{number:02}", heading["cleaned_text"],
                                         [heading, *body], ["diagram_text_excluded_review_original_page"]))
            if page_number == 8:
                selected = sorted([b for b in blocks if b["bbox"][0] < 100 and 430 <= b["bbox"][1] < 700],
                                  key=lambda b: b["bbox"][1])
                sections.append(_section(document_id, pdf.name, "strategies", "Four strategies for success", selected, []))
    expected = {"overview", "strategies", *[f"fault-{i:02}" for i in range(1, 14)]}
    if {s["section_id"] for s in sections} != expected or len(sections) != 15:
        raise ValueError("Layout profile did not find all 15 sections; manual parser review required")
    for section in sections:
        if section["section_id"].startswith("fault") and (len(section["paragraphs"]) < 4 or
                not any(p["cleaned_text"].startswith("Instrument to measure") for p in section["paragraphs"])):
            raise ValueError(f"Incomplete section: {section['section_id']}")
    used = {p["paragraph_id"] for s in sections for p in s["paragraphs"]}
    excluded = [{"paragraph_id": b["paragraph_id"], "page": p["page"],
                 "reason": "outside selected narrative regions: diagram, category heading, footer or publisher text"}
                for p in pages for b in p["blocks"] if b["paragraph_id"] not in used]
    payload = {"parser_version": PARSER_VERSION, "segmentation_version": SEGMENTATION_VERSION,
               "cleaning_version": CLEANING_VERSION, "pymupdf_version": fitz.VersionBind,
               "document_id": document_id, "document_name": pdf.name, "pages": pages,
               "sections": sections, "excluded_blocks": excluded}
    batch_id = digest(payload)[:24]
    target = Path(output) / f"{batch_id}.json"
    if not target.exists():
        write_json(target, {**payload, "batch_id": batch_id, "created_at": now(), "source_path": str(pdf.resolve())})
    return target, read_json(target)


def _section(document_id, name, section_id, title, paragraphs, issues):
    return {"section_id": section_id, "section": title, "subsection": None, "document_id": document_id,
            "document_name": name, "pages": sorted({p["page"] for p in paragraphs}),
            "original_text": "\n".join(p["original_text"] for p in paragraphs),
            "cleaned_text": "\n\n".join(p["cleaned_text"] for p in paragraphs),
            "paragraphs": paragraphs, "issues": issues}


def evidence_span(ev, section):
    paragraph = next((p for p in section["paragraphs"] if p["paragraph_id"] == ev["paragraph_id"]), None)
    if paragraph is None:
        raise ValueError("Evidence paragraph is outside this section")
    quote = ev["quote"]
    start = paragraph["cleaned_text"].find(quote)
    if not quote.strip() or start < 0:
        raise ValueError("Quote is not an exact nonempty cleaned-text substring")
    if paragraph["cleaned_text"].find(quote, start + 1) >= 0:
        raise ValueError("Quote is ambiguous within paragraph; use a longer quotation")
    end = start + len(quote)
    mapping = paragraph["clean_to_original"]
    raw_start, raw_end = mapping[start], mapping[end - 1] + 1
    return {**ev, "document_id": section["document_id"], "document_name": section["document_name"],
            "page": paragraph["page"], "section_id": section["section_id"], "section": section["section"],
            "clean_start": start, "clean_end": end, "original_start": raw_start, "original_end": raw_end,
            "original_quote": paragraph["original_text"][raw_start:raw_end], "bbox": paragraph["bbox"],
            "source_paragraph_cleaned": paragraph["cleaned_text"],
            "source_paragraph_original": paragraph["original_text"]}
