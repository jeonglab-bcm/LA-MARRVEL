# Rerank Workflow

This repository contains a Nextflow pipeline (`workflows/rerank`) that enriches candidate genes with phenotype metadata, generates structured LLM prompts, gathers multiple AI-driven prioritizations, and aggregates them into a consensus gene ranking for rare disease analysis.

## Requirements
- Nextflow 23.10+ and a Python 3.11 runtime available on worker nodes.
- Python dependencies listed in `requirements.txt` (install with `pip install -r requirements.txt` inside your virtual environment).
- Singularity 4.2.0+
- An LLM backend for each of the two model roles — `reasoning` (long-form analysis) and `extraction` (structured gene-rank extraction). `PROVIDER` sets both; `REASONING_PROVIDER` and `EXTRACTION_PROVIDER` override it per role, so the two steps can run on different backends.
  - `bedrock` (default): AWS CLI 2 and AWS Bedrock access to the Claude Sonnet 4 reasoning model, configured via standard AWS credentials or a `.env` file.
  - `openai`: any OpenAI-compatible `/v1` server, such as a `llama.cpp` `llama-server` hosting a Hugging Face model, reachable at `OPENAI_BASE_URL`.

  See `.env.example` for the variables each provider expects.

## Inputs
The workflow takes either one sample on the command line, or many samples from a CSV manifest.

**One sample**
- `--input_vcf`: Variant Call Format (VCF) file listing variants found in the proband.
- `--hpostxt`: Text file listing HPO identifiers (one per line) describing the proband.

**Many samples**
- `--samples_manifest`: CSV with `run_id,genecsv,hpotxt` columns, one row per sample; see [docs/manifest_format.md](docs/manifest_format.md). Every sample runs in a single workflow, so they share one work directory and one `-resume` cache. `--run_id` is ignored in this mode because each row supplies its own. This mode starts from an existing gene table and does not run AI MARRVEL.

Optional arguments:
- `--ref_ver`: Reference version of the VCF file (`hg19`, `hg38`). Default: `hg19`
- `--genecsv`: Gene table output of AI MARRVEL. If provided, the workflow skips AI MARRVEL and only runs the rerank portion.
- `--consideringgenes_g`: Top-N genes per prompt. Default: `100`
- `--invocationnumber_n`: Number of LLM votes. Default: `10`
- `--aim_store_dir`: Store location where AI MARRVEL will be installed within the workflow. Default: `./aim_store`
- `--run_id`: Namespace for outputs. Single-sample mode only.
- `--publishDirSuffix`: Extra level under `published/`, e.g. `/udn_100` publishes to `published/udn_100/<run_id>/`. Must start with `/`. Use it to keep cohorts or parameter sweeps from overwriting each other when the same `run_id` appears in more than one run.

## Running
The following command is an example run using included vcf and hpo term files.
```bash
nextflow run workflows/rerank \
    --input_vcf "example/demo.vcf.gz" \
    --ref_ver "hg19" \
    --hpostxt "example/demo.hpos.txt" \
    --consideringgenes_g 100 \
    --invocationnumber_n 10 \
    --run_id proband_run
```

On completion, inspect `published/proband_run/` for prompt/LLM artifacts and `proband_run.improved.reranked.gene.csv` for the consensus prioritization (replace `proband_run` with your chosen `--run_id`).

### Running a cohort

Build a manifest, then run every sample in it:

```bash
nextflow run workflows/generate_manifest \
    --genecsvGlob "/path/to/input/*/genedf.csv" \
    --hpotxtGlob  "/path/to/input/*/hpos.txt" \
    --outfile manifest/samples_manifest.csv

nextflow run workflows/rerank \
    --samples_manifest manifest/samples_manifest.csv \
    --consideringgenes_g 100 \
    --invocationnumber_n 10 \
    --publishDirSuffix /cohort_g100
```

`generate_manifest` derives each `run_id` from the name of the directory holding the file, so it expects a `<run_id>/genedf.csv` + `<run_id>/hpos.txt` layout. For a flat layout, pass `--run_id_regex` instead and it is matched against the file name, using the first capture group:

