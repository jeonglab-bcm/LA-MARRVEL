process invokeLlms {
    maxForks 4
    tag "$context.run_id/$iteration"
    publishDir "published${params.publishDirSuffix ?: ''}/$context.run_id/llmoutputs", mode: 'copy'
    // storeDir "stored/llmoutputs"
    // A transient failure (137-150, see bin/llm_provider.py) is retried; anything
    // else costs just this one vote.  'terminate' used to abort the whole run --
    // one sample's four failed invocations killed 419 pending tasks -- so the
    // blast radius is now a single ballot: aggregate() ranks whatever votes
    // arrived and main.nf skips a sample that falls below --min_votes.
    errorStrategy { task.exitStatus in 137..150 ? 'retry' : 'ignore' }
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
    )

    script:
    """
    $moduleDir/../../bin/invoke_reasoning_llm.py \
        --input "$prompt_file" \
        --reasoning_output "${context.run_id}.reasoning.${iteration}.md" \
        --output "${context.run_id}.output.${iteration}.md" \
        --run_id "${context.run_id}" \
        --iteration "${iteration}"
    # invoke_nonreasoning_llm.py \
    #     --input "$prompt_file" \
    #     --output "${context.run_id}.output.${iteration}.md"

    $moduleDir/../../bin/invoke_prioritize_llm.py \
        --input "${context.run_id}.output.${iteration}.md" \
        --output "${context.run_id}.prioritized.${iteration}.csv" \
        --prompt "$prompt_file" \
        --run_id "${context.run_id}" \
        --iteration "${iteration}"
    """
}
