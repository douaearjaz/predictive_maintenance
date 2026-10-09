"""Generate a portable, read-only technician FMEA viewer. No web dependencies."""
import csv
import hashlib
import html
import json
import shutil
from pathlib import Path
from src.io_utils import digest, read_json, write_json
from src.reliable.pipeline import inspect, latest_review
from src.reliable.fmea import build
from src.reliable.sections import now

ROOT = Path(__file__).resolve().parents[2]
LABELS = {"component": "Component", "function": "Function", "failure_mode": "Failure",
          "cause": "Possible cause", "effect": "Consequence", "symptom": "Signs / symptoms",
          "detection_method": "Checks / diagnosis", "maintenance_action": "Maintenance action"}


def escape(value):
    return html.escape(str(value), quote=True)


def values(field):
    return list(dict.fromkeys(v["value"] for v in field or []))


def field_html(field):
    if not field:
        return '<span class="unknown">Not stated</span>'
    items = []
    seen = set()
    for item in field:
        key = (item["value"], item["qualifier"], json.dumps(item.get("operating_conditions"), sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        qualifier = '' if item["qualifier"] == "asserted" else f'<small>{escape(item["qualifier"])}</small>'
        condition = item.get("operating_conditions")
        if condition:
            qualifier += f'<small>When: {escape(condition["text"])}</small>'
        items.append(f'<div>{escape(item["value"])}{qualifier}</div>')
    return ''.join(items)


def status_label(decision):
    if not decision:
        return "Needs review"
    if decision["decision"] == "accepted":
        return "Human reviewed" if decision["reviewer_kind"] == "human" else "Assistant source check"
    return {"rejected": "Rejected", "uncertain": "Uncertain"}.get(decision["decision"], "Needs review")


def collect(roots):
    manifests = set()
    for root in roots:
        path = Path(root)
        if (path / "manifest.json").exists():
            manifests.add(path / "manifest.json")
        elif path.exists():
            manifests.update(path.glob("*/manifest.json"))
    documents, rows, statements = [], [], []
    for path in sorted(manifests):
        run = path.parent
        manifest = read_json(path)
        if "sections" not in manifest:
            continue
        state = inspect(run)
        section_map = {s["section_id"]: s for s in manifest["sections"]}
        section = manifest["sections"][0]
        batch_path = Path(manifest["batch_path"])
        batch = read_json(batch_path) if batch_path.exists() else {}
        doc = {"run_id": manifest["run_id"], "document_id": section["document_id"],
               "name": section["document_name"], "responses": state["responses"], "selected_sections": state["total_sections"],
               "total_pages": batch.get("total_document_pages", len(batch.get("pages", []))),
               "selected_pages": batch.get("selected_pages", sorted({n for s in manifest["sections"] for n in s["pages"]})),
               "source_path": batch.get("source_path"), "created_at": manifest["created_at"], "issues": [], "fmea_rows": 0}
        for result in state["results"]:
            doc["issues"].extend(result["issues"])
            for candidate in result["candidates"]:
                if candidate["category"] != "statements":
                    continue
                decision = latest_review(run, candidate)
                statements.append({**candidate, "review": decision, "status_label": status_label(decision),
                                   "run_id": manifest["run_id"], "document_id": doc["document_id"],
                                   "document_name": doc["name"], "section_title": section_map[candidate["section_id"]]["section"]})
        _, fmea = build(run, allow_assistant=True)
        for row in fmea["records"]:
            doc["fmea_rows"] += 1
            rows.append({**row, "run_id": manifest["run_id"], "document_id": doc["document_id"],
                         "document_name": doc["name"], "section_title": section_map[row["section_id"]]["section"],
                         "status_label": "Human reviewed" if row["status"] == "human_reviewed_draft" else "Assistant source check"})
        documents.append(doc)
    rows.sort(key=lambda r: (-sum(bool(r.get(k)) for k in LABELS), "; ".join(values(r["failure_mode"])).casefold(), r["document_name"]))
    return {"created_at": now(), "documents": documents, "rows": rows, "statements": statements}


def source_links(evidence, sources):
    links = []
    for ev in evidence:
        key = (ev.get("document_id"), ev.get("page"))
        if key in links:
            continue
        links.append(key)
    return ' · '.join(f'<a href="{escape(sources[d])}#page={p}" target="_blank" rel="noopener">Open PDF · page {p}</a>'
                      for d, p in links if d in sources and isinstance(p, int))


def evidence_html(evidence, sources):
    blocks, seen = [], set()
    for ev in evidence:
        key = digest(ev)
        if key in seen:
            continue
        seen.add(key)
        blocks.append(f'<section class="evidence"><strong>{escape(ev.get("section", ""))} · page {escape(ev.get("page", ""))}</strong>'
                      f'<blockquote>{escape(ev.get("quote", ""))}</blockquote>{source_links([ev], sources)}'
                      f'<details><summary>Read the full source paragraph</summary><p>{escape(ev.get("source_paragraph_cleaned", ev.get("original_quote", "")))}</p></details></section>')
    return ''.join(blocks) or '<p>No exact evidence passed validation. Consult the source before using this statement.</p>'


def generate(roots, output="fmea_view"):
    output = Path(output)
    data = collect(roots)
    sources = {}
    (output / "sources").mkdir(parents=True, exist_ok=True)
    for doc in data["documents"]:
        if not doc["source_path"]:
            continue
        source = Path(doc["source_path"]).resolve()
        if not source.is_relative_to(ROOT / "data" / "documents") or source.suffix.lower() != ".pdf" or not source.exists():
            continue
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        if "DOC_" + checksum != doc["document_id"]:
            raise ValueError(f"Source PDF changed: {doc['name']}")
        target = output / "sources" / f"{checksum}.pdf"
        if not target.exists():
            shutil.copyfile(source, target)
        sources[doc["document_id"]] = f"sources/{checksum}.pdf"
    fmea_rows, dialogs, cards = [], [], []
    for i, row in enumerate(data["rows"]):
        evidence = [e for field in LABELS for value in row.get(field) or [] for e in value["evidence"]]
        searchable = ' '.join([row["document_name"], row["section_title"], *[v for field in LABELS for v in values(row.get(field))]])
        fmea_rows.append(f'<tr data-doc="{escape(row["document_id"])}" data-status="{escape(row["status_label"])}" data-search="{escape(searchable.lower())}">'
                         f'<td><button class="row-open" data-open="fmea-{i}">{escape("; ".join(values(row["failure_mode"])))}</button>'
                         f'<small>{escape(row["section_title"])}</small></td>'
                         + ''.join(f'<td>{field_html(row.get(field))}</td>' for field in ["cause", "symptom", "detection_method", "maintenance_action"])
                         + f'<td><span class="badge">{escape(row["status_label"])}</span><small>{escape(row["document_name"])}</small><button data-open="fmea-{i}" class="text-button">Details & sources →</button></td></tr>')
        fields = ''.join(f'<div><dt>{title}</dt><dd>{field_html(row.get(field))}</dd></div>' for field, title in LABELS.items())
        dialogs.append(f'<dialog id="fmea-{i}"><button class="close" aria-label="Close details">×</button><p class="eyebrow">{escape(row["status_label"])}</p>'
                       f'<h2>{escape("; ".join(values(row["failure_mode"])))}</h2><p>{escape(row["document_name"])}</p>'
                       f'<dl class="field-grid">{fields}</dl><h3>Source evidence</h3>{evidence_html(evidence,sources)}'
                       '</dialog>')
    for i, c in enumerate(data["statements"]):
        r = c["record"]
        if not r:
            continue
        valid = c["schema_valid"] and c["evidence_valid"] and not c["issues"]
        label = c["status_label"] if valid else "Evidence / structure issue"
        relation_labels = {"CAUSES": "can cause / causes", "LEADS_TO": "leads to", "HAS_SYMPTOM": "has sign", "DETECTED_BY": "checked using", "MITIGATED_BY": "addressed by", "HAS_FAILURE_MODE": "can fail as", "HAS_FUNCTION": "has function", "AFFECTS": "affects", "ASSOCIATED_WITH": "associated with"}
        search = ' '.join([r["subject"]["text"], r["object"]["text"], c["document_name"], c["section_title"]]).lower()
        cards.append(f'<article class="statement" data-doc="{escape(c["document_id"])}" data-status="{escape(label)}" data-search="{escape(search)}">'
                     f'<span class="badge">{escape(label)}</span><h3>{escape(r["subject"]["text"])}</h3>'
                     f'<p class="relation">{escape(relation_labels.get(r["relation"],r["relation"]))} →</p><p><strong>{escape(r["object"]["text"])}</strong></p>'
                     f'<small>Source wording: {escape(r["qualifier"])}</small><small>{escape(c["document_name"])} · {escape(c["section_title"])}</small>'
                     f'<button data-open="statement-{i}" class="text-button">Read evidence →</button></article>')
        errors = ''.join(f'<li>{escape(x)}</li>' for x in c["issues"] + c["warnings"])
        dialogs.append(f'<dialog id="statement-{i}"><button class="close" aria-label="Close details">×</button><p class="eyebrow">{escape(label)}</p>'
                       f'<h2>{escape(r["subject"]["text"])} → {escape(r["object"]["text"])}</h2>'
                       f'<p>Relation: {escape(r["relation"])}. Source wording: {escape(r["qualifier"])}.</p>'
                       f'<p>Conditions: {escape(r["operating_conditions"]["text"] if r["operating_conditions"] else "Not stated")}</p>'
                       f'{evidence_html(c["resolved_evidence"],sources)}<details><summary>Extraction checks</summary><ul>{errors}</ul>'
                       '</details></dialog>')
    documents = ''.join(f'<article class="document"><h3>{escape(d["name"])}</h3><p>{d["fmea_rows"]} FMEA rows · {d["responses"]}/{d["selected_sections"]} selected passages extracted</p>'
                        f'<p>Selected physical pages: {escape(", ".join(map(str,d["selected_pages"])))} · Document: {d["total_pages"]} pages</p>'
                        f'<p>Selected passages only; full document coverage is not claimed.</p>'
                        f'<a href="{escape(sources[d["document_id"]])}" target="_blank" rel="noopener">Open source PDF →</a>'
                        f'<details><summary>Extraction details</summary><p>Run: {escape(d["run_id"])}<br>{escape("; ".join(d["issues"]))}</p></details></article>'
                        for d in data["documents"] if d["document_id"] in sources)
    options = ''.join(f'<option value="{escape(d)}">{escape(n)}</option>' for d,n in sorted({(d["document_id"],d["name"]) for d in data["documents"]}, key=lambda x:x[1]))
    template = Path(__file__).with_name("viewer.html").read_text()
    replacements = {"@@ROWS@@": ''.join(fmea_rows), "@@CARDS@@": ''.join(cards), "@@DIALOGS@@": ''.join(dialogs),
                    "@@DOCUMENTS@@": documents, "@@OPTIONS@@": options, "@@ROWCOUNT@@": str(len(data["rows"])),
                    "@@STATEMENTCOUNT@@": str(len(cards)), "@@DOCCOUNT@@": str(len({d["document_id"] for d in data["documents"]})),
                    "@@DATE@@": escape(data["created_at"][:16].replace('T',' ') + ' UTC')}
    # Single-pass replacement prevents source text from being interpreted as template markers.
    import re
    content = re.sub(r"@@[A-Z]+@@", lambda m: replacements.get(m.group(),m.group()), template)
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(content, encoding="utf-8")
    write_json(output / "fmea.json", {"created_at":data["created_at"], "records":data["rows"]})
    columns = ["document_name", "status_label", *LABELS]
    for field in LABELS:
        columns.extend([field + "_qualifiers", field + "_conditions"])
    with (output / "fmea.csv").open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in data["rows"]:
            flat = {k: '; '.join(values(row.get(k))) if k in LABELS else row[k] for k in ["document_name", "status_label", *LABELS]}
            for field in LABELS:
                flat[field + "_qualifiers"] = '; '.join(dict.fromkeys(v["value"] + ': ' + v["qualifier"] for v in row.get(field) or []))
                flat[field + "_conditions"] = '; '.join(dict.fromkeys(v["value"] + ': ' + v["operating_conditions"]["text"] for v in row.get(field) or [] if v.get("operating_conditions")))
            # Spreadsheet-safe display export; canonical evidence is in JSON.
            writer.writerow({k: "'"+v if v.lstrip().startswith(('=','+','-','@')) else v for k,v in flat.items()})
    return output / "index.html"
