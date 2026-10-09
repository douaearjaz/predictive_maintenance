# Preserved legacy pipeline

This folder is historical material, not an executable stage of the active pipeline.
Do not run its scripts as part of the new workflow. They include stale paths,
import-time file writes, web collection, ontology conversion, and random Bayesian
probabilities. Their outputs are not reviewed engineering knowledge.

`manifest.json` records original paths, current paths, reasons, and SHA-256 hashes
for all 80 migrated files (including PDFs moved into the active data directories).
Each hash was verified after migration. The original requirements are preserved here.
The local `.env` and `myenv/` were not moved or copied into this archive.

Reused concepts: PyMuPDF traversal and character-window chunking from pdf_parser.py;
its explicit-information-only prompt and checkpoint intent; validation/normalization
separation from validator.py; SHA-256 document identity from the collector. The
legacy keyword filters are preserved for future comparison, not activated as a
gate that could discard useful technical passages.
