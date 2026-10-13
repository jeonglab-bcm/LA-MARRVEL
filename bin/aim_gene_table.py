#!/bin/sh
"exec" "sh" "-c" 'p="${0%/*}/../.venv/bin/python"; [ -x "$p" ] || p=python; exec "$p" "$0" "$@"' "$0" "$@"
# Collapse AI-MARRVEL's transcript-level matrix (<run_id>.expanded.csv.gz) into
# the gene table the LA_MARRVEL workflow takes as --genecsv.
#
# AIM v1.2 writes <run_id>.gene.csv itself; v1.1.x and the hyunhwan-bcm fork
# stop at the expanded matrix, so runAIMARRVEL calls this to produce the same
# table: one row per variant (its most severe transcript), the variants worth
# reviewing grouped by gene, genes sorted by AIM's predict score.
import argparse
import ast

import pandas as pd

IMPACT = pd.CategoricalDtype(["MODIFIER", "LOW", "MODERATE", "HIGH"], ordered=True)
ZYGOSITY = {1: "Heterozygous", 2: "Homozygous"}
COLUMNS = [
    "geneSymbol", "geneEnsId", "varId", "clinvarSignDesc", "clinvarCondition",
    "CADD_PHRED", "zyg", "gnomadAF", "predict", "IMPACT_text", "Consequence", "phenoDict",
]


def variants(expanded):
    """One row per variant: the transcript with the highest impact, then the most phenotypes."""
    df = expanded.rename(columns={"Unnamed: 0": "varId"})
    df = df[df.geneSymbol != "-"].copy()
    df["clinvarCondition"] = df.clinvarCondition.fillna("-")
    df["Consequence"] = df.Consequence.str.split(",")
    df["IMPACT_text"] = df.IMPACT_text.astype(IMPACT)
    df["zyg"] = df.zyg.map(ZYGOSITY).fillna("Unknown")
    phenos = df.phenoList.map(ast.literal_eval)
    inheritance = df.phenoInhList.map(ast.literal_eval)
    df["phenoDict"] = [dict(zip(p, i)) for p, i in zip(phenos, inheritance)]
    df["phenoCount"] = phenos.map(len)
    return (
        df.sort_values(["varId", "IMPACT_text", "phenoCount"], ascending=[True, False, False])
        .drop_duplicates("varId")
        .drop(columns="phenoCount")
    )


def genes(vardf):
    """Group the reviewable variants by gene."""
    clinvar = vardf.clinvarSignDesc.fillna("")
    keep = (
        clinvar.str.contains("Pathogenic|Likely_pathogenic|Uncertain_significance")
        | (vardf.zyg == "Homozygous")
        | vardf.IMPACT_text.isin(["HIGH", "MODERATE"])
        | (vardf.CADD_PHRED >= 15)
    )
    vardf = vardf[keep]
    if vardf.empty:
        return pd.DataFrame(columns=COLUMNS)

    by_gene = vardf.groupby("geneSymbol")
    genedf = by_gene[["geneEnsId", "varId", "clinvarSignDesc", "clinvarCondition",
                      "CADD_PHRED", "zyg", "gnomadAF", "predict"]].agg(lambda x: list(set(x) - {"-"}))
    genedf["geneEnsId"] = genedf.geneEnsId.map(lambda x: max(x, default="-"))
    genedf["predict"] = genedf.predict.map(max)
    genedf["IMPACT_text"] = by_gene.IMPACT_text.max()
    genedf["Consequence"] = by_gene.Consequence.agg(
        lambda x: list({c for cs in x for c in cs if c is not None})
    )
    genedf["phenoDict"] = by_gene.phenoDict.agg(
        lambda x: {k: v or "Unknown" for d in x for k, v in d.items()}
    )
    return genedf.sort_values(["predict", "IMPACT_text"], ascending=False).reset_index()[COLUMNS]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="AIM <run_id>.expanded.csv.gz")
    parser.add_argument("--output", required=True, help="gene table CSV to write")
    args = parser.parse_args()

    genes(variants(pd.read_csv(args.input, low_memory=False))).to_csv(args.output, index=False)
