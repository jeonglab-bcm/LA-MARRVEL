# Rerank Workflow

This repository contains a Nextflow pipeline (`workflows/rerank`) that enriches candidate genes with phenotype metadata, generates structured LLM prompts, gathers multiple AI-driven prioritizations, and aggregates them into a consensus gene ranking for rare disease analysis.

## Requirements
- Nextflow 23.10+ and a Python 3.11 runtime available on worker nodes.
- Python dependencies listed in `requirements.txt` (install with `pip install -r requirements.txt` inside your virtual environment).
- Singularity 4.2.0+
- AWS CLI 2
- AWS Bedrock access to Claude Sonnet 4 reasoning model configured via standard AWS credentials or a `.env` file. See `.env.example` for the credential variables the scripts expect.

## Inputs
- `--input_vcf`: Variant Call Format (VCF) file listing variants found in the proband.
- `--hpostxt`: Text file listing HPO identifiers (one per line) describing the proband.
- Optional arguments: 
  - `--ref_ver`: Reference version of the VCF file (`hg19`, `hg38`). Default: `hg19`
  - `--gene_csv`: Gene table output of AI MARRVEL. If provided, the workflow skips AI MARRVEL and only runs the rerank portion.
  - `--consideringgenes_g`: Top-N genes per prompt. Default: `100`
  - `--invocationnumber_n`: Number of LLM votes. Default: `10`
  - `--aim_store_dir`: Store location where AI MARRVEL will be installed within the workflow. Default: `./aim_store`
  - `--run_id`: Namespace for outputs.

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

## Pipeline stages
1. **AI MARRVEL PORTION** (these parts are skipped if gene table `gene_csv` is supplied)
    1. **installAIMARRVELDeps** - downloads AI MARRVEL dependency files (reference genomes, etc) from aws S3 bucket. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **cloneAIMARRVEL** - clones AI MARRVEL git repository from github at version `v1.2.0-rc260512`. Stores in `aim_store_dir` and doesn't rerun automatically.
    1. **runAIMARRVEL** - runs the AI MARRVEL workflow within `aim_store_dir` using Singularity profile and generates a gene table.
1. **generateHpodf** – maps supplied HPO IDs onto labels/definitions using `resources/hp.json`.
1. **improveGeneCsv** – augments the gene table with HGNC/OMIM phenotypes, inheritance metadata, and `isTransHeterozygote` flags via the cached resources in `workflows/rerank/resources`.
1. **generatePrompt** – builds a markdown prompt that embeds the curated HPO and gene tables (limited to the first `g` genes).
1. **invokeLlms** – for each prompt iteration, calls `bin/invoke_reasoning_llm.py` to obtain a long-form analysis and `bin/invoke_prioritize_llm.py` to extract an ordered list of genes. Both scripts rely on `langchain_aws` with AWS Bedrock Claude access (credentials loaded through `.env`/environment variables).
1. **aggregate** – combines every prioritized list with a Tideman ranked-pairs consensus to produce `${run_id}.improved.reranked.gene.csv`.

Intermediate artifacts (prompts, LLM reasoning/output markdown, per-iteration rankings) are copied into `published/<run_id>/`.

## AWS Troubleshooting

The helper scripts invoke `dotenv.load_dotenv()` before touching Bedrock (`bin/invoke_reasoning_llm.py`, `bin/invoke_prioritize_llm.py`), so copy `.env.example` to `.env` and fill in the AWS identity that can reach Claude Sonnet 4 (the template lists `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION`).

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