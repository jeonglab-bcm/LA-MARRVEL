#!/usr/bin/env -S uv run --quiet --script
import sys
import os
import argparse
import openai
import dotenv

dotenv.load_dotenv()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--reasoning_output", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.environ.get("DEFAULT_LOCAL_MODEL"))
    parser.add_argument("--model_url", default=os.environ.get("OLLAMA_URL", "http://localhost:11435/v1"))
    args = parser.parse_args()
    if not args.model:
        parser.error("--model is required or DEFAULT_LOCAL_MODEL must be set")

    client = openai.OpenAI(
        base_url=args.model_url,
        api_key="none",
    )
    with open(args.input) as f:
        prompt = f.read().strip()

    try:
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": prompt}],
            # max_tokens=65536,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": True}
            }

        )
        message = response.choices[0].message
        reasoning_content = getattr(message, "reasoning", None) or ""
        main_content = message.content or ""
    except openai.RateLimitError as e:
        print(e)
        sys.exit(138)
    except openai.APITimeoutError as e:
        print(e)
        sys.exit(139)
    except openai.APIStatusError as e:
        print(e)
        sys.exit(140)

    with open(args.reasoning_output, "w") as f:
        f.write(reasoning_content)

    with open(args.output, "w") as f:
        f.write(main_content)
