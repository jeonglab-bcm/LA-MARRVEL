nextflow.enable.dsl = 2

include { validateParameters } from 'plugin/nf-schema'
include { generateHpodf } from '../../modules/local/generateHpodf.nf'
include { generatePrompt } from '../../modules/local/generatePrompt.nf'
include { improveGeneCsv } from '../../modules/local/improveGeneCsv.nf'
include { invokeLlms } from '../../modules/local/invokeLlms.nf'
include { aggregate } from '../../modules/local/aggregate.nf'

validateParameters()

workflow {
    run_id = params.run_id
    invocationnumber_n = params.invocationnumber_n
    consideringgenes_g = params.consideringgenes_g

    context = [
        "run_id": run_id,
        "invocationnumber_n": invocationnumber_n,
        "consideringgenes_g": consideringgenes_g,
    ]

    genecsv = Channel.fromPath(params.genecsv)
    hpostxt = Channel.fromPath(params.hpostxt)

    hpodf = generateHpodf(hpostxt, context)
    improvedgenecsv = improveGeneCsv(genecsv, context)

    prompts = generatePrompt(hpodf, improvedgenecsv, context)

    prompt_runs = prompts
        .flatMap { file ->
            (0..<invocationnumber_n).collect { iteration -> tuple(iteration, file) }
        }

    llmoutputs = invokeLlms(prompt_runs, context).collect()

    improvedrerankedgenecsv = aggregate(improvedgenecsv, llmoutputs, context)
}
