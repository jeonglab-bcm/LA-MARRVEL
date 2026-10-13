#!/usr/bin/env -S sh -c 'p=${0%/*}/../.venv/bin/python; [ -x "$p" ] || p=python; exec "$p" "$0" "$@"'
import argparse
import io
import re
import sys
import pydantic
import typing
import pandas as pd
import dotenv
import llm_provider
import llm_tracing

dotenv.load_dotenv()


class GenerankItem(pydantic.BaseModel):
    excerpt: typing.List[str]
    name: str
    rank: int


# Ceiling on `results` when the extraction runs by hand without --prompt and
# the candidate list is therefore unknown.
DEFAULT_MAX_RESULTS = 500


def generank_model(max_results):
    """``Generank`` whose ``results`` array is capped at ``max_results`` items.

    An unbounded array lets a grammar-constrained decode keep appending entries
    until it hits max_tokens, which the OpenAI client reports as
    ``LengthFinishReasonError`` rather than a usable answer.  pydantic's
    ``max_length`` becomes ``maxItems`` in the JSON schema, which llama.cpp
    turns into a bounded repetition in the sampling grammar so the model has to
    close the array.  (Real OpenAI rejects ``maxItems`` under ``strict``; this
    bound assumes an extraction endpoint that builds a grammar from the schema.)
    """

    class Generank(pydantic.BaseModel):
        """
        Extract prioritized gene ranks only.
        """
        results: typing.Annotated[
            typing.List[GenerankItem], pydantic.Field(max_length=max_results)
        ]

    return Generank


# The extraction model is asked for gene symbols but sometimes answers with a
# numbered list item, a symbol plus a description, several genes in one entry,
# or a heading it copied out of the reasoning ("Conclusion", "Final
# Prioritization").  clean_gene_names() reduces each entry to the symbols it
# actually names, so aggregate.nf sees one gene per row and can match every row
# against the gene table.
_LIST_PREFIX = re.compile(r"^\s*(?:\d+\s*[.)]|[-*\u2022])\s*")
# Descriptions come parenthesised, and are dropped before splitting so that a
# separator inside one ("HBB (Sickle Cell Disease / Beta-Thalassemia)") does not
# look like a second gene.
_PARENTHETICAL = re.compile(r"\([^)]*\)|\[[^\]]*\]")
# A hyphen only separates when it stands alone, so HLA-DRB1 survives.
_SEPARATORS = re.compile(r"\s*(?:[,;:/|+&]|(?<=\s)[-\u2013\u2014](?=\s)|\band\b|\bor\b)\s*")
_PUNCTUATION = " \t.,;:?!\"'`*"
# Fallback for a hand run without --prompt: symbols are upper case, may carry
# digits and hyphens (HLA-DRB1, NKX2-5), and in the C#orf# family a lower case
# "orf".  Requiring the whole fragment to look like this is what rejects prose.
# The pipeline always passes --prompt, and then only the candidate genes below
# are accepted instead -- a gene the model invented, or picked up from its own
# commentary, is not one of the genes we asked it to rank.
_GENE_SYMBOL = re.compile(r"[A-Z][A-Z0-9]*(?:orf[0-9]+)?(?:-[A-Z0-9]+)*")
_CSV_BLOCK = re.compile(r"```csv\s*\n(.*?)```", re.DOTALL)


def candidate_genes(prompt):
    """The gene symbols generatePrompt.nf put in front of the reasoning model.

    That is the top ``consideringgenes_g`` rows of the gene table, i.e. the only
    genes the answer is allowed to rank.
    """
    for block in _CSV_BLOCK.findall(prompt):
        table = pd.read_csv(io.StringIO(block))
        if "geneSymbol" in table.columns:
            return table["geneSymbol"].dropna().astype(str).str.strip().tolist()
    # Silently accepting nothing here would empty every prioritized CSV, so fail
    # the task instead (exit 1, which invokeLlms.nf does not retry).
    raise ValueError("no gene table found in the prompt: expected a ```csv block with a geneSymbol column")


def candidate_index(symbols):
    """Map upper-cased symbol to the table's spelling, first occurrence winning."""
    index = {}
    for symbol in symbols:
        index.setdefault(symbol.upper(), symbol)
    return index


def gene_names(entry, candidates=None):
    """Return the gene symbols named by one extracted entry, in order.

    With ``candidates`` (from :func:`candidate_index`) a fragment counts only if
    it is one of the genes shown to the model, compared case-insensitively and
    reported back in the gene table's spelling.
    """
    text = _PARENTHETICAL.sub(" ", _LIST_PREFIX.sub("", str(entry)))
    fragments = (f.strip(_PUNCTUATION) for f in _SEPARATORS.split(text))
    if candidates is None:
        return [f for f in fragments if len(f) > 1 and _GENE_SYMBOL.fullmatch(f)]
    return [candidates[f.upper()] for f in fragments if f.upper() in candidates]


def clean_gene_names(names, candidates=None):
    """One gene per row: entries naming several genes expand, the rest drop.

    A gene repeated later in the list -- on its own or inside a multi-gene
    entry -- keeps only its first, best-ranked row.
    """
    return (
        names.map(lambda entry: gene_names(entry, candidates))
        .explode()
        .dropna()
        .drop_duplicates(keep="first")
        .reset_index(drop=True)
    )


llm = llm_provider.prioritize_llm()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        required=True,
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    parser.add_argument(
        "--prompt",
        help="prompt file shown to the reasoning model; its gene table is the "
        "set of symbols an answer may name. Without it any gene-shaped word is "
        "accepted.",
    )
    # Tracing only: both default to None so the script still runs by hand.
    parser.add_argument(
        "--run_id",
        help="sample id, used as the Langfuse session id",
    )
    parser.add_argument(
        "--iteration",
        help="which of the N votes this invocation is, recorded on the trace",
    )
    args = parser.parse_args()
    with open(args.input) as f:    
        ai_content = f.read()

    candidates = None
    # No answer can name more genes than were shown to the reasoning model, so
    # the candidate list doubles as the bound on the extracted array.
    max_results = DEFAULT_MAX_RESULTS
    if args.prompt:
        with open(args.prompt) as f:
            candidates = candidate_index(candidate_genes(f.read()))
        max_results = max(len(candidates), 1)
    retry_on = (pydantic.ValidationError,) + llm_provider.retry_exceptions(llm)
    llm_provider.log_settings(llm, llm_provider.EXTRACTION)
    backend, model = llm_provider.describe(llm)
    with llm_tracing.trace(
        llm_provider.EXTRACTION,
        run_id=args.run_id,
        iteration=args.iteration,
        tags=(backend,),
        backend=backend,
        model=model,
    ) as config:
        # The in-process retries land on the same trace, so a retried extraction
        # shows up as several generations under one observation.
        try:
            generank = llm_provider.structured_output(llm, generank_model(max_results)).with_retry(retry_if_exception_type=retry_on).invoke(ai_content, config=config)
        except Exception as e:
            # Same contract as invoke_reasoning_llm.py: a transient failure that
            # outlived the in-process retries exits in 137-150 so invokeLlms.nf
            # reruns the task -- which resamples the reasoning step too, giving
            # the extraction a different input to work from.
            exit_code = llm_provider.retry_exit_code(e, llm)
            if exit_code is None:
                raise
            print(e, file=sys.stderr)
            sys.exit(exit_code)
    main_content = clean_gene_names(pd.DataFrame(generank.model_dump()['results']).name, candidates).to_csv()
    
    with open(args.output, "w") as f:
        f.write(main_content)
