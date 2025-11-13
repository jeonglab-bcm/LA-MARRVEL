nextflow.enable.dsl = 2

include { validateParameters } from 'plugin/nf-schema'

validateParameters()

workflow {
    runid = params.runid
    invocationnumber_n = params.invocationnumber_n
    consideringgenes_g = params.consideringgenes_g

    context = [
        "runid": runid,
        "invocationnumber_n": invocationnumber_n,
        "consideringgenes_g": consideringgenes_g,
    ]

    genecsv = Channel.fromPath(params.genecsv)
    hpostxt = Channel.fromPath(params.hpostxt)

    hpodf = generateHpodf(hpostxt, context)
    improvedgenecsv = improveGeneCsv(genecsv, context)

    prompts = generatePrompt(hpodf, improvedgenecsv, context)

    prompt_runs = prompts
        .flatMap { file ->
            (0..<invocationnumber_n).collect { iteration -> tuple(iteration, file) }
        }

    llmoutputs = invokeLlms(prompt_runs, context).collect()

    improvedrerankedgenecsv = aggregate(improvedgenecsv, llmoutputs, context)
}

process generateHpodf {
    cpus 1

    // publishDir "published/$context.runid/hpodf", mode: 'copy'
    tag "$context.runid"

    input:
    path inputhpo, name: 'input.hpos.txt'
    val context

    output:
    path "./${context.runid}.hpodf.csv"

    script:
    """
    #!/usr/bin/env python

    import pandas as pd
    import json

    with open("$moduleDir/resources/hp.json") as file:
        data = json.load(file)

    wholehpodf = pd.DataFrame([{
        "id": node['id'].split('/')[-1],
        "name": node['lbl'],
        "synonyms": [syn.get('val') for syn in node.get('meta', {}).get('synonyms', [])],
        "definition": node.get('meta', {}).get('definition', {}).get('val', ''),
    } for node in data['graphs'][0]['nodes'] if node.get("type") == "CLASS"])
    wholehpodf["id"] = wholehpodf["id"].str.replace("HP_", "HP:")

    if __name__ == "__main__":
        hpodf = pd.read_csv(f"input.hpos.txt", header=None, names=["id"]).merge(wholehpodf, on="id", how="left")
        hpodf.to_csv("./${context.runid}.hpodf.csv", index=False)
    """

    stub:
    """
    #!/usr/bin/env python
    import csv
    from pathlib import Path

    ids = [line.strip() for line in Path("input.hpos.txt").read_text().splitlines() if line.strip()]
    if not ids:
        ids = ["HP:STUB"]

    with open("${context.runid}.hpodf.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "name", "synonyms", "definition"])
        writer.writeheader()
        for hp_id in ids:
            writer.writerow({
                "id": hp_id,
                "name": f"Stub term for {hp_id}",
                "synonyms": "[]",
                "definition": "Stub definition produced with -with-stub"
            })
    """
}

process generatePrompt {
    cpus 1

    publishDir "published/$context.runid/prompt", mode: 'copy'
    tag "$context.runid"

    input:
    path hpodf, name: 'hpodf.csv'
    path genecsv, name: 'genedf.csv'
    val context

    output:
    path "./${context.runid}.prompt.md"

    script:
    """
    #!/usr/bin/env python

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

    with open("./${context.runid}.prompt.md", "w") as f:
        f.write(prompt)
    """

    stub:
    """
    cat <<EOF > ${context.runid}.prompt.md
    # Stub Prompt

    This prompt was generated while running with `-with-stub`.
    Run ID: ${context.runid}
    Considered Genes: ${context.consideringgenes_g}
    EOF
    """
}