```bash
nextflow run workflows/generate_manifest \
    --genecsvGlob "/path/to/gene_csvs/*.csv" \
    --hpotxtGlob  "/path/to/hpos/*.txt" \
    --run_id_regex '^([^.]+)' \
    --outfile manifest/samples_manifest.csv
```

A sample that matches only one of the two patterns is reported as a warning and left out of the manifest, so check the run's output before using it. The manifest is a plain CSV: edit it by hand to run a subset, or keep several alongside each other (one per cohort) and select with `--samples_manifest`.

Cohort runs are worth a look at `maxForks` in `modules/local/invokeLlms.nf`, which caps concurrent LLM calls at 2 across the whole run.

## Pipeline stages
1. **AI MARRVEL PORTION** (these parts are skipped if gene table `gene_csv` is supplied)
    1. **installAIMARRVELDeps** - downloads AI MARRVEL dependency files (reference genomes, etc) from aws S3 bucket. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **cloneAIMARRVEL** - clones AI MARRVEL git repository from github at version `v1.2.0-rc260512`. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **runAIMARRVEL** - runs the AI MARRVEL workflow within `aim_store_dir` using Singularity profile and generates a gene table.
Each stage below runs once per sample, keyed on `run_id`; with a manifest they run concurrently.

1. **generateHpodf** – maps supplied HPO IDs onto labels/definitions using `resources/hp.json`.
1. **improveGeneCsv** – augments the gene table with HGNC/OMIM phenotypes, inheritance metadata, and `isTransHeterozygote` flags via the cached resources in `workflows/rerank/resources`.
1. **generatePrompt** – builds a markdown prompt that embeds the curated HPO and gene tables (limited to the first `g` genes).
1. **invokeLlms** – for each prompt iteration, calls `bin/invoke_reasoning_llm.py` to obtain a long-form analysis and `bin/invoke_prioritize_llm.py` to extract an ordered list of genes. Both scripts get their chat model from `bin/llm_provider.py`, which builds a Bedrock or an OpenAI-compatible client for each role independently (settings loaded through `.env`/environment variables).
1. **aggregate** – combines every prioritized list with a Tideman ranked-pairs consensus to produce `${run_id}.improved.reranked.gene.csv`.

Intermediate artifacts (prompts, LLM reasoning/output markdown, per-iteration rankings) are copied into `published/<run_id>/`.

## Choosing a provider

`bin/llm_provider.py` builds the chat models for both invoke scripts. The scripts call `dotenv.load_dotenv()` first, so settings can live either in the shell environment or in a `.env` next to this README; real environment variables win over `.env` entries.

The pipeline calls two models and each picks its backend independently:

| Role | Script | Provider variable |
| --- | --- | --- |
| `reasoning` | `bin/invoke_reasoning_llm.py` | `REASONING_PROVIDER`, else `PROVIDER` |
| `extraction` | `bin/invoke_prioritize_llm.py` | `EXTRACTION_PROVIDER`, else `PROVIDER` |

Both default to `bedrock`. Every other setting can be scoped to one role the same way, by inserting `REASONING` or `EXTRACTION` after the provider prefix — `OPENAI_REASONING_BASE_URL`, `BEDROCK_EXTRACTION_MODEL_ID` — with the unscoped name (`OPENAI_BASE_URL`, `BEDROCK_MODEL_ID`) as the fallback. `PRIORITIZE` is still accepted as an alias for `EXTRACTION`, so existing `.env` files keep working.

Two exceptions to that fallback: the extraction step's temperature (`OPENAI_EXTRACTION_TEMPERATURE`, default `0.0`) and thinking flag (`OPENAI_EXTRACTION_ENABLE_THINKING`, default off) never inherit from the unscoped `OPENAI_TEMPERATURE`/`OPENAI_ENABLE_THINKING`, which exist to keep the *reasoning* votes diverse.

### bedrock (default)

