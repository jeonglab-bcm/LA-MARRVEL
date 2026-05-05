from pathlib import Path
import runpy
import sys
import types
import openai


_dotenv_module = types.ModuleType("dotenv")
_dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", _dotenv_module)


class _FakeMessage:
    def __init__(self, reasoning=None, content=None, parsed=None):
        self.reasoning = reasoning
        self.content = content
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResponse:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


def _make_openai_mock(monkeypatch, *, completions_create=None, beta_parse=None):
    class _Completions:
        def create(self, **kwargs):
            return completions_create(**kwargs)

    class _Chat:
        completions = _Completions()

    class _BetaCompletions:
        def parse(self, **kwargs):
            return beta_parse(**kwargs)

    class _BetaChat:
        completions = _BetaCompletions()

    class _Beta:
        chat = _BetaChat()

    class _Client:
        chat = _Chat()
        beta = _Beta()

    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: _Client())


def test_invoke_reasoning_llm_writes_outputs(tmp_path, monkeypatch):
    def _create(**kwargs):
        return _FakeResponse(_FakeMessage(reasoning="mock reasoning", content="mock main"))

    _make_openai_mock(monkeypatch, completions_create=_create)

    input_path = tmp_path / "prompt.txt"
    reasoning_path = tmp_path / "reasoning.txt"
    output_path = tmp_path / "output.txt"
    input_path.write_text("prompt content", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "invoke_reasoning_llm",
        "--input", str(input_path),
        "--reasoning_output", str(reasoning_path),
        "--output", str(output_path),
        "--model", "test-model",
    ])

    script_path = Path(__file__).resolve().parents[1] / "bin" / "invoke_reasoning_llm.py"
    runpy.run_path(str(script_path), run_name="__main__")

    assert reasoning_path.read_text(encoding="utf-8") == "mock reasoning"
    assert output_path.read_text(encoding="utf-8") == "mock main"


def test_invoke_prioritize_llm_writes_ranked_csv(tmp_path, monkeypatch):
    class _MockParsed:
        def model_dump(self):
            return {
                "results": [
                    {"excerpt": ["a"], "name": "GENE1", "rank": 1},
                    {"excerpt": ["b"], "name": "GENE2", "rank": 2},
                ]
            }

    def _parse(**kwargs):
        return _FakeResponse(_FakeMessage(parsed=_MockParsed()))

    _make_openai_mock(monkeypatch, beta_parse=_parse)

    input_path = tmp_path / "input.txt"
    output_path = tmp_path / "output.csv"
    input_path.write_text("structured prompt", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", [
        "invoke_prioritize_llm",
        "--input", str(input_path),
        "--output", str(output_path),
        "--model", "test-model",
    ])

    script_path = Path(__file__).resolve().parents[1] / "bin" / "invoke_prioritize_llm.py"
    runpy.run_path(str(script_path), run_name="__main__")

    assert output_path.read_text(encoding="utf-8") == ",name\n0,GENE1\n1,GENE2\n"
