process generatePrompt {
    cpus 1

    publishDir "published/$context.run_id/prompt", mode: 'copy'
    tag "$context.run_id"

    input:
    path hpodf, name: 'hpodf.csv'
    path genecsv, name: 'genedf.csv'
    val context

    output:
    path "./${context.run_id}.prompt.md"

    script:
    """
    #!/usr/bin/env -S uv run --quiet --script

    import pandas as pd

    hpodf = pd.read_csv("./hpodf.csv")
    genedf = pd.read_csv("./genedf.csv")

    prompt = f\"""
    Given HPO and Genes with Variants, Evaluate Gene 1 by 1 based on ACMG and phenotype matching to Prioritize Pathogenic Genes:

    Notes:
    zyg=het & isTransHeterozygote=yes: a second pathogenic variant is present in both alleles of a gene, which meets the recessive disease criteria.
    zyg=hom may mean hemizygous for chromosome X if the proband is male
    The data is generated from whole exome sequencing, finding additional pathogenic variant is unlikely.

    HPO:
    ```csv
    {hpodf.drop(columns="id").to_csv(index=False)}
    ```

    Genes:
    ```csv
    {genedf.rename(columns={"IMPACT_text": "ConsequenceImpactClass"}).head($context.consideringgenes_g)[["geneSymbol", "clinvarSignDesc", "CADD_PHRED", "gnomadAF", "zyg", "isTransHeterozygote", "Consequence", "ConsequenceImpactClass", "phenoDict"]].to_csv(index=False)}
    ```
    \""".strip()

    with open("./${context.run_id}.prompt.md", "w") as f:
        f.write(prompt)
    """

    stub:
    """
    cat <<EOF > ${context.run_id}.prompt.md
    # Stub Prompt

    This prompt was generated while running with `-stub-run`.
    Run ID: ${context.run_id}
    Considered Genes: ${context.consideringgenes_g}
    EOF
    """
}
