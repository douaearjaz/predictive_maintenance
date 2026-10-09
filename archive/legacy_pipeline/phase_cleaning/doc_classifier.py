import json

with open(
    "corpus_audit.json",
    "r",
    encoding="utf-8"
) as f:

    docs = json.load(f)

categories = []

for doc in docs:

    file_name = doc["file"].lower()

    category = "papers"

    if "fmea" in file_name:
        category = "fmea"

    elif any(
        word in file_name
        for word in [
            "manual",
            "handbook",
            "maintenance guide"
        ]
    ):
        category = "manuals"

    elif doc["noise_score"] > doc["domain_score"]:
        category = "noisy"

    elif doc["domain_score"] > 5:
        category = "useful"

    categories.append({

        "file": doc["file"],
        "path": doc["path"],
        "category": category

    })

with open(
    "document_categories.json",
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        categories,
        f,
        indent=2,
        ensure_ascii=False
    )

print("Classification completed.")