Copy `.env.example` to `.env` and fill in the AWS identity that can reach Claude Sonnet 4 (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`). `BEDROCK_MODEL_ID`, `BEDROCK_MAX_TOKENS`, and `BEDROCK_THINKING_BUDGET_TOKENS` override the defaults.

### openai

Point the pipeline at a separate OpenAI-compatible server. For a Hugging Face model served by `llama.cpp`:

```bash
llama-server -hf <org>/<repo> --jinja --reasoning-format deepseek -c 32768 --port 8080
```

```bash
export PROVIDER=openai
export OPENAI_BASE_URL="http://<llama-server-host>:8080/v1"
export OPENAI_MODEL="<served model name>"   # llama.cpp accepts any name
nextflow run workflows/rerank --input_vcf ... --hpostxt ...
```

Notes on this path:
- `OPENAI_API_KEY` defaults to a placeholder because llama.cpp does not check it, but a real gateway in front of the server will.
- Reasoning is read from a `reasoning_content` field (`--reasoning-format deepseek`) or from inline `<think>` tags (`--reasoning-format none`); either way it lands in `*.reasoning.*.md` and is stripped out of `*.output.*.md`.
- Gene extraction is requested with a `json_schema` response format, which llama.cpp enforces as a sampling grammar. Set `OPENAI_STRUCTURED_OUTPUT_METHOD=function_calling` instead if your server prefers tool calls.
- `OPENAI_TIMEOUT` defaults to one hour per call; raise it for large contexts on slow hardware.
- See `.env.example` for the remaining knobs (`OPENAI_MAX_TOKENS`, `OPENAI_TEMPERATURE`, `OPENAI_EXTRA_BODY`, …).

### Mixing the two

Reason on a local llama-server, then extract the ranking with Bedrock:

```bash
export REASONING_PROVIDER=openai
export OPENAI_REASONING_BASE_URL="http://<llama-server-host>:8080/v1"
export OPENAI_REASONING_MODEL="<served model name>"

export EXTRACTION_PROVIDER=bedrock
export BEDROCK_EXTRACTION_MODEL_ID="us.anthropic.claude-sonnet-4-20250514-v1:0"
# plus the usual AWS_* credentials

nextflow run workflows/rerank --input_vcf ... --hpostxt ...
```

Both SDKs must be installed for a mixed run; `requirements.txt` already lists them. Structured-output binding and retry classification follow the model that is actually in use, so each role keeps its own provider's conventions.

Transient failures on either provider (throttling, timeouts, an unreachable server) exit with codes 137-150, which `modules/local/invokeLlms.nf` retries up to five times.

## Citing LA-MARRVEL

```bibtex
@misc{lee2026lamarrvelknowledgegroundedlanguageawarellm,
      title={LA-MARRVEL: A Knowledge-Grounded, Language-Aware LLM Framework for Clinically Robust Rare Disease Gene Prioritization}, 
      author={Jaeyeon Lee and Lin Yao and Hyun-Hwan Jeong and Zhandong Liu},
      year={2026},
      eprint={2511.02263},
      archivePrefix={arXiv},
      primaryClass={q-bio.GN},
      url={https://arxiv.org/abs/2511.02263}, 
}
```

## Example Data

Example data (`demo.vcf.gz`) was obtained from the publicly accessible AI-MARRVEL web platform (ai.marrvel.org). It is included here for demonstration purposes only.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

Note: [AI-MARRVEL](https://github.com/LiuzLab/AI_MARRVEL), which is fetched and invoked at runtime, is licensed under GPL-3.0.

### Third-Party Data

The files under `workflows/rerank/resources/` are redistributed snapshots of publicly available biomedical databases:

| File | Source | Version/Download | License |
|------|--------|--------------|---------|
| `hp.json` | [Human Phenotype Ontology](https://hpo.jax.org/) | 2025-08-11 | [HPO License](https://hpo.jax.org/license) |
| `phenotype.hpoa` | [HPO Annotations](https://hpo.jax.org/data/annotations) | 2024-08-13 | [HPO License](https://hpo.jax.org/license) |
| `disease_to_phenotypes.csv` | [HPO Annotations](https://hpo.jax.org/data/annotations) | 2024-08-13 | [HPO License](https://hpo.jax.org/license) |
| `hgnc_complete_set.txt` | [HGNC](https://www.genenames.org/) | 2025-09-08 | [CC0](https://www.genenames.org/about/license/) |

This pipeline uses the Human Phenotype Ontology (versions noted above). Find out more at http://www.human-phenotype-ontology.org.

If you are redistributing or using this pipeline commercially, please review the upstream licenses for these resources.