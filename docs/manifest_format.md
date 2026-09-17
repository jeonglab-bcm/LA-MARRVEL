# Manifest format

Passed to the rerank workflow as `--samples_manifest`.

Required columns:
- `run_id` — output namespace for the sample; must be unique within the manifest
- `genecsv` — AI MARRVEL gene table for the sample
- `hpotxt` — HPO identifiers for the sample, one per line

Example:

```csv
run_id,genecsv,hpotxt
sampleA,data/sampleA.improved.gene.csv,data/sampleA.hpo.txt
sampleB,data/sampleB.improved.gene.csv,data/sampleB.hpo.txt
```

Notes:
- Relative paths are resolved relative to the manifest file's directory; absolute paths are used as given.
- `run_id` names every output for that sample (`<run_id>.prompt.md`, `<run_id>.improved.reranked.gene.csv`) and its publish directory (`published/<run_id>/`, or `published/<publishDirSuffix>/<run_id>/`).
- The manifest is validated before any task is submitted: a missing column, a duplicate `run_id`, an empty cell, or a path that does not exist stops the run immediately.
- This is the same format the `LA_MARRVEL_RERANK_BATCH` pipeline uses, so a manifest can be handed to either.

Generate one from a directory tree with `workflows/generate_manifest` — see the README.
