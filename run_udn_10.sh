#!/usr/bin/env bash
# Rerank the UDN cohort, using the manifest maintained in LA_MARRVEL_RERANK_BATCH.
# Env overrides: MANIFEST, BATCH_REPO, INVOCATIONS, GENES, VENV.
# Extra nextflow args are passed through, e.g. ./run_udn_10.sh -stub-run
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

BATCH_REPO="${BATCH_REPO:-../LA_MARRVEL_RERANK_BATCH}"
MANIFEST="${MANIFEST:-$BATCH_REPO/published/manifest/samples_udn_manifest.csv}"
INVOCATIONS="${INVOCATIONS:-10}"
GENES="${GENES:-100}"
VENV="${VENV:-.venv}"

# The task scripts pin their interpreter in their own shebangs: bin/invoke_*_llm.py
# and the inline python in the local modules both resolve <repo>/.venv/bin/python
# relative to themselves, so they no longer depend on this shell's PATH.  Keep the
# activation so `python` here matches what the tasks use -- and note that pointing
# VENV at anything other than .venv only affects this shell, not the tasks.
if [[ -f "$VENV/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV/bin/activate"
else
    echo "warning: no virtualenv at $VENV -- the local module steps pin .venv/bin/python and will fail" >&2
fi

[[ -r "$MANIFEST" ]] || { echo "Manifest not readable: $MANIFEST" >&2; exit 1; }

samples=$(( $(wc -l < "$MANIFEST") - 1 ))
echo "udn cohort: $samples samples x $INVOCATIONS votes = $(( samples * INVOCATIONS * 2 )) LLM calls"
echo "python:           $(command -v python)"
echo "publishing to:    published/udn_10/<run_id>/"
echo

exec nextflow run workflows/rerank \
    -resume \
    --samples_manifest "$MANIFEST" \
    --invocationnumber_n "$INVOCATIONS" \
    --consideringgenes_g "$GENES" \
    --publishDirSuffix /udn_10 \
    "$@"
