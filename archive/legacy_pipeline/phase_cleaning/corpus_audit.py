import fitz
import json
from pathlib import Path

from chunk_classifier import score_text

PDF_DIR = Path("knowledge_base")

results = []

for pdf_file in PDF_DIR.rglob("*.pdf"):

    try:

        doc = fitz.open(pdf_file)

        pages = len(doc)

        text = ""

        for page in doc:
            text += page.get_text()

        words = len(text.split())

        score = score_text(text)

        results.append({

            "file": pdf_file.name,
            "path": str(pdf_file),

            "pages": pages,
            "words": words,

            "domain_score": score["domain_score"],
            "noise_score": score["noise_score"],

            "domain_hits": score["domain_hits"],
            "noise_hits": score["noise_hits"]
        })

        print(f"Processed {pdf_file.name}")

    except Exception as e:

        print(pdf_file, e)

with open(
    "corpus_audit.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        results,
        f,
        indent=2,
        ensure_ascii=False
    )

print("Audit completed.")