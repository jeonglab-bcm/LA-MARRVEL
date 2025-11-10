#!/usr/bin/env python
import langchain_aws
import argparse
import pydantic
import typing
import pandas as pd

class GenerankItem(pydantic.BaseModel):
    excerpt: typing.List[str]
    name: str
    rank: int

class Generank(pydantic.BaseModel):
    """
    Extract prioritized gene ranks only.
    """
    results: typing.List[GenerankItem]

llm = langchain_aws.ChatBedrockConverse(
    provider = "anthropic",
    model_id="arn:aws:bedrock:us-east-1:314146307595:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
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
        ai_content = f.read()
    generank = llm.with_structured_output(Generank).with_retry(retry_if_exception_type=(pydantic.ValidationError,llm.client.exceptions.ThrottlingException,)).invoke(ai_content)
    main_content = pd.DataFrame(generank.model_dump()['results']).name.to_csv()
    with open(args.output, "w") as f:
        f.write(main_content)
