"""Tests for the ``[llm-settings]`` line the invoke scripts write to the task log.

Models are only built, never called, so nothing here reaches a server.
"""

import json
import os
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

import llm_provider  # noqa: E402


@pytest.fixture(autouse=True)
def clean_provider_env(monkeypatch):
    prefixes = ("OPENAI", "BEDROCK", "AWS")
    names = ("PROVIDER", "REASONING_PROVIDER", "EXTRACTION_PROVIDER",
             "PRIORITIZE_PROVIDER", "LLM_PROVIDER")
    for name in list(os.environ):
        if name.startswith(prefixes) or name in names:
            monkeypatch.delenv(name, raising=False)


def logged(llm, role, capsys):
    llm_provider.log_settings(llm, role)
    err = capsys.readouterr().err.strip()
    prefix = "[llm-settings] "
    assert err.startswith(prefix)
    return json.loads(err[len(prefix):])


def test_openai_reasoning_records_what_is_sent(monkeypatch, capsys):
    monkeypatch.setenv("REASONING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid:8000/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.setenv("OPENAI_MODEL", "qwen-test")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "0.8")
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "5000")
    monkeypatch.setenv("OPENAI_TIMEOUT", "120")
    monkeypatch.setenv("OPENAI_ENABLE_THINKING", "false")
    monkeypatch.setenv("OPENAI_EXTRA_BODY", '{"top_k": 20}')

    record = logged(llm_provider.reasoning_llm(), llm_provider.REASONING, capsys)

    assert record["backend"] == "openai"
    assert record["provider_from"] == "REASONING_PROVIDER"
    assert record["model"] == "qwen-test"
    assert record["base_url"] == "http://example.invalid:8000/v1"
    assert record["temperature"] == 0.8
    assert record["max_tokens"] == 5000
    assert record["timeout"] == 120.0
    assert record["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False},
        "top_k": 20,
    }
    assert "warning" not in record


def test_api_key_never_logged(monkeypatch, capsys):
    monkeypatch.setenv("PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    llm_provider.log_settings(llm_provider.prioritize_llm(), llm_provider.EXTRACTION)
    assert "sk-secret-value" not in capsys.readouterr().err


def test_openai_extraction_includes_structured_output_method(monkeypatch, capsys):
    monkeypatch.setenv("EXTRACTION_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_STRUCTURED_OUTPUT_METHOD", "json_mode")

    record = logged(llm_provider.prioritize_llm(), llm_provider.EXTRACTION, capsys)

    assert record["role"] == "extraction"
    assert record["temperature"] == 0.0
    assert record["structured_output_method"] == "json_mode"
    assert record["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_bedrock_default_and_stale_llm_provider_are_flagged(monkeypatch, capsys):
    # The 2026-09-24 failure mode: only the old spelling set, so bedrock is used.
    monkeypatch.setenv("LLM_PROVIDER", "local")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    record = logged(llm_provider.reasoning_llm(), llm_provider.REASONING, capsys)

    assert record["backend"] == "bedrock"
    assert record["provider_from"].startswith("default")
    assert record["model"] == llm_provider.DEFAULT_BEDROCK_MODEL_ID
    assert record["region"] == "us-east-1"
    assert record["max_tokens"] == llm_provider.DEFAULT_BEDROCK_MAX_TOKENS
    assert record["additional_model_request_fields"]["thinking"]["budget_tokens"] == (
        llm_provider.DEFAULT_BEDROCK_THINKING_BUDGET
    )
    assert "LLM_PROVIDER" in record["warning"]
