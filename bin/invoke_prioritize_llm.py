#!/usr/bin/env -S sh -c 'p=${0%/*}/../.venv/bin/python; [ -x "$p" ] || p=python; exec "$p" "$0" "$@"'
import argparse
import pydantic
import typing
import pandas as pd
import dotenv
import llm_provider

dotenv.load_dotenv()


class GenerankItem(pydantic.BaseModel):
    excerpt: typing.List[str]
    name: str
    rank: int


class Generank(pydantic.BaseModel):
    """
    Extract prioritized gene ranks only.
    """
    results: typing.List[GenerankItem]


llm = llm_provider.prioritize_llm()


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
    retry_on = (pydantic.ValidationError,) + llm_provider.retry_exceptions(llm)
    generank = llm_provider.structured_output(llm, Generank).with_retry(retry_if_exception_type=retry_on).invoke(ai_content)
    main_content = pd.DataFrame(generank.model_dump()['results']).name.to_csv()
    with open(args.output, "w") as f:
        f.write(main_content)
