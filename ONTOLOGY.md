# First maintenance ontology

The [unified electric-motor graph](analysis/motor_ontology/index.html) adds
equipment organization and explicit vocabulary alignments over this source-scoped
draft. See its [scope and review notes](analysis/motor_ontology/README.md).

[Open the first generated draft](data/ontology/8ec228b61bde801bf5424fb6/index.html):
62 concepts and 47 accepted statements across six PDFs. All 45 tests passed;
both RDF exports round-tripped successfully.

This draft organizes the accepted atomic statements behind the FMEA. Empty FMEA
fields add no facts. The inputs cover selected passages from six PDFs, not six
fully processed documents. Accepted assistant source checks remain draft data;
they are not technical approval.

Generate locally, without an LLM call:

```bash
source myenv/bin/activate
python -m src.reliable.cli ontology --allow-assistant
```

The command prints a versioned folder under `data/ontology/`. Open its `index.html`
for a searchable list of connections with quotations. The same folder contains:

- `ontology.owl`: the vocabulary and populated draft in RDF/XML.
- `ontology.ttl`: the same information in Turtle.
- `ontology.json`: concepts, statements, conditions, source evidence and exclusions.
- `manifest.json`: version, input fingerprint, counts and serialization checks.

Omit `--allow-assistant` to include only human-accepted statements. Existing
extractions, reviews and previous ontology exports are preserved.

The vocabulary uses Component, Function, FailureMode, Cause, Effect, Symptom,
DetectionMethod, MaintenanceAction and Phenomenon. These classes describe the
roles of extracted concepts, rather than individual installed machines. A concept
may have more than one role. Supported relations include causes, leadsTo,
hasSymptom, detectedBy, mitigatedBy, hasFailureMode and hasFunction.

For example, the accepted Fluke bearing statements describe inadequate lubrication
as a possible cause of bearing failure, and a failed bearing as having increased
drag. The small existing failure-name mapping joins those names. Quotations and
original extracted wording are retained.

Each connection is an EvidenceStatement with a subject, relation, object,
qualifier, operating conditions and source evidence. In RDF these are represented
with `rdf:subject`, `rdf:predicate` and `rdf:object`; the unqualified causal triple
is deliberately not asserted. This preserves “may” and conditions instead of
turning them into universal rules. The export supplies an OWL vocabulary and
source-supported claims, not causal inference or a completed domain taxonomy.
See the [W3C RDF primer](https://www.w3.org/TR/rdf11-primer/) for the underlying
graph format.

Identical labels connect within the same document section, including intermediate
steps of causal chains. Different source sections keep separate concept IDs;
matching words alone do not prove that equipment or operating contexts are the
same. No transitive causes, risk scores, fault-tree gates or probabilities are
invented. Source quotations remain accessible in HTML; internal review history
is retained only in the data exports.

Verification checks review eligibility, preserves qualifiers and quotations,
prevents inferred causal shortcuts, and round-trips both RDF file formats.
These checks verify export behavior, not engineering correctness or completeness.

## Python graph figures

```bash
python -m pip install -r requirements-visualization.txt
python -m src.reliable.plot_graph --ontology data/ontology/8ec228b61bde801bf5424fb6/ontology.json
```

The command prints a versioned `figures/` folder containing one unified graph as
PNG, SVG and the first page of a PDF. All concepts appear on one canvas; groups
without an existing relationship remain disconnected. SVG and PDF support sharp
zooming. Source tags distinguish concepts from different sections. The PDF adds
a source key and numbered evidence pages with full qualifiers and conditions.
Colors show concept roles, using the first matching role in legend order when
several apply. No new connections, concept merges or HTML are generated.
Earlier section-by-section figures remain preserved.
