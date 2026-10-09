# One-PDF reliability milestone

This workflow implements **one PDF → coherent sections → atomic statements →
recorded review → FMEA draft**. It does not implement ontology, fault trees,
Bayesian networks or RAG. Do not run the full corpus yet.

## What the inspection found

The old parser used `page.get_text(sort=True)` followed by 1,500-character windows
with 300-character overlap. On this PDF, page-wide ordering introduced layout
spaces and diagram labels into prose. Window boundaries separated fault headings,
causal descriptions and diagnostic instruments. Saved old chunks include a
fragment beginning `put PWM signals`. The currently installed old chunker already
has token-boundary handling, so this audit does not assume all historical outputs
were produced by its current revision. It still has no notion of fault sections.

The old prompt requested complete FMEA records, making multi-step causal chains
awkward to represent. Its `valid` status combined schema/evidence checks but did
not establish semantic correctness. Heading/list mentions and incorrect instrument
associations could pass those checks.

Useful existing code is reused: PyMuPDF, Pydantic strict model primitives,
`src.io_utils` hashing and atomic JSON writes, and the configured Groq client.
Checkpoint/resume and content-bound review patterns are retained. The old CLI,
parser, extractor and generated runs remain available and unchanged; the new path
is `python -m src.reliable.cli` under `data/pilot/`.

## Parser scope and representation

`src/reliable/sections.py` implements a deliberately bounded layout profile for
the eight-page Fluke `13-common-causes.pdf`. It identifies numbered section heading
blocks and selects the narrative column until the next heading. The overview and
the final strategies section are separately retained: **15 complete sections**.
Every fault section contains its heading, description, impact, instrument and
criticality paragraph. Criticality prose is preserved as source, not converted to
an AMDEC score.

Original page text and **all** text blocks remain in the batch. Diagram text,
category headings, footers and publisher blocks outside selected regions are
listed in `excluded_blocks`; none is silently erased. Two source-page layouts
were rendered, and page 2 was visually checked. This is not a general solution for
arbitrary manuals, OCR, tables or sections spanning pages. An unsupported layout
fails rather than silently falling back to character windows.

Cleaning collapses whitespace only. It does not repair spelling, change units,
remove hyphens, rewrite technical terms or infer missing text. Line-end hyphens
are preserved and flagged. This conservatism still causes some model quotations
to fail exact matching; those responses remain available for review.

```json
{
  "section_id": "fault-02",
  "section": "2 Voltage imbalance",
  "subsection": null,
  "document_id": "DOC_<PDF sha256>",
  "document_name": "13-common-causes.pdf",
  "pages": [2],
  "original_text": "...",
  "cleaned_text": "...",
  "paragraphs": [{
    "paragraph_id": "P2_B6",
    "page": 2,
    "bbox": [268.71, 523.34, 547.97, 556.69],
    "original_text": "...",
    "cleaned_text": "...",
    "clean_to_original": [0, 1, 2],
    "issues": []
  }]
}
```

The offset array shown above is abbreviated. Each cleaned character maps to an
original block offset. Exact quotation matches resolve to original start/end,
original quotation, page, section and bounding box. Full original and cleaned
source paragraphs accompany resolved evidence, so anaphora and list introductions
can be checked without losing context. Page numbers are physical, one-based.

## Atomic extraction contract

`src/reliable/schema.py` defines strict `statements`, `mentions`, and `ambiguities`
collections. The LLM supplies content, never validation or approval flags.

```json
{
  "subject": {"text": "increased operating temperatures", "kind": "phenomenon"},
  "relation": "LEADS_TO",
  "object": {"text": "insulation breakdown", "kind": "failure_mode"},
  "qualifier": "leading to",
  "operating_conditions": null,
  "evidence": [{
    "paragraph_id": "P2_B6",
    "quote": "leading to insulation breakdown"
  }],
  "needs_context_review": false,
  "review_note": ""
}
```

This is a real live-extracted statement. Its short quotation requires the full
paragraph to resolve the subject; the validator flags missing literal endpoints,
and the review explicitly records that context check. The same paragraph produced
three separate statements:

`Imbalance → excessive current flow → increased operating temperatures → insulation breakdown`

The FMEA cause for insulation breakdown is **increased operating temperatures**;
the builder never substitutes upstream imbalance through transitive closure.

Supported relations are CAUSES, LEADS_TO, HAS_SYMPTOM, DETECTED_BY, MITIGATED_BY,
HAS_FAILURE_MODE, HAS_FUNCTION, AFFECTS and ASSOCIATED_WITH. Endpoint kinds include
component, function, failure_mode, cause, effect, symptom, detection_method,
maintenance_action, phenomenon and unknown. Unknown roles are not silently
promoted to failure modes.

