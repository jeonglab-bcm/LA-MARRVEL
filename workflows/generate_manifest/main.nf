nextflow.enable.dsl = 2

// Derive a sample's run_id from its path: by default the name of the directory
// holding the file (input/<run_id>/genedf.csv), or the first capture group of
// --run_id_regex applied to the file name when the layout is flat.
def runIdOf(f) {
    if (params.run_id_regex) {
        def matcher = (f.name =~ params.run_id_regex)
        if (!matcher.find()) {
            error "run_id_regex /${params.run_id_regex}/ did not match file name: ${f.name}"
        }
        return matcher.groupCount() >= 1 ? matcher.group(1) : matcher.group(0)
    }
    return f.parent.name
}

// Map run_id -> file, rejecting patterns that resolve two files to one run_id.
def indexByRunId(pattern, option) {
    def matches = file(pattern)
    if (matches instanceof Path) {
        matches = [matches]
    }
    if (!matches) {
        error "--${option} matched no files: ${pattern}"
    }

    def index = [:]
    matches.each { f ->
        def run_id = runIdOf(f)
        if (index.containsKey(run_id)) {
            error "--${option} matched two files with run_id '${run_id}':\n  ${index[run_id]}\n  ${f}"
        }
        index[run_id] = f
    }
    return index
}

// Nothing is written until every check has passed, so a failed run never leaves
// a half-populated manifest behind for the next command to pick up.
workflow {
    if (!params.genecsvGlob) error "Missing required parameter: --genecsvGlob"
    if (!params.hpotxtGlob)  error "Missing required parameter: --hpotxtGlob"

    genecsvs = indexByRunId(params.genecsvGlob, 'genecsvGlob')
    hpotxts = indexByRunId(params.hpotxtGlob, 'hpotxtGlob')

    run_ids = (genecsvs.keySet() + hpotxts.keySet()).sort()
    complete = run_ids.findAll { genecsvs[it] && hpotxts[it] }
    incomplete = run_ids - complete

    incomplete.each { run_id ->
        log.warn "Skipping '${run_id}': no ${genecsvs[run_id] ? 'hpotxt' : 'genecsv'} matched the given pattern"
    }
    if (incomplete) {
        log.warn "${incomplete.size()} of ${run_ids.size()} sample(s) skipped for missing files"
    }
    if (!complete) {
        error "No sample matched both --genecsvGlob and --hpotxtGlob"
    }

    outfile = file(params.outfile)
    outfile.parent.mkdirs()
    outfile.text = (
        ['run_id,genecsv,hpotxt'] + complete.collect { "${it},${genecsvs[it]},${hpotxts[it]}" }
    ).join('\n') + '\n'

    log.info "Wrote ${complete.size()} sample(s) to ${outfile}"
}
