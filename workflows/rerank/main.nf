nextflow.enable.dsl = 2

include { validateParameters } from 'plugin/nf-schema'
include { installAIMARRVELDeps } from '../../modules/aim/installAIMARRVELDeps.nf'
include { cloneAIMARRVEL } from '../../modules/aim/cloneAIMARRVEL.nf'
include { runAIMARRVEL } from '../../modules/aim/runAIMARRVEL.nf'
include { storeGeneOmim } from '../../modules/local/storeGeneOmim.nf'
include { generateHpodf } from '../../modules/local/generateHpodf.nf'
include { generatePrompt } from '../../modules/local/generatePrompt.nf'
include { improveGeneCsv } from '../../modules/local/improveGeneCsv.nf'
include { invokeLlms } from '../../modules/local/invokeLlms.nf'
include { aggregate } from '../../modules/local/aggregate.nf'

workflow {
    validateParameters()

    context = [
        "run_id": params.run_id,
        "invocationnumber_n": params.invocationnumber_n as Integer,
        "consideringgenes_g": params.consideringgenes_g as Integer,
        "ref_ver": params.ref_ver,
        "aim_store_dir": params.aim_store_dir,
    ]

    if (params.genecsv) {
        genecsv = Channel.fromPath(params.genecsv)
    } else {
        log.info "No --genecsv provided, generating from --input_vcf via AIMARRVEL..."
        installAIMARRVELDeps(context)
        cloneAIMARRVEL(context)
        genecsv = runAIMARRVEL(
            cloneAIMARRVEL.out.aimrepo,
            installAIMARRVELDeps.out.aimdata,
            Channel.fromPath(params.input_vcf),
            Channel.fromPath(params.hpostxt),
            Channel.fromPath(params.aim_store_dir),
            context
        )
    }

    hpostxt = Channel.fromPath(params.hpostxt)

    gene_omim = storeGeneOmim(context)
    hpodf = generateHpodf(hpostxt, context)
    improvedgenecsv = improveGeneCsv(genecsv, gene_omim, context)

    prompts = generatePrompt(hpodf, improvedgenecsv, context)

    prompt_runs = prompts
        .flatMap { file ->
            (0..<context.invocationnumber_n).collect { i -> tuple(i, file) }
        }

    llmoutputs = invokeLlms(prompt_runs, context).collect()

    aggregate(improvedgenecsv, llmoutputs, context)
}