The candidate envelope adds `schema_valid`, `evidence_valid`, issues, warnings,
resolved source spans and `semantic_review_status: pending`. Conditions require
their own quotations. Exact quotes do not prove entailment; context-dependent
instrument associations, missing literal endpoints and potential modality loss
are flagged. There is no automatic semantic approval.

## Reproduce the pilot

Run from the project root with the existing environment:

```bash
source myenv/bin/activate
python -m src.reliable.cli parse --pdf data/documents/trusted/13-common-causes.pdf

SECTIONS=data/pilot/sections/25fa319e05cce5f5489e5d05.json
RUN=data/pilot/runs/c7f8842146507b286f377664

# This exact experiment has completed. Unchanged configuration reuses its responses.
python -m src.reliable.cli extract --sections "$SECTIONS" \
  --model openai/gpt-oss-120b --max-sections 15
python -m src.reliable.cli report --run "$RUN"
```

Use the actual parser output if the parser/library/document changes. Extraction
allows at most 15 new requests per invocation and one document per run. Optional
repeated `--section-id fault-02` arguments select a smaller experiment; selection
changes run identity. `--max-sections` caps **new** requests, not total responses.
Only `extract` contacts Groq. No command traverses all PDFs in the pilot.

Run manifests contain parser/segmentation/cleaning/prompt/validator versions,
schema, model, parameters, source sections and creation time. Responses preserve
provider model, request ID, usage, finish reason and timestamp. A lock prevents
concurrent extraction of the same run. Raw responses are never resent merely
because validation fails. Rate errors leave durable checkpoints and error events.

Validation, evaluation, FMEA and review reports use separate content-addressed
artifacts. Review history is append-only. Evaluations include reference hash,
comparison rules, model configuration and time. Exact model output is not
guaranteed reproducible by temperature zero and a seed. Old runs under
`data/candidates/` are neither revalidated nor rewritten by this workflow.

## Manual review

Open the Markdown review packet generated by `report`: each section includes its
complete source paragraphs, candidate IDs, proposed roles, relation, qualifier,
conditions, quoted spans and current review decision. Compare against the PDF
when layout or meaning is uncertain.

Record a decision only after checking the specific statement:

```bash
python -m src.reliable.cli review --run "$RUN" \
  --candidate ATOM_2ae450641edcff529e874cbe \
  --decision accepted --reviewer "Your name" \
  --note "Checked page 2 full impact paragraph: temperature is the immediate cause; no causal step collapsed."

python -m src.reliable.cli build --run "$RUN"
```

`rejected` and `uncertain` are also available. Invalid/duplicate candidates cannot
be accepted. Reviews bind to the complete candidate and resolved evidence hash;
changed content requires another review. This version supports decisions, not
in-place corrections. Preserve bad output and create a new extraction configuration
when correcting the pipeline.

FMEA consumes only accepted statements. The default requires `reviewer_kind=human`.
The included reviews are explicitly `assistant`, not approvals made on your behalf.
The optional `build --allow-assistant` produces a visibly labeled
`assistant_verified_draft`. Without it, the current human-reviewed export has zero
rows. Mentions and ambiguities never become FMEA rows, even if their classification
was reviewed. Accepted statements without a direct FMEA mapping remain preserved.

## Evaluation

The editable files under `evaluation/fluke15/` cover all 15 sections and contain
expected typed concepts, qualified relations, forbidden associations, tags,
reference-review status and whether each list is exhaustive.

- `reference.assistant-draft.json`: initial source-grounded draft.
- `reference.v2.assistant-draft.json`: separate development revision with explicit
  comparison aliases after pilot inspection. It is **not a held-out benchmark**.

Both are assistant-authored and require human verification. Set an individual
section's `review_status` to `human_verified` after checking its expectations.
Use `pending` to exclude an unfinished section from scoring. Add facts and explicit
aliases; do not mark a partial list exhaustive. A blank template can be created:

```bash
python -m src.reliable.cli reference-template --sections "$SECTIONS" \
  --output evaluation/fluke15/reference.my-review.json

python -m src.reliable.cli evaluate --run "$RUN" \
  --reference evaluation/fluke15/reference.v2.assistant-draft.json
```

Comparison is deterministic: case/whitespace normalization plus explicit term,
relation and qualifier aliases. Section aliases avoid conflating different kinds
of imbalance across faults. V2 treats CAUSES/LEADS_TO as equivalent direct-causal
labels and groups unqualified causal wording; **can is never equated to asserted**.
Endpoint types and direction remain significant. Configure aliases to match your
annotation policy; the report records every rule used.

Reports list correct concepts/relations, missing concepts/relations, forbidden or
unsupported facts, role/association mismatches, qualifier/condition differences,
invalid candidates, extra facts needing adjudication and processing coverage.
Unprocessed sections are not reported as model omissions. For nonexhaustive
references, unlisted extra facts are **unassessed**, not automatically hallucinated.
Content matches and evidence validity are separate. An exact match can still have
an invalid quotation. No single precision/accuracy score is claimed from this
partial development reference.

