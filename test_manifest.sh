#!/usr/bin/env bash
# Build a manifest from a directory tree, then rerank every sample in it.
set -euo pipefail

INPUT_DIR="${1:?usage: $0 <input_dir>}"

nextflow run workflows/generate_manifest \
    --genecsvGlob "${INPUT_DIR}/*/genedf.csv" \
    --hpotxtGlob  "${INPUT_DIR}/*/hpos.txt" \
    --outfile manifest/samples_manifest.csv

nextflow run workflows/rerank \
    -resume \
    --samples_manifest manifest/samples_manifest.csv \
    --consideringgenes_g 100 \
    --invocationnumber_n 10 \
    --publishDirSuffix /cohort_g100
