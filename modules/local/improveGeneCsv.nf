process improveGeneCsv {
    cpus 1
    tag "$context.run_id"

    input:
    tuple val(context), path(genecsv, name: "gene.csv")

    output:
    tuple val(context), path("./${context.run_id}.improved.gene.csv")

    script:
    """
    #!${moduleDir}/../../.venv/bin/python
    import pandas as pd
    import json
    import ast
    from packaging.version import Version

    assert Version(pd.__version__) >= Version("3.0.0") # NOTE(JL): series.to_frame() has been changed, https://github.com/pandas-dev/pandas/pull/58018

    with open("${projectDir}/resources/gene_omim.json") as f:
        gene_omim = json.loads(f.read())
    hgncdf = pd.read_csv("${projectDir}/resources/hgnc_complete_set.txt", sep="\t", low_memory=False)
    d2pdf = pd.read_csv("${projectDir}/resources/disease_to_phenotypes.csv")
    d2pdf = d2pdf.groupby("disease_id").apply(lambda x: x.hpo_termname.to_list(), include_groups=False).rename("termnames")

    genesymbol2phenotypes = pd.DataFrame([entry for entry in gene_omim]).set_index("geneSymbol").phenotypes
    genesymbol2phenotypes = genesymbol2phenotypes[~genesymbol2phenotypes.index.duplicated(keep='last')]
    g2p = genesymbol2phenotypes.explode().to_frame()
    g2p = g2p[~g2p.phenotypes.isna()]
    g2p = g2p.join(pd.json_normalize(g2p.phenotypes)).drop(columns = ["phenotypes", "mimNumber"])
    g2p["phenotypeMimNumber"] = g2p.phenotypeMimNumber.apply(lambda x: f"OMIM:{int(x)}" if not pd.isna(x) else None)
    g2p = g2p.merge(d2pdf, left_on="phenotypeMimNumber", right_index=True, how='left')
    g2p["phenoDict"] = g2p.apply(lambda row: { row.phenotype: {"inheritance": row.phenotypeInheritance, "clinicalSynopsis": row.termnames } }, axis=1)
    genesymbol2phenotypes = g2p.groupby("geneSymbol").phenoDict.aggregate(lambda list_of_dicts: {k: v for d in list_of_dicts for k, v in d.items()})

    ensid2hgncapprovedsymbol = hgncdf[~hgncdf["ensembl_gene_id"].isna()].set_index("ensembl_gene_id")["symbol"]
    ensid2phenotypes = ensid2hgncapprovedsymbol.to_frame().merge(genesymbol2phenotypes, left_on="symbol", right_index=True).phenoDict


    def as_dict(x):
        return x if isinstance(x, dict) else {}


    if __name__ == "__main__":
        genedf = pd.read_csv(f"${genecsv}")[["geneSymbol", "varId", "geneEnsId", "zyg", "predict", "IMPACT_text", "Consequence", "clinvarSignDesc", "CADD_PHRED", "gnomadAF"]]

        genedf['phenoDict'] = genedf['geneEnsId'].map(ensid2phenotypes).combine(genedf['geneSymbol'].map(genesymbol2phenotypes), lambda a, b: as_dict(a) | as_dict(b))
        genedf['isTransHeterozygote'] = genedf.varId.apply(lambda x: "Yes" if len(ast.literal_eval(x)) > 1 else "No")

        genedf.to_csv("${context.run_id}.improved.gene.csv")
    """

    stub:
    """
    #!${moduleDir}/../../.venv/bin/python
    import csv

    with open("gene.csv", newline="") as fh:
        reader = csv.DictReader(fh)
        input_fieldnames = reader.fieldnames or []
        rows = list(reader)

    out_fields = list(dict.fromkeys(input_fieldnames + ["phenoDict", "isTransHeterozygote"]))

    for row in rows:
        row.setdefault("phenoDict", "{}")
        row.setdefault("isTransHeterozygote", "No")

    with open("${context.run_id}.improved.gene.csv", "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)
    """
}
