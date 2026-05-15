#!/usr/bin/env python
import sys
import argparse
import langchain_aws
import botocore.exceptions
import urllib3.exceptions
import dotenv

dotenv.load_dotenv()

thinking_params= {
    "thinking": {
        "type": "enabled",
        "budget_tokens": 50000,
    }
}

thinking_llm = langchain_aws.ChatBedrockConverse(
    provider="anthropic",
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    max_tokens=65536,
    additional_model_request_fields=thinking_params
)

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
    except botocore.exceptions.EventStreamError as e:
        print(e)
        sys.exit(137)
    except thinking_llm.client.exceptions.ThrottlingException as e:
        print(e)
        sys.exit(138)
    except urllib3.exceptions.ReadTimeoutError as e:
        print(e)
        sys.exit(139)
    except thinking_llm.client.exceptions.ServiceUnavailableException as e:
        print(e)
        sys.exit(140)
    aimsg = full

    reasoning_content = aimsg.content[0]['reasoning_content']['text']
    main_content = aimsg.content[1]['text']

    with open(args.reasoning_output, "w") as f:
        f.write(reasoning_content)

    with open(args.output, "w") as f:
        f.write(main_content)