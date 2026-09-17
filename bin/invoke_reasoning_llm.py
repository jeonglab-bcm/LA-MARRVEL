#!/usr/bin/env -S sh -c 'p=${0%/*}/../.venv/bin/python; [ -x "$p" ] || p=python; exec "$p" "$0" "$@"'
import sys
import argparse
import dotenv
import llm_provider

dotenv.load_dotenv()

thinking_llm = llm_provider.reasoning_llm()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        required=True,
    )
    parser.add_argument(
        "--reasoning_output",
        required=True,
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    args = parser.parse_args()

    with open(args.input) as f:
        prompt = f.read().strip()

    try:
        stream = thinking_llm.stream(prompt)
        full = next(stream)
        for chunk in stream:
            full += chunk
            print(chunk)
    except Exception as e:
        exit_code = llm_provider.retry_exit_code(e, thinking_llm)
        if exit_code is None:
            raise
        print(e)
        sys.exit(exit_code)
    aimsg = full

    reasoning_content, main_content = llm_provider.split_reasoning(aimsg)

    with open(args.reasoning_output, "w") as f:
        f.write(reasoning_content)

    with open(args.output, "w") as f:
        f.write(main_content)
