"""Tests for the optional Langfuse tracing helper.

Nothing here talks to a Langfuse server: the SDK keeps one set of resources per
public key, so a client built up front with an in-memory span exporter is the
one ``llm_tracing`` picks up, and the spans it would have shipped can be read
back directly.
"""

import sys
import pathlib

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

import llm_tracing  # noqa: E402

PUBLIC_KEY = "pk-lf-test"
SECRET_KEY = "sk-lf-test"


@pytest.fixture(scope="session")
def exporter():
    from langfuse import Langfuse

    exporter = InMemorySpanExporter()
    # Registers the resources every later Langfuse() call in the process reuses.
    Langfuse(public_key=PUBLIC_KEY, secret_key=SECRET_KEY, span_exporter=exporter)
    return exporter


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    """Clear the helper's memoised client and any inherited configuration."""
    monkeypatch.setattr(llm_tracing, "_handler", None)
    monkeypatch.setattr(llm_tracing, "_client", None)
    monkeypatch.setattr(llm_tracing, "_disabled", False)
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_TRACING_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch, exporter):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET_KEY)
    exporter.clear()
    return exporter


def test_disabled_without_credentials():
    assert not llm_tracing.is_enabled()
    with llm_tracing.trace("reasoning", run_id="SAMPLE", iteration="0") as config:
        assert config == {}


def test_disabled_by_flag(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC_KEY)
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET_KEY)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")

    assert not llm_tracing.is_enabled()
    with llm_tracing.trace("extraction") as config:
        assert config == {}


def test_empty_config_still_usable_by_langchain():
    llm = FakeListChatModel(responses=["ok"])
    with llm_tracing.trace("reasoning") as config:
        assert llm.invoke("hi", config=config).content == "ok"


def test_traced_call_reports_sample_role_and_backend(configured):
    llm = FakeListChatModel(responses=["ranked genes"])

    assert llm_tracing.is_enabled()
    with llm_tracing.trace(
        "reasoning",
        run_id="SAMPLE1",
        iteration="3",
        tags=("bedrock",),
        backend="bedrock",
        model="us.anthropic.claude-sonnet-4-20250514-v1:0",
    ) as config:
        assert config["run_name"] == "la_marrvel_rerank.reasoning"
        assert llm.invoke("prompt", config=config).content == "ranked genes"

    spans = configured.get_finished_spans()
    assert len(spans) == 1
    attributes = spans[0].attributes

    # The sample id groups a run's votes into one session.
    assert attributes["session.id"] == "SAMPLE1"
    assert attributes["langfuse.trace.name"] == "la_marrvel_rerank.reasoning"
    assert set(attributes["langfuse.trace.tags"]) == {
        "la_marrvel_rerank",
        "reasoning",
        "bedrock",
    }
    assert attributes["langfuse.trace.metadata.iteration"] == "3"
    assert attributes["langfuse.trace.metadata.backend"] == "bedrock"
    assert attributes["langfuse.observation.output"]


def test_missing_sdk_is_not_fatal(monkeypatch, configured, capsys):
    """A broken install must not take a pipeline task down with it."""
    # ``None`` in sys.modules makes the import raise, as an uninstalled package would.
    monkeypatch.setitem(sys.modules, "langfuse.langchain", None)

    with llm_tracing.trace("extraction", run_id="SAMPLE2") as config:
        assert config == {}

    assert not configured.get_finished_spans()
    assert "langfuse tracing: disabled" in capsys.readouterr().err
    # Given up on for the rest of the process rather than retried per call.
    assert not llm_tracing.is_enabled()
