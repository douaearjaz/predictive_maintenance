# One-PDF pilot: quick guide

For the browser viewer and the selected passages from five additional PDFs, see
[FMEA_VIEW.md](FMEA_VIEW.md). This page documents the original one-PDF pilot.

**Goal:** one PDF → complete sections → sourced statements → review → FMEA draft.

Use this guide for the current work. [README.md](README.md) covers project setup
and the earlier pipeline. [PILOT_DETAILS.md](PILOT_DETAILS.md) preserves the full
technical explanation, schemas, experiment results and limitations.

## What changed

- Keep each fault heading, description and diagnostic information together.
- Preserve original text, cleaned text and source locations.
- Extract individual relationships before assembling FMEA rows.
- Separate isolated terms from supported relationships and ambiguous information.
- Build FMEA only from accepted statements; leave missing information and ratings null.

Example: `voltage imbalance → excessive current → increased temperature → insulation breakdown`.
Each arrow remains a separate statement with evidence.

## What is ready

The pilot processed **15 sections from `13-common-causes.pdf`** using Groq.
It produced 120 statements, 192 concept mentions and 10 ambiguities.
**24 candidates failed mechanical checks.** All 33 software tests passed;
that does not prove the extracted knowledge is correct.

After assistant source review, 15 statements were accepted and 4 candidates rejected.
The resulting **9-row FMEA is an assistant-verified draft, awaiting your review**.
The default human-reviewed export currently has no rows.

Open these files:

- [Source paragraphs and candidate review packet](data/pilot/runs/c7f8842146507b286f377664/reports/9207430fcdd7567cb9a86395.md)
- [FMEA draft (CSV)](data/pilot/runs/c7f8842146507b286f377664/fmea/30a83dcc20f4245ea0f6b2bb/fmea.csv)
- [Editable evaluation reference](evaluation/fluke15/reference.v2.assistant-draft.json)

The parser currently supports this PDF's layout only. Previous runs are preserved.

## Next step: review two sections first

Start with **Voltage imbalance (page 2)** and **Bearing wear (page 6)**.
Compare the review packet with the PDF. Check the direction of each relationship,
its cause/failure/symptom roles, qualifiers such as “can”, and the instrument's scope.
Record acceptance only when the source supports the statement; otherwise reject it
or mark it uncertain.

From the project root:

```bash
source myenv/bin/activate
RUN=data/pilot/runs/c7f8842146507b286f377664

# Refresh the readable review packet; this makes no API calls.
python -m src.reliable.cli report --run "$RUN"

# Example: run only after checking this statement against page 2.
python -m src.reliable.cli review --run "$RUN" \
  --candidate ATOM_2ae450641edcff529e874cbe \
  --decision accepted --reviewer "Your name" \
  --note "Checked the full paragraph: temperature leads to insulation breakdown."

# Export statements accepted by a human reviewer.
python -m src.reliable.cli build --run "$RUN"
```

Use `--decision rejected` or `--decision uncertain` when appropriate.
Do not edit generated candidate JSON to correct an extraction.

## Then evaluate and fix the remaining errors

Verify the expected facts in the evaluation reference against the PDF, saving your
changes in a separate copy. The supplied reference is an assistant-authored development
draft, not independent ground truth.

```bash
python -m src.reliable.cli evaluate --run "$RUN" \
  --reference evaluation/fluke15/reference.v2.assistant-draft.json
```

Use your reference copy's path when it is ready. The report lists matches, missing
facts, role/association differences and extra claims needing review. Some wording
matches depend on explicit aliases; an unmatched claim is not automatically false.

**Next development work:** fix recurring quotation and role errors, then test the
same sections again in a new run. Review terminology before merging labels such as
“failed bearing” and “bearing failure”. Keep the current run for comparison.

The original pilot ended here. The current selected-document extension is described
in [FMEA_VIEW.md](FMEA_VIEW.md); ontology, Bayesian networks and RAG remain outside this workflow.