process improveGeneCsv {
    cpus 1
    tag "$context.runid"

    input:
    path genecsv, name: "gene.csv"
    val context

    output:
    path "./${context.runid}.improved.gene.csv"

    script:
    """
    #!/usr/bin/env python
    import pandas as pd
    import json
    import ast

    with open("$moduleDir/resources/gene_omim.json") as f:
        gene_omim = json.loads(f.read())
    hgncdf = pd.read_csv("$moduleDir/resources/hgnc_complete_set.txt", sep="\t", low_memory=False)
    d2pdf = pd.read_csv("$moduleDir/resources/disease_to_phenotypes.csv")
    d2pdf = d2pdf.groupby("disease_id").apply(lambda x: x.hpo_termname.to_list(), include_groups=False).rename("termnames")

    genesymbol2phenotypes = pd.DataFrame([entry for entry in gene_omim]).set_index("geneSymbol").phenotypes
    genesymbol2phenotypes = genesymbol2phenotypes[~genesymbol2phenotypes.index.duplicated(keep='last')]
    g2p = genesymbol2phenotypes.explode().to_frame()
    g2p = g2p[~g2p.phenotypes.isna()]
    g2p = g2p.reset_index().join(pd.json_normalize(g2p.phenotypes)).drop(columns = ["phenotypes", "mimNumber"])
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

        genedf.to_csv("${context.runid}.improved.gene.csv")
    """

    stub:
    """
    #!/usr/bin/env python
    import csv

    with open("gene.csv", newline="") as fh:
        reader = csv.DictReader(fh)
        input_fieldnames = reader.fieldnames or []
        rows = list(reader)

    out_fields = list(dict.fromkeys(input_fieldnames + ["phenoDict", "isTransHeterozygote"]))

    for row in rows:
        row.setdefault("phenoDict", "{}")
        row.setdefault("isTransHeterozygote", "No")

    with open("${context.runid}.improved.gene.csv", "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(rows)
    """
}

process invokeLlms {
    maxForks 2
    tag "$context.runid/$iteration"
    publishDir "published/$context.runid/llmoutputs", mode: 'copy'
    // storeDir "stored/llmoutputs"
    errorStrategy { task.exitStatus in 137..150 ? 'retry' : 'terminate' }
    maxRetries 5

    input:
    tuple(
        val(iteration),
        path(prompt_file),
    )
    val context

    output:
    tuple(
        path("*.reasoning.*.md"),
        path("*.output.*.md"),
        path("*.prioritized.*.csv"),
    )

    script:
    """
    $moduleDir/../../bin/invoke_reasoning_llm.py \
        --input "$prompt_file" \
        --reasoning_output "${context.runid}.reasoning.${iteration}.md" \
        --output "${context.runid}.output.${iteration}.md"
    # invoke_nonreasoning_llm.py \
    #     --input "$prompt_file" \
    #     --output "${context.runid}.output.${iteration}.md"

    $moduleDir/../../bin/invoke_prioritize_llm.py \
        --input "${context.runid}.output.${iteration}.md" \
        --output "${context.runid}.prioritized.${iteration}.csv"
    """

    stub:
    """
    cat <<EOF > ${context.runid}.reasoning.${iteration}.md
    Stub reasoning output for iteration ${iteration}
    EOF

    cat <<EOF > ${context.runid}.output.${iteration}.md
    Stub final output for iteration ${iteration}
    EOF

    cat <<EOF > ${context.runid}.prioritized.${iteration}.csv
    name
    STUB_GENE_${iteration}
    EOF
    """
}

