process aggregate {
    cpus 1
    tag "$context.run_id"
    publishDir "published/$context.run_id/reranked_gene", mode: 'copy'

    input:
    path genecsv, name: "gene.csv"
    path llmoutputs
    val context

    output:
    path "./${context.run_id}.improved.reranked.gene.csv"

    script:
    """
    #!/usr/bin/env python
    import pandas as pd
    import numpy as np

    from itertools import permutations

    def tideman_ranked_pairs(ballots):
        '''
        ballots: iterable of pd.Series (index=candidates, value=rank with 1=best). Missing = unranked.
        returns: list of candidates, best -> worst
        '''
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
            df_i = pd.read_csv(f"${context.run_id}.prioritized.{i}.csv")
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

    reranked_genedf.to_csv("${context.run_id}.improved.reranked.gene.csv")

    """
}
