process invokeLlms {
    // maxForks 2
    tag "$context.run_id/$iteration"
    publishDir "published${params.publishDirSuffix ?: ''}/$context.run_id/llmoutputs", mode: 'copy'
    // storeDir "stored/llmoutputs"
    errorStrategy { task.exitStatus in 137..150 ? 'retry' : 'terminate' }
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

    stub:
    """
    cat <<EOF > ${context.run_id}.reasoning.${iteration}.md
    Stub reasoning output for iteration ${iteration}
    EOF

    cat <<EOF > ${context.run_id}.output.${iteration}.md
    Stub final output for iteration ${iteration}
    EOF

    cat <<EOF > ${context.run_id}.prioritized.${iteration}.csv
    name
    STUB_GENE_${iteration}
    EOF
    """
}
