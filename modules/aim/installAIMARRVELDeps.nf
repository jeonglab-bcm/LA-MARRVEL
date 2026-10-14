process installAIMARRVELDeps {
    storeDir params.aim_store_dir
    cpus 1

    input:
    val context

    output:
    path "./aimdata", emit: "aimdata"

    script:
    """
    aws s3 sync s3://${params.aim_ref_bucket} aimdata --no-sign-request
    """
}
