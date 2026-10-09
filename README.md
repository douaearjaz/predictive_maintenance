# Traceable technical documents → FMEA

**Read the FMEA:** [open the viewer](fmea_view/index.html), or follow
[FMEA_VIEW.md](FMEA_VIEW.md) for the local web address and additional PDF workflow.

**First ontology draft:** [open the searchable connections](data/ontology/8ec228b61bde801bf5424fb6/index.html),
or see [ONTOLOGY.md](ONTOLOGY.md) to regenerate OWL, Turtle and JSON from accepted statements.

The reliability milestone uses the isolated **one-PDF atomic-statement pilot**:
see [PILOT.md](PILOT.md). Use `python -m src.reliable.cli` for that workflow.
The older `src.cli` commands below retain the earlier FMEA-row extraction format
for comparison. Existing runs are preserved.

Earlier workflow documented below: trusted PDFs → page-local chunks → Groq candidate extraction →
mechanical validation → explicit human review → FMEA JSON/CSV → candidate causal
relations. That older workflow does not generate an ontology. The new draft export above
uses accepted atomic statements; Neo4j, RAG and Bayesian networks remain outside its scope.

## Setup

Run all commands from the project root. Python 3.10+ is required; this project was
tested with the existing Python 3.12 environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Only if you do not already have .env:
cp -n .env.example .env
```

Edit your local `.env`:

```dotenv
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-120b
```

The existing `.env` was left untouched. Never commit it: `.gitignore` excludes it,
virtual environments, and generated outputs. Environment variables override `.env`.
The API key is read only from `GROQ_API_KEY`; the model defaults to
`openai/gpt-oss-120b`. `extract --model NAME` can override the configured model.

The client uses Groq's OpenAI-compatible endpoint with temperature 0, seed 42,
JSON-object output, and local Pydantic validation. Low temperature and a seed do
not guarantee identical provider responses. JSON syntax is not semantic validation.
See [Groq API reference](https://console.groq.com/docs/api-reference) and
[Groq structured output documentation](https://console.groq.com/docs/structured-outputs).
Only `extract` makes API calls and sends chunk text to Groq.

## Documents and parsing

Put selected PDFs in `data/documents/trusted/`. Six existing maintenance and
troubleshooting documents have been moved here. Two broader documents are retained
in `data/documents/reference/` for selective use. The duplicate-text polyphase
guide is preserved in the archive; its counterpart is active.

```bash
python -m src.cli parse
```

This prints `data/chunks/<batch_id>.json`. It includes document hashes and paths,
physical page numbers (1-based, not printed page labels), exact text windows,
character offsets, and parsing issues. Byte-identical PDFs are skipped with a
recorded issue. Differently encoded versions require manual duplicate review.
Rerunning unchanged inputs produces the same batch ID. A content change creates
a new ID. Optional `--documents`, `--chunk-size`, and `--overlap` are available.

For a small first run, copy just one chosen PDF into a separate input folder and
pass that folder with `--documents`; or use extraction's `--max-chunks 3`.

This first version extracts page text with PyMuPDF, favors line boundaries, and
never joins pages. It does not reconstruct tables or OCR scanned pages. Blank
text pages and unreadable documents are retained as issues for review. Tables,
diagrams, split sentences, and page-spanning statements need visual source review.
Do not interpret an empty extraction as proof that no technical knowledge exists.

## Extract and resume

Use the actual batch path printed by parsing:

```bash
BATCH=data/chunks/<batch_id>.json
python -m src.cli extract --chunks "$BATCH" --max-chunks 3
# Continue all remaining chunks using the same batch and model:
python -m src.cli extract --chunks "$BATCH"
```

The command prints `data/candidates/<run_id>`. A run captures model, prompt,
schema, settings, and source chunks. Raw responses are atomically saved after each
completed request, before validation. Resume reads them locally, including invalid
responses; rate/connection failures leave earlier results intact. The SDK retries
transient request failures up to twice, then the command exits with a resume message.
A file lock prevents concurrent extraction of the same run.

Changing the batch, model, schema, or prompt creates a separate run. Checkpoints
are scoped to that run. As with any remote request, a process crash after the API
responds but before local persistence may require resending that one chunk.
Malformed/truncated responses remain in `raw/` and appear as output-level issues;
they are not silently discarded or automatically resent. Review these cases before
starting a new extraction configuration. Partial runs can be reviewed and exported;
`inspect` shows response coverage so you can distinguish partial from complete work.

```text
data/candidates/<run_id>/
  manifest.json       # Exact config and input chunks
  raw/*.json          # Original content and finish reason
  validated/*.json    # Raw + normalized records, status, validation issues
  index.json          # All candidates, duplicates, output-level issues
  last_error.json     # Last failure if any; historical, not completion state
```

## Review candidates

```bash
RUN=data/candidates/<run_id>
python -m src.cli inspect --run "$RUN"
```

Read `$RUN/index.json` alongside the original PDF. For each field, check that the
exact quotation supports the proposed meaning and that cause, effect, symptom,
detection, and maintenance have not been conflated. Check relational wording and
qualifiers (`can`, `may`), operating context, and applicability to the component.

Mechanical validation checks shape, populated-field evidence, exact quote matches,
document/page/chunk identity, relation types and endpoint compatibility. It cannot
prove that the quotation entails the value. All candidates therefore start pending.
Normalization only collapses whitespace in values; quotes are unchanged. No alias
merges, fuzzy matches, or general-knowledge completion occur. Identical normalized
records/evidence from overlapping chunks are flagged as duplicates and preserved.
Paraphrased duplicates require human review.

Approve a mechanically valid candidate only after checking it:

```bash
python -m src.cli review --run "$RUN" --candidate CAND_<id> \
  --decision approved --reviewer "Your name" \
  --note "Checked fields and causal wording against the cited PDF page"
```

Use `--decision rejected` or `--decision uncertain` for other outcomes and explain
why in `--note`. All decisions and their history are stored under
`data/reviewed/<run_id>/<candidate_id>/`. Invalid and duplicate candidates cannot
be approved. Rejected and uncertain candidates remain preserved. This version
supports decisions, not in-place candidate corrections; reject/flag incorrect
records and improve the extraction configuration for a new run. Never edit raw
responses or generated candidate files to bypass validation.

## Build FMEA and candidate relations

```bash
python -m src.cli build --run "$RUN"
```

Outputs:

* `data/fmea/<run_id>/fmea.json`: approved records, evidence and review metadata.
* `data/fmea/<run_id>/fmea.csv`: values plus a JSON evidence column for every field.
* `data/fmea/<run_id>/excluded.json`: candidates excluded from this export and why.
* `data/causal/<run_id>/relations.json`: explicit candidate relations linked to FMEA IDs.

Every record distinguishes component, function, failure_mode, cause, effect,
symptom, detection_method, and maintenance_action. Missing fields remain JSON null
(empty CSV cells). Severity, occurrence, detection_rating and RPN are always unset
in this version; no assessment process has been implemented.

Only explicit extracted relation claims are exported: CAUSES (cause → failure),
RESULTS_IN (failure → effect/symptom), and DETECTED_BY (failure/symptom → detection).
No relationship is generated merely because two fields are populated. Multiple
possible causes are requested as separate scenarios/relations. All relation exports
remain `pending` even when their FMEA record has been approved. Quoted modal wording
must remain part of their interpretation; these are not deterministic engineering
assertions. No AND/OR logic or probability is inferred.

## Tests and examples

```bash
python -m unittest discover -s tests -v
```

Tests use mocked Groq responses and temporary PDF fixtures. They test supported
motor-fault fields with missing values left null, exact evidence, malformed output,
duplicates, invalid relations, review decisions, rate-limit interruption/resume,
configuration changes, and exports. They do not measure live-model extraction
quality. `examples/fmea.json` and `examples/relations.json` are generated by the
offline fixture flow and labeled as simulated examples, not reviewed real data.

## Structure and legacy preservation

```text
src/
  cli.py, io_utils.py
  ingestion/   pdf_parser.py, chunker.py
  extraction/  schemas.py, prompts.py, extractor.py
  validation/  validator.py, normalizer.py, review.py
  fmea/        fmea_builder.py
  causal/      relation_builder.py
data/
  documents/   trusted/, reference/
  chunks/, candidates/, reviewed/, fmea/, causal/
tests/         test_pipeline.py, fixtures/motor_fault.txt
examples/      fmea.json, relations.json
archive/legacy_pipeline/
  manifest.json, README.md, original scripts, artifacts, corpus, notebooks
.env.example, .gitignore, requirements.txt, README.md
```

The archive manifest records original/new paths and hashes for every migrated
file. No legacy experiment was deleted or reactivated. Reused code concepts are
PyMuPDF traversal, bounded character windows, explicit-only prompting,
checkpoint/resume, validation/normalization separation, and SHA-256 identity.
Legacy field mappings that promoted algorithms/data to components were not reused.
