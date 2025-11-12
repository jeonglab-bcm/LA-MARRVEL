from pathlib import Path
import runpy
import sys
import types


class _DummyExceptions:
    EventStreamError = type("EventStreamError", (Exception,), {})
    ThrottlingException = type("ThrottlingException", (Exception,), {})
    ServiceUnavailableException = type("ServiceUnavailableException", (Exception,), {})
    ReadTimeoutError = type("ReadTimeoutError", (Exception,), {})


_botocore_module = types.ModuleType("botocore")
_botocore_exceptions = types.ModuleType("botocore.exceptions")
_botocore_exceptions.EventStreamError = _DummyExceptions.EventStreamError
_botocore_module.exceptions = _botocore_exceptions
sys.modules.setdefault("botocore", _botocore_module)
sys.modules.setdefault("botocore.exceptions", _botocore_exceptions)

_urllib3_module = types.ModuleType("urllib3")
_urllib3_exceptions = types.ModuleType("urllib3.exceptions")
_urllib3_exceptions.ReadTimeoutError = _DummyExceptions.ReadTimeoutError
_urllib3_module.exceptions = _urllib3_exceptions
sys.modules.setdefault("urllib3", _urllib3_module)
sys.modules.setdefault("urllib3.exceptions", _urllib3_exceptions)

_dotenv_module = types.ModuleType("dotenv")
_dotenv_module.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", _dotenv_module)


class _DummyClient:
    exceptions = types.SimpleNamespace(
        ThrottlingException=_DummyExceptions.ThrottlingException,
        ServiceUnavailableException=_DummyExceptions.ServiceUnavailableException,
    )


class _ReasoningMessage:
    def __init__(self, reasoning_text: str, main_text: str):
        self.content = [
            {"reasoning_content": {"text": reasoning_text}},
            {"text": main_text},
        ]

    def __iadd__(self, _chunk):
        return self


def test_invoke_reasoning_llm_writes_outputs(tmp_path, monkeypatch):
    created_instances = []

    class _ReasoningLLM:
        client = _DummyClient()

        def __init__(self):
            self.stream_calls = []

        def stream(self, prompt: str):
            self.stream_calls.append(prompt)
            message = _ReasoningMessage("mock reasoning", "mock main")

            def _generator():
                yield message
                yield object()

            return _generator()

    def _chatbedrock_factory(*_args, **_kwargs):
        instance = _ReasoningLLM()
        created_instances.append(instance)
        return instance

    langchain_stub = types.ModuleType("langchain_aws")
    langchain_stub.ChatBedrockConverse = _chatbedrock_factory
    sys.modules["langchain_aws"] = langchain_stub

    input_path = tmp_path / "prompt.txt"
    reasoning_path = tmp_path / "reasoning.txt"
    output_path = tmp_path / "output.txt"
    input_path.write_text("prompt content", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "invoke_reasoning_llm",
            "--input",
            str(input_path),
            "--reasoning_output",
            str(reasoning_path),
            "--output",
            str(output_path),
        ],
    )

    script_path = Path(__file__).resolve().parents[1] / "bin" / "invoke_reasoning_llm.py"
    runpy.run_path(str(script_path), run_name="__main__")

    assert reasoning_path.read_text(encoding="utf-8") == "mock reasoning"
    assert output_path.read_text(encoding="utf-8") == "mock main"
    assert created_instances[0].stream_calls == ["prompt content"]


def test_invoke_prioritize_llm_writes_ranked_csv(tmp_path, monkeypatch):
    created_instances = []

    class _PrioritizeLLM:
        client = _DummyClient()

        def __init__(self):
            self.invocations = []
            self._model = None

        def with_structured_output(self, model):
            self._model = model
            return self

        def with_retry(self, **_kwargs):
            return self

        def invoke(self, content: str):
            self.invocations.append(content)
            return self._model(
                results=[
                    {"excerpt": ["a"], "name": "GENE1", "rank": 1},
                    {"excerpt": ["b"], "name": "GENE2", "rank": 2},
                ]
            )

    def _chatbedrock_factory(*_args, **_kwargs):
        instance = _PrioritizeLLM()
        created_instances.append(instance)
        return instance

    langchain_stub = types.ModuleType("langchain_aws")
    langchain_stub.ChatBedrockConverse = _chatbedrock_factory
    sys.modules["langchain_aws"] = langchain_stub

    input_path = tmp_path / "input.txt"
    output_path = tmp_path / "output.csv"
    input_path.write_text("structured prompt", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "invoke_prioritize_llm",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
        ],
    )

    script_path = Path(__file__).resolve().parents[1] / "bin" / "invoke_prioritize_llm.py"
    runpy.run_path(str(script_path), run_name="__main__")

    assert output_path.read_text(encoding="utf-8") == ",name\n0,GENE1\n1,GENE2\n"
    assert created_instances[0].invocations == ["structured prompt"]
