# Rerank Workflow

[![Tests](https://github.com/LiuzLab/LA_MARRVEL_RERANK/actions/workflows/pytest.yml/badge.svg)](https://github.com/LiuzLab/LA_MARRVEL_RERANK/actions/workflows/pytest.yml)

This repository contains a Nextflow pipeline (`workflows/rerank`) that enriches candidate genes with phenotype metadata, generates structured LLM prompts, gathers multiple AI-driven prioritizations, and aggregates them into a consensus gene ranking for rare disease analysis.

## Inputs
- `--genecsv`: CSV exported from upstream AI_MARRVEL (>= v1.2.0-rc251111).
- `--hpotxt`: Text file listing HPO identifiers (one per line) describing the proband.
- Optional knobs: `--consideringgenes_g` (top-N genes per prompt), `--invocationnumber_n` (number of LLM votes), `--runid` (namespace for outputs).

## Pipeline stages
1. **generateHpodf** – maps supplied HPO IDs onto labels/definitions using `resources/hp.json`.
2. **improveGeneCsv** – augments the gene table with HGNC/OMIM phenotypes, inheritance metadata, and `isTransHeterozygote` flags via the cached resources in `workflows/rerank/resources`.
3. **generatePrompt** – builds a markdown prompt that embeds the curated HPO and gene tables (limited to the first `g` genes).
4. **invokeLlms** – for each prompt iteration, calls `bin/invoke_reasoning_llm.py` to obtain a long-form analysis and `bin/invoke_prioritize_llm.py` to extract an ordered list of genes. Both scripts rely on `langchain_aws` with AWS Bedrock Claude access (credentials loaded through `.env`/environment variables).
5. **aggregate** – combines every prioritized list with a Tideman ranked-pairs consensus to produce `${runid}.improved.reranked.gene.csv`.

Intermediate artifacts (prompts, LLM reasoning/output markdown, per-iteration rankings) are copied into `published/<runid>/`.

## Requirements
- Nextflow 23.10+ and a Python 3.10 runtime available on worker nodes.
- Python dependencies listed in `requirements.txt` (install with `pip install -r requirements.txt` inside your virtual environment).
- AWS Bedrock access to Claude Sonnet 4 reasoning model configured via standard AWS credentials or a `.env` file consumed by the helper scripts. See `.env.example` for the credential variables the scripts expect.

The helper scripts invoke `dotenv.load_dotenv()` before touching Bedrock (`bin/invoke_reasoning_llm.py`, `bin/invoke_prioritize_llm.py`), so copy `.env.example` to `.env` and fill in the AWS identity that can reach Claude Sonnet 4 (the template lists `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION`).

## Running
```bash
nextflow run workflows/rerank \
  --genecsv data/proband.genes.csv \
  --hpotxt data/proband.hpo.txt \
  --consideringgenes_g 10 \
  --invocationnumber_n 10 \
  --runid proband_run
```

On completion, inspect `published/proband_run/` for prompt/LLM artifacts and `proband_run.improved.reranked.gene.csv` for the consensus prioritization.

### Dry runs with `-stub-run`
Every process in the pipeline has a lightweight `stub` block so you can validate the control-flow without AWS credentials or large resource downloads. Use the bundled nf-test fixtures and enable stub mode:

```bash
nextflow run workflows/rerank \
  -stub-run \
  --genecsv tests/fixtures/nf-test/genes/nf_test_run.improved.gene.csv \
  --hpotxt tests/fixtures/nf-test/hpo/proband.hpos.txt \
  --consideringgenes_g 10 \
  --invocationnumber_n 10 \
  --runid stub_demo
```

The run finishes quickly, emits placeholder markdown/CSV artifacts, and exercises every channel/combiner so you can iterate on workflow logic even when the full dependencies are unavailable.
