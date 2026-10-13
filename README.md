# LA_MARRVEL Workflow

This repository contains a Nextflow pipeline (`workflows/la_marrvel`) that enriches candidate genes with phenotype metadata, generates structured LLM prompts, gathers multiple AI-driven prioritizations, and aggregates them into a consensus gene ranking for rare disease analysis.

## Requirements
- Nextflow 23.10+ and a Python 3.11 runtime available on worker nodes.
- Python dependencies listed in `requirements.txt` (install with `pip install -r requirements.txt` inside your virtual environment).
- Singularity 4.2.0+
- An LLM backend for each of the two model roles — `reasoning` (long-form analysis) and `extraction` (structured gene-rank extraction). `PROVIDER` sets both; `REASONING_PROVIDER` and `EXTRACTION_PROVIDER` override it per role, so the two steps can run on different backends.
  - `bedrock` (default): AWS CLI 2 and AWS Bedrock access to the Claude Sonnet 4 reasoning model, configured via standard AWS credentials or a `.env` file.
  - `openai`: any OpenAI-compatible `/v1` server, such as a `llama.cpp` `llama-server` hosting a Hugging Face model, reachable at `OPENAI_BASE_URL`.

  See `.env.example` for the variables each provider expects.
- Optional: a [Langfuse](https://langfuse.com) project (cloud or self-hosted) to trace the LLM calls; see [Tracing LLM calls with Langfuse](#tracing-llm-calls-with-langfuse).

## Inputs
The workflow takes either one sample on the command line, or many samples from a CSV manifest.

**One sample**
- `--input_vcf`: Variant Call Format (VCF) file listing variants found in the proband.
- `--hpostxt`: Text file listing HPO identifiers (one per line) describing the proband.

**Many samples**
- `--samples_manifest`: CSV with `run_id,genecsv,hpotxt` columns, one row per sample; see [docs/manifest_format.md](docs/manifest_format.md). Every sample runs in a single workflow, so they share one work directory and one `-resume` cache. `--run_id` is ignored in this mode because each row supplies its own. This mode starts from an existing gene table and does not run AI MARRVEL.

Optional arguments:
- `--ref_ver`: Reference version of the VCF file (`hg19`, `hg38`). Default: `hg19`
- `--genecsv`: Gene table output of AI MARRVEL. If provided, the workflow skips AI MARRVEL and only runs the LA_MARRVEL LLM portion.
- `--consideringgenes_g`: Top-N genes per prompt. Default: `100`
- `--invocationnumber_n`: Number of LLM votes. Default: `10`
- `--aim_store_dir`: Store location where AI MARRVEL will be installed within the workflow. Default: `./aim_store`
- `--run_id`: Namespace for outputs. Single-sample mode only. Default: `run1`
- `--publishDirSuffix`: Extra level under `published/`, e.g. `/udn_100` publishes to `published/udn_100/<run_id>/`. Must start with `/`. Use it to keep cohorts or parameter sweeps from overwriting each other when the same `run_id` appears in more than one run.
- `--min_votes`: Fewest surviving LLM votes a sample needs to be reranked; a sample with fewer is reported and left un-reranked. `0` means a simple majority of `--invocationnumber_n`. Default: `0`
- `--reason_before_extract`: With `RUN_STRATEGY=stratified`, finish every reasoning call before the first extraction starts (see [Pipeline stages](#pipeline-stages)). Ignored by `unified`. Default: `true`
- `--reuse_published_votes`: Copy LLM outputs already published under this `--publishDirSuffix` instead of calling the model again — a vote's reasoning when its `*.output.*.md` is non-empty, its extraction when its `*.prioritized.*.csv` is non-empty. See [Resuming an interrupted run](#resuming-an-interrupted-run). Default: `false`

How the LLM steps run is set by the `RUN_STRATEGY` environment variable rather than a parameter; see [Environment variables](#environment-variables).

## Running
The following command is an example run using included vcf and hpo term files.
```bash
nextflow run workflows/la_marrvel \
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

nextflow run workflows/la_marrvel \
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

`generate_manifest` parameters:
- `--genecsvGlob` (required): Glob matching every sample's gene table.
- `--hpotxtGlob` (required): Glob matching every sample's HPO list.
- `--run_id_regex`: Regex matched against each file name; its first capture group is the `run_id`. Unset, the `run_id` is the name of the file's parent directory.
- `--outfile`: Where to write the manifest. Default: `manifest/samples_manifest.csv`

Cohort runs are worth a look at `maxForks` in `modules/local/invokeLlms.nf`, which caps concurrent LLM tasks at 4 per process across the whole run.

### Resuming an interrupted run

`-resume` reuses the cached non-LLM stages, but the LLM processes (`invokeLlms`, `reasonLlm`, `extractLlm`) are never cached (`workflows/la_marrvel/nextflow.config`), because each call is a fresh sample. To pick an interrupted run up without repeating finished LLM calls, rerun it with the same `--publishDirSuffix` and `--reuse_published_votes true`:

```bash
nextflow run workflows/la_marrvel -resume \
    --samples_manifest manifest/samples_manifest.csv \
    --publishDirSuffix /cohort_g100 \
    --reuse_published_votes true
```

Votes already published are copied; only the missing ones call the model. To redo a specific vote, move both its `*.output.<i>.md` and its `*.prioritized.<i>.csv` out of `published/` before rerunning — with only the first moved, the new reasoning would be paired with the old extraction.

## Pipeline stages
1. **AI MARRVEL PORTION** (these parts are skipped if gene table `gene_csv` is supplied)
    1. **installAIMARRVELDeps** - downloads AI MARRVEL dependency files (reference genomes, etc) from aws S3 bucket. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **cloneAIMARRVEL** - clones AI MARRVEL git repository from github at version `v1.2.0-rc260512`. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **runAIMARRVEL** - runs the AI MARRVEL workflow within `aim_store_dir` using Singularity profile and generates a gene table.
Each stage below runs once per sample, keyed on `run_id`; with a manifest they run concurrently.

1. **generateHpodf** – maps supplied HPO IDs onto labels/definitions using `resources/hp.json`.
1. **improveGeneCsv** – augments the gene table with HGNC/OMIM phenotypes, inheritance metadata, and `isTransHeterozygote` flags via the cached resources in `workflows/la_marrvel/resources`.
1. **generatePrompt** – builds a markdown prompt that embeds the curated HPO and gene tables (limited to the first `g` genes).
1. **reasonLlm** – for each prompt iteration, calls `bin/invoke_reasoning_llm.py` to obtain a long-form analysis. With `--reason_before_extract` (the default) every reasoning call finishes before the first extraction starts, which saves model swaps when both models are served from one llama-swap host; `--reason_before_extract false` lets each vote go on to extraction as soon as its reasoning is done.
1. **extractLlm** – calls `bin/invoke_prioritize_llm.py` on each reasoning output to extract an ordered list of genes, which is cleaned to one gene symbol per row before it is written: entries naming several genes are split, each name is matched against the gene table in that run's own prompt, and repeats keep only their first, best-ranked row — so headings, commentary, and genes the model invented are dropped. Both scripts get their chat model from `bin/llm_provider.py`, which builds a Bedrock or an OpenAI-compatible client for each role independently (settings loaded through `.env`/environment variables). Both calls are traced through `bin/llm_tracing.py` when Langfuse is configured.
1. **invokeLlms** – with `RUN_STRATEGY=unified` (the default), reasonLlm and extractLlm above run as this one task per vote instead, so a retry resamples the reasoning as well as the extraction. `RUN_STRATEGY=stratified` runs them as the two separate steps. Set it in the environment or in `.env` (environment wins); `--reason_before_extract` only applies to `stratified`.
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
nextflow run workflows/la_marrvel --input_vcf ... --hpostxt ...
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

nextflow run workflows/la_marrvel --input_vcf ... --hpostxt ...
```

Both SDKs must be installed for a mixed run; `requirements.txt` already lists them. Structured-output binding and retry classification follow the model that is actually in use, so each role keeps its own provider's conventions.

Transient failures on either provider (throttling, timeouts, an unreachable server, a response cut off at `max_tokens`) exit with codes 137-150, which `modules/local/invokeLlms.nf` retries up to five times; a vote that still fails is dropped and the sample is ranked on the votes that remain (see `--min_votes`).

## Environment variables

Read from the shell environment or from `.env` at the repository root; a real environment variable wins. `.env.example` lists them with examples. Every `OPENAI_*`/`BEDROCK_*` setting below can be scoped to one role by inserting `REASONING` or `EXTRACTION` (alias `PRIORITIZE`) after the prefix — `OPENAI_EXTRACTION_MAX_TOKENS` — with the unscoped name as the fallback.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUN_STRATEGY` | `unified` | `unified`: reasoning and extraction run as one task per vote, so a retry resamples the reasoning too. `stratified`: separate tasks, with `--reason_before_extract` applying, and a retry re-extracts the same reasoning. Read by `workflows/la_marrvel/main.nf`. |
| `PROVIDER` | `bedrock` | Backend for both roles: `bedrock` or `openai`. |
| `REASONING_PROVIDER`, `EXTRACTION_PROVIDER` | `PROVIDER` | Backend for one role. `LLM_PROVIDER`, the old name, is ignored (a warning is logged). |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` | — | Bedrock credentials (standard AWS configuration also works). |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514-v1:0` | Bedrock model. |
| `BEDROCK_MAX_TOKENS` | `65536` | Reasoning output cap on Bedrock. |
| `BEDROCK_THINKING_BUDGET_TOKENS` | `50000` | Reasoning thinking budget on Bedrock. |
| `OPENAI_BASE_URL` (alias `OPENAI_API_BASE`) | `http://localhost:8080/v1` | OpenAI-compatible endpoint. |
| `OPENAI_API_KEY` | `sk-no-key-required` | API key; llama.cpp ignores it. |
| `OPENAI_MODEL` | `local-model` | Served model name. |
| `OPENAI_MAX_TOKENS` | `65536` | Output cap per call. A reasoning answer that hits it is cut off, and an extraction that hits it fails with exit 142; raise `OPENAI_EXTRACTION_MAX_TOKENS` if extractions keep failing that way. |
| `OPENAI_TIMEOUT` | `3600` | Seconds per call. |
| `OPENAI_TEMPERATURE` | server default | Reasoning temperature; keep it above 0 so the votes differ. |
| `OPENAI_ENABLE_THINKING` | not sent | Reasoning `chat_template_kwargs.enable_thinking` (Qwen3-style templates). |
| `OPENAI_EXTRACTION_TEMPERATURE` | `0.0` | Extraction temperature. Does not fall back to `OPENAI_TEMPERATURE`. |
| `OPENAI_EXTRACTION_ENABLE_THINKING` | `false` | Extraction thinking flag. Does not fall back to `OPENAI_ENABLE_THINKING`. |
| `OPENAI_STRUCTURED_OUTPUT_METHOD` | `json_schema` | How extraction requests structured output: `json_schema`, `function_calling` or `json_mode`. |
| `OPENAI_EXTRA_BODY` | — | JSON merged into every request body, e.g. `{"top_k": 20}`. |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | — | Turn on Langfuse tracing when both are set. |
| `LANGFUSE_HOST` | Langfuse cloud | Self-hosted Langfuse instance. |
| `LANGFUSE_TRACING_ENABLED` | `true` | `false` keeps the keys but stops tracing. |
| `LANGFUSE_TRACING_ENVIRONMENT`, `LANGFUSE_RELEASE` | — | Labels that separate cohorts or versions. |
| `LANGFUSE_SAMPLE_RATE` | `1` | Fraction of calls traced. |
| `LANGFUSE_TIMEOUT` | `5` | Seconds a task waits to flush its trace. |

## Tracing LLM calls with Langfuse

Every reasoning and extraction call can be reported to [Langfuse](https://langfuse.com), which is useful for watching a cohort run, comparing backends, and seeing what the model was actually sent. Tracing is opt-in and off until both keys are set:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"   # or your self-hosted instance

nextflow run workflows/la_marrvel --samples_manifest manifest/samples_manifest.csv
```

With either key unset the pipeline behaves exactly as before and reports nothing, so a `.env` without these variables needs no change.

How a run shows up in Langfuse:

- One trace per model call, named `la_marrvel.reasoning` or `la_marrvel.extraction`, carrying the prompt, the response, token usage, and latency.
- The sample's `run_id` is the **session id**, so a sample's `invocationnumber_n` votes and their extraction passes are grouped together.
- Each trace is tagged with its role and backend (`reasoning`/`extraction`, `bedrock`/`openai`) and records the `iteration` number and model id as metadata — enough to compare vote-to-vote variation, or one provider against the other, from the Langfuse UI.

Other variables (see `.env.example`): `LANGFUSE_TRACING_ENABLED=false` turns tracing off while keeping the keys, `LANGFUSE_TRACING_ENVIRONMENT` and `LANGFUSE_RELEASE` separate cohorts from test runs, and `LANGFUSE_SAMPLE_RATE` traces only a fraction of a large cohort.

Tracing never fails a task: a missing `langfuse` package, bad credentials, or an unreachable server is reported once on stderr (visible in the task's `.command.err`) and the run continues. Because each Nextflow task is its own short-lived process, it flushes its trace before exiting, which costs an unreachable Langfuse server a few seconds per task — `LANGFUSE_TIMEOUT` (default 5 s) caps that wait.

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

The files under `workflows/la_marrvel/resources/` are redistributed snapshots of publicly available biomedical databases:

| File | Source | Version/Download | License |
|------|--------|--------------|---------|
| `hp.json` | [Human Phenotype Ontology](https://hpo.jax.org/) | 2025-08-11 | [HPO License](https://hpo.jax.org/license) |
| `phenotype.hpoa` | [HPO Annotations](https://hpo.jax.org/data/annotations) | 2024-08-13 | [HPO License](https://hpo.jax.org/license) |
| `disease_to_phenotypes.csv` | [HPO Annotations](https://hpo.jax.org/data/annotations) | 2024-08-13 | [HPO License](https://hpo.jax.org/license) |
| `hgnc_complete_set.txt` | [HGNC](https://www.genenames.org/) | 2025-09-08 | [CC0](https://www.genenames.org/about/license/) |

This pipeline uses the Human Phenotype Ontology (versions noted above). Find out more at http://www.human-phenotype-ontology.org.

If you are redistributing or using this pipeline commercially, please review the upstream licenses for these resources.