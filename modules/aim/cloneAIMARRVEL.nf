process cloneAIMARRVEL {
    storeDir params.aim_store_dir
    cpus 1

    input:
    val context

    output:
    path "./AI_MARRVEL", emit: "aimrepo"

    script:
    """
    git clone --branch v1.2.0-rc260512 --depth 1 https://github.com/LiuzLab/AI_MARRVEL
    """

    stub:
    """
    mkdir -p AI-MARRVEL
    """
}