process aggregate {
    cpus 1
    tag "$context.runid"
    publishDir "published/$context.runid/reranked_gene", mode: 'copy'

    input:
    path genecsv, name: "gene.csv"
    path llmoutputs
    val context

    output:
    path "./${context.runid}.improved.reranked.gene.csv"

    script:
    """
    #!/usr/bin/env python
    import pandas as pd
    import numpy as np

    from itertools import permutations

    def tideman_ranked_pairs(ballots):
        \"""
        ballots: iterable of pd.Series (index=candidates, value=rank with 1=best). Missing = unranked.
        returns: list of candidates, best -> worst
        \"""
        ballots = [s.astype(float) for s in ballots]
        if not ballots: return []
        C = sorted(set().union(*[set(s.index) for s in ballots]))
        m = len(C)

        # Borda (for deterministic tie-breaks)
        borda = {c: 0.0 for c in C}
        for s in ballots:
            r = s.reindex(C)
            for c in C:
                if pd.notna(r[c]):
                    borda[c] += (m - r[c] + 1)

        # Pairwise wins
        wins = {a: {b: 0 for b in C} for a in C}
        for s in ballots:
            r = s.reindex(C)
            for a, b in permutations(C, 2):
                ra, rb = r[a], r[b]
                if pd.notna(ra) and pd.isna(rb): wins[a][b] += 1
                elif pd.isna(ra) and pd.notna(rb): pass
                elif pd.notna(ra) and pd.notna(rb):
                    if ra < rb: wins[a][b] += 1

        # Strength-of-victory pairs
        pairs = []
        for a, b in permutations(C, 2):
            if a < b:  # dedupe unordered pairs
                wa, wb = wins[a][b], wins[b][a]
                if wa > wb: pairs.append((a, b, wa - wb, wa, wb))
                elif wb > wa: pairs.append((b, a, wb - wa, wb, wa))
        pairs.sort(key=lambda x: (-x[2], -x[3], x[0], x[1]))

        # Lock without cycles
        adj = {c: set() for c in C}
        def creates_cycle(u, v):
            stack, seen = [v], set()
            while stack:
                x = stack.pop()
                if x == u: return True
                for y in adj[x]:
                    if y not in seen:
                        seen.add(y); stack.append(y)
            return False

        for u, v, *_ in pairs:
            if not creates_cycle(u, v):
                adj[u].add(v)

        # Topological order (tie-break by Borda then name)
        indeg = {c: 0 for c in C}
        for u in C:
            for v in adj[u]:
                indeg[v] += 1

        order, avail = [], sorted([c for c in C if indeg[c] == 0], key=lambda c: (-borda[c], c))
        while avail:
            u = avail.pop(0)
            order.append(u)
            for v in sorted(adj[u]):
                indeg[v] -= 1
                if indeg[v] == 0:
                    avail.append(v)
            avail.sort(key=lambda c: (-borda[c], c))

        return order

    def get_reranked_genedf():
        N = $context.invocationnumber_n
        G = $context.consideringgenes_g

        genedf = (
            pd.read_csv(f"gene.csv", index_col=0)
            .reset_index(drop=True)
            .reset_index(names="originalIndex")
            .set_index("geneSymbol")
        )

        # Candidates = full gene universe (index of genedf)
        candidates = genedf.index.tolist()[:G]

        # Build COMPLETE ballots for Tideman: prioritized list + remaining genes in original order
        ballots = []
        for i in range(N):
            df_i = pd.read_csv(f"${context.runid}.prioritized.{i}.csv")
            order = df_i["name"].drop_duplicates(keep='first').tolist()
            full_order = order + [c for c in candidates if c not in order]

            # Convert to a ranking Series (0 = best) for compatibility with tideman_ranked_pairs
            ballots.append(pd.Series(
                data=range(len(full_order)),
                index=full_order,
                name=f"ranking_{i}"
            ))

        # Tideman over COMPLETE ballots
        prioritized_genedf = pd.DataFrame({
            "name": tideman_ranked_pairs(ballots)
        })

        # Reorder labeled genes by the consensus, then tack on any stragglers (if any)
        in_consensus = prioritized_genedf.name[prioritized_genedf.name.isin(genedf.index)]
        reranked_genedf = (
            pd.concat([
                genedf.loc[in_consensus],
                genedf[~genedf.index.isin(in_consensus)]
            ])
            .reset_index()
            .reset_index(names="reorderedIndex")
            .set_index("geneSymbol")
        )

        return reranked_genedf

    reranked_genedf = get_reranked_genedf()

    reranked_genedf.to_csv("${context.runid}.improved.reranked.gene.csv")

    """

    stub:
    """
    cp gene.csv ${context.runid}.improved.reranked.gene.csv
    """
}
