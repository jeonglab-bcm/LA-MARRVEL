nextflow.enable.dsl = 2

include { validateParameters } from 'plugin/nf-schema'
include { installAIMARRVELDeps } from '../../modules/aim/installAIMARRVELDeps.nf'
include { cloneAIMARRVEL } from '../../modules/aim/cloneAIMARRVEL.nf'
include { runAIMARRVEL } from '../../modules/aim/runAIMARRVEL.nf'
include { generateHpodf } from '../../modules/local/generateHpodf.nf'
include { generatePrompt } from '../../modules/local/generatePrompt.nf'
include { improveGeneCsv } from '../../modules/local/improveGeneCsv.nf'
include { invokeLlms } from '../../modules/local/invokeLlms.nf'
include { aggregate } from '../../modules/local/aggregate.nf'

// Resolve one manifest cell into a file, relative paths being taken relative to
// the directory holding the manifest (see docs/manifest_format.md).
def resolveManifestPath(manifest_dir, value, column, run_id) {
    if (!value?.trim()) {
        error "Manifest row '${run_id}': column '${column}' is empty"
    }
    def raw = value.trim()
    def resolved = raw.startsWith('/') ? file(raw) : file("${manifest_dir}/${raw}")
    if (!resolved.exists()) {
        error "Manifest row '${run_id}': ${column} does not exist: ${resolved}"
    }
    return resolved
}

// Parse the manifest eagerly so that a malformed one fails before any task is
// submitted, and emit one [context, genecsv, hpotxt] tuple per sample.
def samplesFromManifest(base_context) {
    def manifest = file(params.samples_manifest, checkIfExists: true)
    def rows = manifest.splitCsv(header: true, strip: true)

    if (!rows) {
        error "Manifest ${manifest} contains no sample rows"
    }

    def required = ['run_id', 'genecsv', 'hpotxt']
    def missing = required.findAll { !(it in rows[0].keySet()) }
    if (missing) {
        error "Manifest ${manifest} is missing required column(s): ${missing.join(', ')}"
    }

    def duplicates = rows.countBy { it.run_id }.findAll { id, n -> n > 1 }.keySet()
    if (duplicates) {
        error "Manifest ${manifest} has duplicate run_id value(s): ${duplicates.join(', ')}"
    }

    log.info "Loaded ${rows.size()} sample(s) from ${manifest}"

    return Channel.fromList(
        rows.collect { row ->
            tuple(
                base_context + ["run_id": row.run_id],
                resolveManifestPath(manifest.parent, row.genecsv, 'genecsv', row.run_id),
                resolveManifestPath(manifest.parent, row.hpotxt, 'hpotxt', row.run_id),
            )
        }
    )
}

workflow {
    validateParameters()

    if (params.publishDirSuffix && !params.publishDirSuffix.startsWith('/')) {
        error "publishDirSuffix must start with '/' (example: --publishDirSuffix /run100)"
    }

    // Everything except run_id is shared by every sample; run_id is attached
    // per sample below so that each one carries its own output namespace.
    base_context = [
        "invocationnumber_n": params.invocationnumber_n as Integer,
        "consideringgenes_g": params.consideringgenes_g as Integer,
        "ref_ver": params.ref_ver,
    ]

    if (params.samples_manifest) {
        samples = samplesFromManifest(base_context)
    }
    else if (params.genecsv) {
        samples = Channel.of(
            tuple(
                base_context + ["run_id": params.run_id],
                file(params.genecsv, checkIfExists: true),
                file(params.hpostxt, checkIfExists: true),
            )
        )
    }
    else {
        log.info "No --genecsv provided, generating from --input_vcf via AIMARRVEL..."
        log.info "AIMARRVEL outputs will be stored in ${params.aim_store_dir}"

        aim_context = base_context + ["run_id": params.run_id]
        aim_hpostxt = file(params.hpostxt, checkIfExists: true)

        installAIMARRVELDeps(aim_context)
        cloneAIMARRVEL(aim_context)
        genecsv = runAIMARRVEL(
            cloneAIMARRVEL.out.aimrepo,
            installAIMARRVELDeps.out.aimdata,
            params.input_vcf,
            params.hpostxt,
            aim_context
        )

        samples = genecsv.map { gene_csv -> tuple(aim_context, gene_csv, aim_hpostxt) }
    }

    hpodf = generateHpodf(samples.map { context, gene_csv, hpotxt -> tuple(context, hpotxt) })
    improvedgenecsv = improveGeneCsv(samples.map { context, gene_csv, hpotxt -> tuple(context, gene_csv) })

    // run_id is the join key throughout: the two branches above fan out
    // independently, so they have to be re-paired per sample rather than by
    // arrival order.
    prompts = generatePrompt(
        hpodf.map { context, hpo_df -> tuple(context.run_id, context, hpo_df) }
            .join(improvedgenecsv.map { context, gene_csv -> tuple(context.run_id, gene_csv) })
            .map { run_id, context, hpo_df, gene_csv -> tuple(context, hpo_df, gene_csv) }
    )

    prompt_runs = prompts
        .flatMap { context, prompt_file ->
            (0..<context.invocationnumber_n).collect { i -> tuple(context, i, prompt_file) }
        }

    // Group the per-iteration votes back into one bundle per sample. Aggregate
    // only reads the prioritized CSVs, which it looks up by file name, so the
    // reasoning/output markdown is left published rather than restaged.
    prioritized = invokeLlms(prompt_runs)
        .map { context, reasoning, output, prioritized_csv -> tuple(context.run_id, prioritized_csv) }
        .groupTuple(size: base_context.invocationnumber_n, sort: true)

    aggregate(
        improvedgenecsv.map { context, gene_csv -> tuple(context.run_id, context, gene_csv) }
            .join(prioritized)
            .map { run_id, context, gene_csv, prioritized_csvs -> tuple(context, gene_csv, prioritized_csvs) }
    )
}
