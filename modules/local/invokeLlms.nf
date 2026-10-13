// The two LLM steps of one vote, run one of two ways (RUN_STRATEGY, see
// main.nf):
//
//   unified     invokeLlms does reasoning and extraction in one task, so a
//               retry resamples the reasoning too and the extraction gets a
//               different answer to work from.
//   stratified  reasonLlm and extractLlm are separate processes so that
//               main.nf can finish every reasoning call before the first
//               extraction starts (--reason_before_extract): when both models
//               are served by one llama-swap host, interleaving them makes it
//               swap models on nearly every task.  A retry of extractLlm
//               re-extracts the same reasoning output.
//
// All three share one retry contract.  A transient failure (137-150, see
// bin/llm_provider.py) is retried; anything else costs just this one vote.
// 'terminate' used to abort the whole run -- one sample's four failed
// invocations killed 419 pending tasks -- so the blast radius is now a single
// ballot: aggregate() ranks whatever votes arrived and main.nf skips a sample
// that falls below --min_votes.

process invokeLlms {
    maxForks 4
    tag "$context.run_id/$iteration"
    publishDir "published${params.publishDirSuffix ?: ''}/$context.run_id/llmoutputs", mode: 'copy'
    // Once maxRetries is spent a 'retry' verdict aborts the whole run, so the
    // last attempt falls through to 'ignore' like any other lost vote.
    errorStrategy { task.exitStatus in 137..150 && task.attempt <= 5 ? 'retry' : 'ignore' }
    maxRetries 5

    input:
    tuple(
        val(context),
        val(iteration),
        path(prompt_file),
    )

    output:
    tuple(
        val(context),
        path("*.reasoning.*.md"),
        path("*.output.*.md"),
        path("*.prioritized.*.csv"),
        path("*.extracted.*.csv"),
    )

    script:
    def published = "${workflow.launchDir}/published${params.publishDirSuffix ?: ''}/${context.run_id}/llmoutputs"
    def reasoning_md = "${context.run_id}.reasoning.${iteration}.md"
    def output_md = "${context.run_id}.output.${iteration}.md"
    def prioritized_csv = "${context.run_id}.prioritized.${iteration}.csv"
    def extracted_csv = "${context.run_id}.extracted.${iteration}.csv"
    """
    if [[ "${params.reuse_published_votes}" == "true" && -e "${published}/${reasoning_md}" && -s "${published}/${output_md}" ]]; then
        echo "reusing published vote from ${published}"
        cp "${published}/${reasoning_md}" "${published}/${output_md}" .
    else
        $moduleDir/../../bin/invoke_reasoning_llm.py \
            --input "$prompt_file" \
            --reasoning_output "${reasoning_md}" \
            --output "${output_md}" \
            --run_id "${context.run_id}" \
            --iteration "${iteration}"
    fi

    if [[ "${params.reuse_published_votes}" == "true" && -s "${published}/${prioritized_csv}" && -e "${published}/${extracted_csv}" ]]; then
        echo "reusing published extraction from ${published}"
        cp "${published}/${prioritized_csv}" "${published}/${extracted_csv}" .
    else
        $moduleDir/../../bin/invoke_prioritize_llm.py \
            --input "${output_md}" \
            --output "${prioritized_csv}" \
            --raw_output "${extracted_csv}" \
            --prompt "$prompt_file" \
            --run_id "${context.run_id}" \
            --iteration "${iteration}"
    fi
    """
}

process reasonLlm {
    maxForks 4
    tag "$context.run_id/$iteration"
    publishDir "published${params.publishDirSuffix ?: ''}/$context.run_id/llmoutputs", mode: 'copy'
    // storeDir "stored/llmoutputs"
    // Once maxRetries is spent a 'retry' verdict aborts the whole run, so the
    // last attempt falls through to 'ignore' like any other lost vote.
    errorStrategy { task.exitStatus in 137..150 && task.attempt <= 5 ? 'retry' : 'ignore' }
    maxRetries 5

    input:
    tuple(
        val(context),
        val(iteration),
        path(prompt_file),
    )

    output:
    tuple(
        val(context),
        val(iteration),
        path("*.reasoning.*.md"),
        path("*.output.*.md"),
    )

    script:
    def published = "${workflow.launchDir}/published${params.publishDirSuffix ?: ''}/${context.run_id}/llmoutputs"
    def reasoning_md = "${context.run_id}.reasoning.${iteration}.md"
    def output_md = "${context.run_id}.output.${iteration}.md"
    """
    if [[ "${params.reuse_published_votes}" == "true" && -e "${published}/${reasoning_md}" && -s "${published}/${output_md}" ]]; then
        echo "reusing published vote from ${published}"
        cp "${published}/${reasoning_md}" "${published}/${output_md}" .
    else
        $moduleDir/../../bin/invoke_reasoning_llm.py \
            --input "$prompt_file" \
            --reasoning_output "${reasoning_md}" \
            --output "${output_md}" \
            --run_id "${context.run_id}" \
            --iteration "${iteration}"
    fi
    # invoke_nonreasoning_llm.py \
    #     --input "$prompt_file" \
    #     --output "${context.run_id}.output.${iteration}.md"
    """
}

process extractLlm {
    maxForks 4
    tag "$context.run_id/$iteration"
    publishDir "published${params.publishDirSuffix ?: ''}/$context.run_id/llmoutputs", mode: 'copy'
    // A retry here re-extracts the same reasoning output; it no longer
    // resamples the reasoning step the way a retry of the combined task did.
    // Once maxRetries is spent a 'retry' verdict aborts the whole run, so the
    // last attempt falls through to 'ignore' like any other lost vote.
    errorStrategy { task.exitStatus in 137..150 && task.attempt <= 5 ? 'retry' : 'ignore' }
    maxRetries 5

    input:
    tuple(
        val(context),
        val(iteration),
        path(output_md),
        // Only read for its gene table, which bounds what an answer may name.
        path(prompt_file),
    )

    output:
    tuple(
        val(context),
        path("*.prioritized.*.csv"),
        path("*.extracted.*.csv"),
    )

    script:
    def published = "${workflow.launchDir}/published${params.publishDirSuffix ?: ''}/${context.run_id}/llmoutputs"
    def prioritized_csv = "${context.run_id}.prioritized.${iteration}.csv"
    def extracted_csv = "${context.run_id}.extracted.${iteration}.csv"
    """
    if [[ "${params.reuse_published_votes}" == "true" && -s "${published}/${prioritized_csv}" && -e "${published}/${extracted_csv}" ]]; then
        echo "reusing published extraction from ${published}"
        cp "${published}/${prioritized_csv}" "${published}/${extracted_csv}" .
    else
        $moduleDir/../../bin/invoke_prioritize_llm.py \
            --input "$output_md" \
            --output "${prioritized_csv}" \
            --raw_output "${extracted_csv}" \
            --prompt "$prompt_file" \
            --run_id "${context.run_id}" \
            --iteration "${iteration}"
    fi
    """
}
