nextflow.enable.dsl = 2

include { validateParameters } from 'plugin/nf-schema'
include { installAIMARRVELDeps } from '../../modules/aim/installAIMARRVELDeps.nf'
include { cloneAIMARRVEL } from '../../modules/aim/cloneAIMARRVEL.nf'
include { runAIMARRVEL } from '../../modules/aim/runAIMARRVEL.nf'
include { storeGeneOmim } from '../../modules/local/storeGeneOmim.nf'
include { generateHpodf } from '../../modules/local/generateHpodf.nf'
include { generatePrompt } from '../../modules/local/generatePrompt.nf'
include { improveGeneCsv } from '../../modules/local/improveGeneCsv.nf'
include { invokeLlms; reasonLlm; extractLlm } from '../../modules/local/invokeLlms.nf'
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

// RUN_STRATEGY picks how the two LLM steps of a vote are run (see
// modules/local/invokeLlms.nf): 'unified' (default) or 'stratified'.  It is read
// like the invoke scripts read their settings -- the environment first, then
// the .env at the repository root.
def runStrategy() {
    def value = System.getenv('RUN_STRATEGY')
    def dotenv = file("${projectDir}/../../.env")
    if (value == null && dotenv.exists()) {
        def line = dotenv.readLines().find { it ==~ /^\s*(export\s+)?RUN_STRATEGY\s*=.*/ }
        if (line) {
            value = line.split('=', 2)[1].replaceAll(/\s+#.*$/, '').trim().replaceAll(/^["']|["']$/, '')
        }
    }
    def strategy = value ?: 'unified'
    if (!(strategy in ['unified', 'stratified'])) {
        error "RUN_STRATEGY must be 'unified' or 'stratified', got '${strategy}'"
    }
    return strategy
}

workflow {
    validateParameters()

    if (params.publishDirSuffix && !params.publishDirSuffix.startsWith('/')) {
        error "publishDirSuffix must start with '/' (example: --publishDirSuffix /run100)"
    }

    // Everything except run_id is shared by every sample; run_id is attached
    // per sample below so that each one carries its own output namespace.
    n_votes = params.invocationnumber_n as Integer
    // 0 means "a simple majority of N".  A sample whose surviving ballots fall
    // below this is reported and left un-reranked rather than reranked on the
    // strength of one or two votes.
    min_votes = (params.min_votes as Integer) ?: (n_votes.intdiv(2) + 1)
    if (min_votes > n_votes) {
        error "min_votes (${min_votes}) cannot exceed invocationnumber_n (${n_votes})"
    }

    base_context = [
        "invocationnumber_n": params.invocationnumber_n as Integer,
        "consideringgenes_g": params.consideringgenes_g as Integer,
        "ref_ver": params.ref_ver,
        "aim_store_dir": params.aim_store_dir,
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
    // Shared by every sample, so .first() turns it into a value channel that
    // each improveGeneCsv task can consume rather than just the first one.
    gene_omim = storeGeneOmim(base_context).first()
    improvedgenecsv = improveGeneCsv(
        samples.map { context, gene_csv, hpotxt -> tuple(context, gene_csv) },
        gene_omim
    )

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

    run_strategy = runStrategy()
    log.info "LLM run strategy: ${run_strategy}"
    if (run_strategy == 'unified') {
        votes = invokeLlms(prompt_runs)
            .map { context, reasoning, output, prioritized_csv, extracted_csv -> tuple(context.run_id, prioritized_csv) }
    }
    else {
        reasoned = reasonLlm(prompt_runs)
            .map { context, iteration, reasoning, output -> tuple(context.run_id, context, iteration, output) }
        if (params.reason_before_extract) {
            // Barrier: toList() emits once, after the last reasoning task (retries
            // included) has finished, so extraction never shares the server with
            // reasoning and llama-swap swaps models once rather than per task.  An
            // empty list, when every reasoning call failed, emits nothing.
            reasoned = reasoned.toList().flatMap { it }
        }

        // The prompt is joined back on by run_id rather than carried through
        // reasonLlm: extraction needs its gene table as the candidate list.
        extraction_runs = reasoned
            .combine(prompts.map { context, prompt_file -> tuple(context.run_id, prompt_file) }, by: 0)
            .map { run_id, context, iteration, output, prompt_file -> tuple(context, iteration, output, prompt_file) }

        votes = extractLlm(extraction_runs)
            .map { context, prioritized_csv, extracted_csv -> tuple(context.run_id, prioritized_csv) }
    }

    // Group the per-iteration votes back into one bundle per sample. Aggregate
    // reads whichever prioritized CSVs were staged, so the reasoning/output
    // markdown is left published rather than restaged.
    //
    // The LLM processes use errorStrategy 'ignore', so a sample can
    // arrive with fewer than N votes: remainder:true lets those short groups
    // through (without it groupTuple drops them silently and the sample vanishes
    // from the results), and the filter decides whether what survived is still
    // worth ranking.
    prioritized = votes
        .groupTuple(size: n_votes, remainder: true, sort: true)
        .filter { run_id, prioritized_csvs ->
            def got = prioritized_csvs.size()
            if (got == n_votes) {
                return true
            }
            if (got >= min_votes) {
                log.warn "Sample ${run_id}: reranking on ${got}/${n_votes} votes -- ${n_votes - got} invocation(s) failed"
                return true
            }
            // log.warn, not log.error: the run carries on, and log.error is
            // rendered like a fatal error on the console.
            log.warn "SKIPPED sample ${run_id}: only ${got}/${n_votes} votes survived, need ${min_votes} -- not reranked"
            return false
        }

    aggregate(
        improvedgenecsv.map { context, gene_csv -> tuple(context.run_id, context, gene_csv) }
            .join(prioritized)
            .map { run_id, context, gene_csv, prioritized_csvs -> tuple(context, gene_csv, prioritized_csvs) }
    )
}
