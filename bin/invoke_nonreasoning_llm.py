#!/usr/bin/env python
import sys
import argparse
import langchain_aws
import botocore.exceptions
import urllib3.exceptions

llm = langchain_aws.ChatBedrockConverse(
    provider = "anthropic",
    model_id="arn:aws:bedrock:us-east-1:314146307595:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
    max_tokens=65536,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
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
        stream = llm.stream(prompt)
        full = next(stream)
        for chunk in stream:
            full += chunk
            print(chunk)
    except botocore.exceptions.EventStreamError as e:
        print(e)
        sys.exit(137)
    except llm.client.exceptions.ThrottlingException as e:
        print(e)
        sys.exit(138)
    except urllib3.exceptions.ReadTimeoutError as e:
        print(e)
        sys.exit(139)
    aimsg = full

    main_content = aimsg.content[0]['text']

    with open(args.output, "w") as f:
        f.write(main_content)