## Completed experiment and FMEA draft

Live model: `openai/gpt-oss-120b` through Groq; run created
`2026-09-14T20:53:13.201729+00:00`. All **15/15** section responses completed.

| Observation | Count |
|---|---:|
| Atomic statements | 120 |
| Concept mentions | 192 |
| Ambiguities | 10 |
| Candidates with schema errors | 0 |
| Candidates with evidence errors | 23 |
| Candidates failing evidence or other mechanical checks | 24 |
| Candidates with review warnings | 63 |
| Assistant accepted / rejected | 15 / 4 |
| Remaining pending candidates | 303 |

V2 development-reference comparison: **24 concept matches, 8 relation matches,
15 missing concept matches, 14 missing relation matches, 8 role/association
mismatches, 1 qualifier/condition mismatch, and 103 unassessed extra relations**.
Zero matched forbidden claims does **not** establish zero hallucinations. Role
differences and missing aliases need adjudication against the source. The original
strict comparison is also retained; its zero relation matches illustrates why
lexical scores alone cannot establish extraction quality.

The nine-row assistant-verified draft contains:

| Failure mode | Immediate cause | Symptoms |
|---|---|---|
| Insulation breakdown | Increased operating temperatures | unknown |
| Bearing failure | Heavier load than designed for | unknown |
| Bearing failure | Inadequate or incorrect lubrication | unknown |
| Bearing failure | Ineffective bearing sealing | unknown |
| Bearing failure | Shaft misalignment | unknown |
| Bearing failure | Incorrect fit | unknown |
| Bearing failure | Normal wear | unknown |
| Bearing failure | Induced shaft voltages | unknown |
| Failed bearing | unknown | Increased drag; more heat; lower efficiency |

The bearing causes retain **can** and full introductory list context. “Failed
bearing” and “bearing failure” have not been merged in FMEA: comparison aliases
affect evaluation only, not production knowledge. This visibly exposes the need
for reviewed terminology alignment. FMEA matching is exact and section-local;
multiple causes generate separate rows and conditional evidence remains attached
to each field. Diagnostic facts for a `phenomenon` remain accepted statements but
are not forced onto a failure row.

Component, function, effect, detection and maintenance fields remain null where
no reviewed direct mapping exists. Severity, occurrence, detection rating and RPN
are null throughout. JSON retains field evidence, qualifiers, conditions, statement
IDs and review provenance; CSV stores those field objects as JSON to avoid losing
qualifiers or pretending a multi-value field is a single assertion.

Artifacts:

- [Section batch](data/pilot/sections/25fa319e05cce5f5489e5d05.json)
- [Run manifest](data/pilot/runs/c7f8842146507b286f377664/manifest.json)
- [Source-and-review packet](data/pilot/runs/c7f8842146507b286f377664/reports/9207430fcdd7567cb9a86395.md)
- [Real atomic chain](data/pilot/runs/c7f8842146507b286f377664/examples/voltage-imbalance-chain.json)
- [V2 evaluation](data/pilot/runs/c7f8842146507b286f377664/evaluations/09e327f76b895bc194147b25b8ed61c863ad3d01ed9f1e5980c8710c01ec5afe.json)
- [Assistant-verified FMEA JSON](data/pilot/runs/c7f8842146507b286f377664/fmea/30a83dcc20f4245ea0f6b2bb/fmea.json)
- [Assistant-verified FMEA CSV](data/pilot/runs/c7f8842146507b286f377664/fmea/30a83dcc20f4245ea0f6b2bb/fmea.csv)

## Tests, changes and stopping point

Run `python -m unittest discover -s tests -v`. The original 20 tests remain, with
13 new tests covering real-PDF segmentation, source offsets, exact condition
evidence, foreign/ambiguous quotes, malformed siblings, attempted model approval
flags, checkpoint/resume, truncated output, immutable manifests, review integrity,
duplicates, mention exclusion, no transitive FMEA cause, human/assistant separation,
and evaluation aliases/error categories.

Added: `src/reliable/{sections,schema,pipeline,fmea,evaluate,pilot_reference,report,cli,__init__}.py`,
`tests/test_reliable.py`, this guide, evaluation references and pilot artifacts.
Updated: `README.md` to point to the new workflow. Existing pipeline modules and
previous generated runs were not changed. This workspace has no Git repository,
so there is no Git diff/commit to report.

The one-PDF workflow is implemented and exercised, but broad extraction quality
is **not yet certified**. Quotation fidelity, role consistency, overly short
evidence and terminology alignment remain visible review issues. The next work
is human verification of this reference and draft, followed by targeted fixes on
these same sections. Do not expand to the corpus or downstream systems yet.
