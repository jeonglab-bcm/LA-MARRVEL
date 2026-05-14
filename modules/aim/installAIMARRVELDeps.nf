process installAIMARRVELDeps {
    storeDir params.aim_store_dir
    cpus 1

    input:
    val context

    output:
    path "./aimdata", emit: "aimdata"

    script:
    """
    aws s3 sync s3://aim-data-dependencies-2.4-public aimdata --no-sign-request
    """

    stub:
    """
    mkdir -p aimdata
    """
}
