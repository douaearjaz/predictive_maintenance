import fitz
import json
from pathlib import Path

from chunk_classifier import (
    score_text,
    classify_score
)
print(score_text)
print(classify_score)
CHUNK_SIZE = 1500
OVERLAP = 300

PDF_DIR = Path("knowledge_base")


def chunk_text(text):

    chunks = []

    start = 0

    while start < len(text):

        end = start + CHUNK_SIZE

        chunks.append(
            text[start:end]
        )

        start += (
            CHUNK_SIZE - OVERLAP
        )

    return chunks


filtered_chunks = []

total_chunks = 0
kept_chunks = 0

for pdf_file in PDF_DIR.rglob("*.pdf"):

    try:

        doc = fitz.open(pdf_file)

        text = ""

        for page in doc:
            text += page.get_text()

        chunks = chunk_text(text)

        total_chunks += len(chunks)

        for i, chunk in enumerate(chunks):

            score = score_text(chunk)

            decision = classify_score(score)

            if decision != "keep":
                continue
            decision = classify_score(score)

            print(
                f"domain={score['domain_score']} "
                f"noise={score['noise_score']} "
                f"hits={score['domain_hits']} "
                f"decision={decision}"
            )

            kept_chunks += 1

            filtered_chunks.append({

                "file": pdf_file.name,

                "chunk_id":
                f"{pdf_file.stem}_{i}",

                "text": chunk,

                "domain_score":
                score["domain_score"],

                "noise_score":
                score["noise_score"],

                "domain_hits":
                score["domain_hits"],

                "noise_hits":
                score["noise_hits"]

            })

        print(
            f"{pdf_file.name}: "
            f"{len(chunks)} chunks processed"
        )

    except Exception as e:

        print(
            f"Error processing {pdf_file}: {e}"
        )

with open(
    "filtered_chunks.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        filtered_chunks,
        f,
        indent=2,
        ensure_ascii=False
    )

print("\n===================")
print(f"Total chunks: {total_chunks}")
print(f"Kept chunks: {kept_chunks}")
print(f"Rejected chunks: {total_chunks - kept_chunks}")
print("===================\n")

print(
    f"Saved {len(filtered_chunks)} chunks "
    f"to filtered_chunks.json"
)

print("\nPDF Statistics\n")

for pdf_file in PDF_DIR.rglob("*.pdf"):

    try:

        doc = fitz.open(pdf_file)

        text = ""

        for page in doc:
            text += page.get_text()

        chunks = chunk_text(text)

        print(
            f"{pdf_file.name}: "
            f"{len(chunks)} chunks"
        )

    except Exception as e:

        print(
            f"{pdf_file.name}: ERROR -> {e}"
        )
