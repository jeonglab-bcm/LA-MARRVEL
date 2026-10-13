process runAIMARRVEL {
    input:
    path aim_repo   // AI-MARRVEL/ repo dir from cloneAIMARRVEL.out.aimrepo, or --aim_repo_dir
    path aimdata    // reference data dir from installAIMARRVELDeps.out.aimdata, or --aim_ref_dir
    path input_vcf
    path hpostxt
    val  context

    output:
    path "aim_output/${context.run_id}/prediction/final_matrix_expanded/${context.run_id}.gene.csv"

    script:
    def aim_store_dir = file(params.aim_store_dir).toAbsolutePath()
    def expanded = "aim_output/${context.run_id}/prediction/final_matrix_expanded"
    // Singularity (default) runs the AIM release containers; native runs them
    // in the checkout's pixi environments, for hosts without a container engine.
    def aim_profile = params.aim_native
        ? "-c \${FULL_AIM_REPO}/native/native.config run \${FULL_AIM_REPO}/main.nf -profile debug"
        : "run \${FULL_AIM_REPO} -profile singularity --skip_ref_sync"
    """
    export NXF_SINGULARITY_CACHEDIR=$moduleDir/../../work/singularity
    FULL_AIM_REPO=\$(readlink -f ${aim_repo})
    nextflow ${aim_profile} \
        --ref_dir   `readlink -f ${aimdata}` \
        --ref_ver   ${context.ref_ver} \
        --input_vcf `readlink -f ${input_vcf}` \
        --input_hpo `readlink -f ${hpostxt}` \
        --outdir    ./aim_output \
        --storedir  ${aim_store_dir} \
        --run_id    ${context.run_id}

    # AIM v1.2 writes the gene table itself; earlier releases (v1.1.x and the
    # hyunhwan-bcm fork) stop at the transcript-level matrix, so collapse it here.
    if [[ ! -s ${expanded}/${context.run_id}.gene.csv ]]; then
        $moduleDir/../../bin/aim_gene_table.py \
            --input ${expanded}/${context.run_id}.expanded.csv.gz \
            --output ${expanded}/${context.run_id}.gene.csv
    fi
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
