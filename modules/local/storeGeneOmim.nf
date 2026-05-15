process storeGeneOmim {
    storeDir params.aim_store_dir
    cpus 1

    input:
    val context

    output:
    path "./gene_omim.json", emit: "gene_omim"

    script:
    """
    aws s3 cp s3://aim-data-dependencies-2.4-public/annotate/anno_hg19/gene_omim.json gene_omim.json --no-sign-request
    """
}
