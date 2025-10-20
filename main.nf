params.io_dir = null // s3://jaeyeon-dev-aimllmrerank/250908

String sanitizeS3Path(String s3Path) {
    if (!s3Path) return "unknown"

    // Remove s3:// prefix
    String cleaned = s3Path.replaceFirst(/^s3:\/\//, "")

    // Replace any characters not allowed in filenames with "_"
    cleaned = cleaned.replaceAll(/[^a-zA-Z0-9._-]/, "_")

    // Collapse multiple underscores
    cleaned = cleaned.replaceAll(/_+/, "_")

    // Trim leading/trailing underscores or dots
    cleaned = cleaned.replaceAll(/^[_\.]+|[_\.]+$/, "")

    return cleaned
}


workflow {
    input_dir = params.io_dir + "/input"
    output_dir = params.io_dir + "/output"

    prompts = GET_PROMPTS(input_dir).flatten()
    prompts = prompts
        .map { f -> tuple(f.baseName.tokenize('\\.')[0], f) }

    result = INVOKE_REASONING_LLM(prompts)
    PUT_RESULT(result.collect(), output_dir)
}

process GET_PROMPTS {
    tag "$input_dir"
    storeDir "./stored/${sanitizeS3Path(input_dir)}"

    input:
    val input_dir

    output:
    path "**/*.prompt.md"

    """
    AWS_PROFILE=liuzlab aws s3 sync $input_dir ./input_dir
    ls -al
    """
}

process INVOKE_REASONING_LLM {
    maxForks 4
    tag "$id"
    storeDir "./stored/reasoning_llm/"
    errorStrategy { task.exitStatus in 137..140 ? 'retry' : 'terminate' }
    maxRetries 5

    input:
    tuple(
        val(id),
        path(prompt_file),
    )

    output:
    path "$id"

    """
    mkdir -p $id
    for i in {0..9}; do
        invoke_reasoning_llm.py \
            --input "$prompt_file" \
            --reasoning_output "$id/${id}.reasoning.\$i.md" \
            --output "$id/${id}.output.\$i.md"

        invoke_prioritize_llm.py \
            --input "$id/${id}.output.\$i.md" \
            --output "$id/${id}.prioritized.\$i.csv"
    done

    """
}

process PUT_RESULT {
    tag "$output_dir"

    input:
    path files
    val output_dir

    """
    mkdir output_dir
    mv $files output_dir
    ls -al
    AWS_PROFILE=liuzlab aws s3 sync output_dir $output_dir
    """
}