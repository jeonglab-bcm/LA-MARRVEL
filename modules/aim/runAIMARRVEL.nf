process runAIMARRVEL {
    input:
    path aim_repo   // AI-MARRVEL/ repo dir from installAIMARRVEL.out.aimrepo
    path aimdata    // reference data dir from installAIMARRVEL.out.aimdata
    val  input_vcf
    val  hpostxt
    val  context

    output:
    path "aim_output/aim_connect/prediction/final_matrix_expanded/aim_connect.gene.csv"

    script:
    """
    export NXF_SINGULARITY_CACHEDIR=$moduleDir/../work/singularity
    FULL_AIM_REPO=\$(readlink -f ${aim_repo})
    nextflow run \${FULL_AIM_REPO} \
        -profile singularity \
        --skip_ref_sync \
        --ref_dir   ${aimdata} \
        --ref_ver   ${context.ref_ver} \
        --input_vcf ${input_vcf} \
        --input_hpo ${hpostxt} \
        --outdir    ./aim_output \
        --storedir  ./store \
        --run_id    ${context.run_id} 

    """

    stub:
    """
    printf "gene,score\ngene1,1.0\ngene2,0.9\n" > genes.csv
    """
}
