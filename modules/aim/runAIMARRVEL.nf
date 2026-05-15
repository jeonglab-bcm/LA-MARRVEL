process runAIMARRVEL {
    input:
    path aim_repo   // AI-MARRVEL/ repo dir from installAIMARRVEL.out.aimrepo
    path aimdata    // reference data dir from installAIMARRVEL.out.aimdata
    path input_vcf
    path hpostxt
    path aim_store_dir
    val  context

    output:
    path "aim_output/${context.run_id}/prediction/final_matrix_expanded/${context.run_id}.gene.csv"

    script:
    """
    export NXF_SINGULARITY_CACHEDIR=$moduleDir/../../work/singularity
    FULL_AIM_REPO=\$(readlink -f ${aim_repo})
    nextflow run \${FULL_AIM_REPO} \
        -profile singularity \
        --skip_ref_sync \
        --ref_dir   ${aimdata} \
        --ref_ver   ${context.ref_ver} \
        --input_vcf `readlink -f ${input_vcf}` \
        --input_hpo `readlink -f ${hpostxt}` \
        --outdir    ./aim_output \
        --storedir  `readlink -f ${aim_store_dir}` \
        --run_id    ${context.run_id}

    """
}
