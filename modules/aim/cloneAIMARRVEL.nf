process cloneAIMARRVEL {
    storeDir params.aim_store_dir
    cpus 1

    input:
    val context

    output:
    path "./AI_MARRVEL", emit: "aimrepo"

    script:
    // Fetching the ref instead of `git clone --branch` lets aim_version be a
    // commit SHA as well as a tag or branch.
    """
    git init -q AI_MARRVEL
    cd AI_MARRVEL
    git remote add origin ${params.aim_repo}
    git fetch -q --depth 1 origin ${params.aim_version}
    git checkout -q FETCH_HEAD
    """ + (params.aim_native ? """
    # Native mode runs every AIM process in the checkout's pixi environments
    # (native/README.md in the AIM repo), so they are set up once, here.
    pixi install --all
    pixi run -e vep fetch-vep
    pixi run -e r install-ontologysimilarity
    """ : "")
}
