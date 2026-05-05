#!/usr/bin/env -S uv run --quiet --script
import openai
import argparse
import pydantic
import typing
import pandas as pd
import dotenv
import os
import time

dotenv.load_dotenv()


class GenerankItem(pydantic.BaseModel):
    excerpt: typing.List[str] = pydantic.Field(..., description = "A list of excerpts from the literature that support the gene's relevance to the disease.")
    name: str = pydantic.Field(..., description = "The name of the gene.")
    rank: int = pydantic.Field(..., description = "The rank of the gene, with 1 being the highest priority.")


class Generank(pydantic.BaseModel):
    results: typing.List[GenerankItem]


def invoke(content: str, model: str, retries: int = 3):
    for attempt in range(retries):
        try:
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[
                    {"role": "system", "content": "Extract prioritized gene ranks only."},
                    {"role": "user", "content": content}
                ],
                response_format=Generank,
            )
            result = response.choices[0].message.parsed
            if result is None:
                raise pydantic.ValidationError([{
                    'loc': ('response',),
                    'msg': 'Response did not match expected format - empty response',
                    'type': 'value_error',                }], model=Generank)
            return result
        except (openai.RateLimitError, pydantic.ValidationError) as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--gene_csv", required=False, help="Path to a CSV file containing gene names. If provided, only genes in this file will be ranked.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.environ.get("DEFAULT_LOCAL_MODEL"))
    parser.add_argument("--model_url", default=os.environ.get("OLLAMA_URL", "http://localhost:11435/v1"))
    args = parser.parse_args()
    client = openai.OpenAI(
        base_url=args.model_url,
        api_key="none",
    )
    if not args.model:
        parser.error("--model is required or DEFAULT_LOCAL_MODEL must be set")
    with open(args.input) as f:
        ai_content = f.read()
    if args.gene_csv:
        gene_df = pd.read_csv(args.gene_csv)
        gene_list = gene_df['geneSymbol'].tolist()
        class GenerankItem(pydantic.BaseModel):
            excerpt: typing.List[str] = pydantic.Field(..., description = "A list of excerpts from the literature that support the gene's relevance to the disease.")
            gene_name: typing.Literal[*gene_list] = pydantic.Field(..., description = "The gene's name.")
            rank: int = pydantic.Field(..., description = "The rank of the gene, with 1 being the highest priority.")
        class Generank(pydantic.BaseModel):
            results: typing.List[GenerankItem]

    generank = invoke(ai_content, args.model)
    main_content = pd.DataFrame(generank.model_dump()['results']).gene_name.to_csv()
    with open(args.output, "w") as f:
        f.write(main_content)
