"""Tests for the gene-name cleaning in bin/invoke_prioritize_llm.py.

The messy cases below are taken from `published/**/ *.prioritized.*.csv`, i.e.
from what the extraction model has actually written during real runs.

Two matching modes are covered: against the candidate genes from the prompt,
which is what the pipeline does, and the gene-shaped-word fallback used when
the script is run by hand without --prompt.
"""

import importlib.util
import pathlib
import sys

import pandas as pd
import pytest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))


@pytest.fixture(scope="module")
def prioritize(monkeypatch_module):
    """Import the script as a module; it builds a client but calls nothing."""
    import dotenv

    # The script loads .env on import.  Whoever runs the tests may have one with
    # real credentials in it, so neutralise it and configure the import here.
    monkeypatch_module.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch_module.setenv("PROVIDER", "openai")
    monkeypatch_module.setenv("REASONING_PROVIDER", "openai")
    monkeypatch_module.setenv("EXTRACTION_PROVIDER", "openai")
    monkeypatch_module.setenv("OPENAI_BASE_URL", "http://localhost:1/v1")

    spec = importlib.util.spec_from_file_location(
        "invoke_prioritize_llm", BIN / "invoke_prioritize_llm.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROMPT = """\
Given HPO and Genes with Variants, Evaluate Gene 1 by 1:

HPO:
```csv
name,synonyms,definition
Anemia,['Low blood count'],A reduction in circulating hemoglobin.
```

Genes:
```csv
geneSymbol,clinvarSignDesc,CADD_PHRED,phenoDict
PRF1,['Pathogenic'],27.6,"{'Hemophagocytic lymphohistiocytosis': {'inheritance': 'AR'}}"
HBB,[],22.0,"{'Sickle cell anemia': {'inheritance': 'AR'}}"
CLDN16,[],21.0,"{'Hypomagnesemia': {'inheritance': 'AR'}}"
INVS,[],20.0,"{'Nephronophthisis': {'inheritance': 'AR'}}"
HLA-DRB1,[],19.0,"{}"
C9orf72,[],18.0,"{}"
```
"""


@pytest.fixture
def candidates(prioritize):
    return prioritize.candidate_index(prioritize.candidate_genes(PROMPT))


@pytest.mark.parametrize(
    "entry,expected",
    [
        # Already clean.
        ("RBM10", ["RBM10"]),
        ("HLA-DRB1", ["HLA-DRB1"]),
        ("SLC34A3", ["SLC34A3"]),
        # Symbol forms that must survive intact.
        ("C9orf72", ["C9orf72"]),
        ("NKX2-5", ["NKX2-5"]),
        ("MT-ND1", ["MT-ND1"]),
        # A description attached to one gene.
        ("PRF1 (High Priority)", ["PRF1"]),
        ("LYST (Chediak-Higashi Syndrome)", ["LYST"]),
        # The separator sits inside the description, not between two genes.
        ("HBB (Sickle Cell Disease / Beta-Thalassemia)", ["HBB"]),
        # List numbering.
        ("1. PRF1 (Perforin 1)", ["PRF1"]),
        ("- JAG1", ["JAG1"]),
        ("**PKD1**", ["PKD1"]),
        ("Rank 1: PRF1", ["PRF1"]),
        ("PRF1 - Perforin 1", ["PRF1"]),
        # Several genes in one entry.
        ("CLDN16 / INVS", ["CLDN16", "INVS"]),
        (
            "ATM, SLX4, FANCI, LYST, NLRP1, COX10, SLC34A3",
            ["ATM", "SLX4", "FANCI", "LYST", "NLRP1", "COX10", "SLC34A3"],
        ),
        ("TP53 and BRCA1", ["TP53", "BRCA1"]),
        # One gene plus prose.
        ("6. ABCC9 / Other Genes with Hepatosplenomegaly + Anemia + Fever?", ["ABCC9"]),
        # Headings and commentary copied out of the reasoning.
        ("Conclusion", []),
        ("Final Prioritization", []),
        ("Patient Phenotype Summary (HPO)", []),
        ("Let's check other genes.", []),
        ("Let's re-examine HBB.", []),
        ("", []),
    ],
)
def test_gene_names(prioritize, entry, expected):
    assert prioritize.gene_names(entry) == expected


def test_candidate_genes_reads_the_gene_table_from_the_prompt(prioritize):
    """The HPO block above it must not be mistaken for the gene table."""
    assert prioritize.candidate_genes(PROMPT) == [
        "PRF1",
        "HBB",
        "CLDN16",
        "INVS",
        "HLA-DRB1",
        "C9orf72",
    ]


def test_candidate_genes_fails_loudly_without_a_gene_table(prioritize):
    with pytest.raises(ValueError, match="geneSymbol"):
        prioritize.candidate_genes("HPO:\n```csv\nname\nAnemia\n```\n")


@pytest.mark.parametrize(
    "entry,expected",
    [
        ("PRF1", ["PRF1"]),
        ("1. PRF1 (Perforin 1)", ["PRF1"]),
        ("CLDN16 / INVS", ["CLDN16", "INVS"]),
        ("HLA-DRB1", ["HLA-DRB1"]),
        ("C9orf72", ["C9orf72"]),
        # Case is ignored, and the gene table's spelling is what gets written.
        ("prf1", ["PRF1"]),
        ("hla-drb1", ["HLA-DRB1"]),
        ("C9ORF72", ["C9orf72"]),
        # Gene-shaped, but not one of the genes the model was given: ABCC9 is
        # what run 989068 invented, and the fallback regex would have kept it.
        ("6. ABCC9 / Other Genes with Hepatosplenomegaly + Anemia + Fever?", []),
        ("TP53", []),
        # Prose is rejected here too.
        ("Conclusion", []),
        ("Let's re-examine HBB.", []),
        # Only the candidates in a mixed entry survive.
        ("ATM, PRF1, SLX4, HBB", ["PRF1", "HBB"]),
    ],
)
def test_gene_names_against_prompt_candidates(prioritize, candidates, entry, expected):
    assert prioritize.gene_names(entry, candidates) == expected


def test_clean_gene_names_uses_the_candidates_end_to_end(prioritize, candidates):
    names = pd.Series(
        [
            "Final Prioritization",
            "1. PRF1 (Perforin 1)",
            "CLDN16 / INVS",
            "ABCC9",
            "prf1 again",
            "HBB (Sickle Cell Disease / Beta-Thalassemia)",
            "INVS",
        ],
        name="name",
    )

    cleaned = prioritize.clean_gene_names(names, candidates)

    assert list(cleaned) == ["PRF1", "CLDN16", "INVS", "HBB"]
    assert list(cleaned.index) == [0, 1, 2, 3]


def test_clean_gene_names_expands_drops_and_renumbers(prioritize):
    names = pd.Series(
        [
            "Final Prioritization",
            "1. PRF1 (Perforin 1)",
            "CLDN16 / INVS",
            "Let's check other genes.",
            "HBB",
        ],
        name="name",
    )

    cleaned = prioritize.clean_gene_names(names)

    assert list(cleaned) == ["PRF1", "CLDN16", "INVS", "HBB"]
    # Rank is row order, so the index has to be renumbered after the reshuffle.
    assert list(cleaned.index) == [0, 1, 2, 3]
    # aggregate.nf reads the column by name.
    assert cleaned.name == "name"


def test_clean_gene_names_keeps_the_first_of_each_duplicate(prioritize):
    names = pd.Series(
        [
            "LYST (Chediak-Higashi Syndrome)",
            "CLDN16 / LYST",
            "HBB",
            "LYST",
            "HBB (Sickle Cell Disease)",
        ],
        name="name",
    )

    cleaned = prioritize.clean_gene_names(names)

    # LYST keeps rank 0, its repeats inside and after the multi-gene entry go.
    assert list(cleaned) == ["LYST", "CLDN16", "HBB"]
    assert list(cleaned.index) == [0, 1, 2]


def test_clean_output_matches_the_previous_csv_shape(prioritize):
    """Clean input must still produce byte-identical CSV to the old code path."""
    names = pd.Series(["RBM10", "HBB"], name="name")

    assert prioritize.clean_gene_names(names).to_csv() == names.to_csv()


def real_runs():
    """(prompt, prioritized csv) pairs from every real run in this checkout.

    Each extractLlm task directory holds the prompt it was given next to the
    CSV it produced, which is the pairing the pipeline itself makes; published
    runs are checked the same way.  Both trees are gitignored, so CI has
    neither and the test skips.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    pairs = []
    for csv in (root / "work").glob("*/*/*.prioritized.*.csv"):
        prompts = list(csv.parent.glob("*.prompt.md"))
        if prompts:
            pairs.append((prompts[0], csv))
    for prompt in (root / "published").rglob("*.prompt.md"):
        pairs += [
            (prompt, csv)
            for csv in (prompt.parent.parent / "llmoutputs").glob("*.prioritized.*.csv")
        ]
    return sorted(pairs)


def test_real_runs_clean_to_candidate_genes_only(prioritize):
    """Replay every real run against the candidate genes from its own prompt."""
    pairs = real_runs()
    if not pairs:
        pytest.skip("no work/ or published/ runs in this checkout")

    for prompt_path, csv_path in pairs:
        index = prioritize.candidate_index(
            prioritize.candidate_genes(prompt_path.read_text())
        )
        table = pd.read_csv(csv_path)
        # An extraction that returned nothing leaves a header-only file; it has
        # no genes to clean, which is not this step's failure to report.
        raw = table["name"] if "name" in table.columns else pd.Series([], dtype=object)
        cleaned = prioritize.clean_gene_names(raw, index)

        # Only genes the model was actually given, each at most once.
        assert set(cleaned) <= set(index.values()), csv_path
        assert not cleaned.duplicated().any(), csv_path
        # A row that already was a candidate symbol must survive cleaning.
        expected = {index[str(v).upper()] for v in raw if str(v).upper() in index}
        assert expected <= set(cleaned), csv_path


def test_tier_headings_fall_back_to_the_excerpt(prioritize, candidates):
    """bg_10_medgemma/576564: the tiers went into `name`, the genes into `excerpt`."""
    names = pd.Series(
        [
            "High Priority (Likely Pathogenic, Strong Phenotype Match)",
            "Medium Priority (Uncertain/Conflicting Status)",
            "Low Priority (Benign/Likely Benign)",
        ],
        name="name",
    )
    excerpts = pd.Series(
        [["PRF1", "HBB", "ABCC9"], ["CLDN16", "PRF1"], ["INVS", "HBB"]]
    )

    cleaned = prioritize.clean_gene_names(names, candidates, excerpts)

    # Tier order, then the order within each tier; ABCC9 is no candidate, and
    # a gene listed in two tiers stays in the better one.
    assert list(cleaned) == ["PRF1", "HBB", "CLDN16", "INVS"]
    assert list(cleaned.index) == [0, 1, 2, 3]
    assert cleaned.name == "name"


def test_excerpt_is_ignored_when_the_name_is_a_gene(prioritize, candidates):
    """Supporting quotes often mention other genes; those are not ranked."""
    names = pd.Series(["PRF1", "Conclusion"], name="name")
    excerpts = pd.Series([["HBB", "INVS"], []])

    cleaned = prioritize.clean_gene_names(names, candidates, excerpts)

    assert list(cleaned) == ["PRF1"]

