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

    stub:
    """
    mkdir -p aim_output/${context.run_id}/prediction/final_matrix_expanded
    cat <<'CSV' > aim_output/${context.run_id}/prediction/final_matrix_expanded/${context.run_id}.gene.csv
geneSymbol,varId,geneEnsId,zyg,predict,IMPACT_text,Consequence,clinvarSignDesc,CADD_PHRED,gnomadAF
GENE1,"['1-100-A-T']",ENSG00000000001,het,0.9,HIGH,missense_variant,Pathogenic,25.0,0.0001
GENE2,"['1-200-C-G']",ENSG00000000002,hom,0.8,MODERATE,missense_variant,Uncertain_significance,18.0,0.001
CSV
    """
}
