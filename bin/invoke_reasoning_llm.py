#!/usr/bin/env -S sh -c 'p=${0%/*}/../.venv/bin/python; [ -x "$p" ] || p=python; exec "$p" "$0" "$@"'
import sys
import argparse
import dotenv
import llm_provider
import llm_tracing

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
    # Tracing only: both default to None so the script still runs by hand.
    parser.add_argument(
        "--run_id",
        help="sample id, used as the Langfuse session id",
    )
    parser.add_argument(
        "--iteration",
        help="which of the N votes this invocation is, recorded on the trace",
    )
    args = parser.parse_args()

    with open(args.input) as f:
        prompt = f.read().strip()

    backend, model = llm_provider.describe(thinking_llm)
    with llm_tracing.trace(
        llm_provider.REASONING,
        run_id=args.run_id,
        iteration=args.iteration,
        tags=(backend,),
        backend=backend,
        model=model,
    ) as config:
        try:
            stream = thinking_llm.stream(prompt, config=config)
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
