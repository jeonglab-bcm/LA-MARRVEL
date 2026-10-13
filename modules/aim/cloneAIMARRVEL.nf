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
    """
}
