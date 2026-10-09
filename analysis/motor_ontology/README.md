# Unified electric-motor knowledge model

Open **index.html** in a browser. Select a topic, search, or click a concept to
inspect accepted relationships and full source paragraphs. The viewer works locally.

This is one equipment-type model for an electric motor. It does not assume that
all manuals describe the same installed machine or that every action applies to
every motor. It covers bearings, alignment, windings, moisture, voltage imbalance,
starting/control and stalling, including available causes, damage, symptoms,
consequences, detection methods and maintenance actions.

Dashed links organize equipment and knowledge topics. Solid arrows display the
47 accepted qualified source claims. Semantic connectedness does not establish
causal completeness or probabilistic independence. Missing solutions remain unknown.

The motor/bearing/winding/shaft hierarchy and associated controller are explicitly
assistant-curated structure, pending domain review. A topic is not a physical part.
Two assistant-proposed vocabulary alignments join bearing failure across Fluke and
AC guidance, and misalignment/shaft misalignment across Fluke sections 7 and 10.
Original concept IDs, wording, contexts, review records and quotations remain intact.
These alignments do not assert owl:sameAs or universal applicability. Damaged bearings
are not merged with functional bearing failure. Timken repair guidance retains a
motor-specific applicability review flag.

Files:

- `motor_model.json`: complete integrated graph and provenance.
- `motor_model.ttl` and `motor_model.owl`: ontology classes, curated structural
  links and reified source claims with metadata. Qualified claims are not asserted
  as unconditional causal triples.
- `review_queue.json`: 138 excluded candidates (132 unreviewed, two uncertain,
  four rejected), retained as review material rather than graph facts.
- `manifest.json`: input hash, counts and RDF round-trip result.

This version consolidates the accepted snapshot. Review priorities remain the
bearing-to-motor-failure consequence, shaft-voltage damage chain and additional
misalignment relationships. Invalid quotations need corrected candidates with
provenance; a pending review is not an accepted fact. Original exports are preserved.

Rebuild from the project root:

```bash
myenv/bin/python -m src.reliable.motor_model \
  --source data/ontology/8ec228b61bde801bf5424fb6/ontology.json \
  --output analysis/motor_ontology \
  --queue analysis/bayesian_readiness/excluded_candidates.json
```

For the future Bayesian network, select random variables from reviewed dependencies.
Do not convert component or topic links into causal arrows. Equipment applicability,
terminology and relevant missing relationships need review first. Maintenance actions
stay in the knowledge model until an intervention/decision model is designed. The
earlier bearing-only Bayesian draft is a preliminary example, not the project scope.
