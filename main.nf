
params.inputpath = "./stored/251217/input/*/{genedf.csv,hpos.txt}"
params.max_parallel = 1

workflow {
    input_pairs_ch = Channel
        .fromFilePairs(params.inputpath, flat: true)
        .map { dir, genecsv, hpos -> 
            def runId = genecsv.parent.name
            [runId, genecsv, hpos]
        }
        .toSortedList{ a, b -> a[0] <=> b[0] }
        .flatten()
        .buffer(size: 3)

    // Run rerank workflow for each pair
    RUN_CASE(input_pairs_ch)
}

process RUN_CASE {
    maxForks params.max_parallel
    tag "$runId"

    publishDir "published/", mode: 'copy'

    input:
    tuple val(runId), path(genecsv), path(hpos)

    output:
    path "$runId"

    script:
    """
    nextflow run $projectDir/workflows/rerank/ \
        --genecsv "${genecsv}" \
        --hpostxt "${hpos}" \
        --run_id "${runId}"

    mv published/$runId $runId
    """

    stub:
    """
    echo "Processing ${runId} with files:"
    echo "genecsv: ${genecsv}"
    echo "hpos: ${hpos}"
    """
}

