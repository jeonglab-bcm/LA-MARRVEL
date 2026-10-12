"""Chat model factories for the rerank LLM steps.

The provider is selected per role, so the long-form reasoning step and the
structured extraction step can run on different backends (e.g. reasoning on a
local OpenAI-compatible server, extraction on Bedrock).  ``REASONING_PROVIDER``
and ``EXTRACTION_PROVIDER`` pick the backend for their role and both fall back
to ``PROVIDER`` when unset:

``bedrock`` (default)
    AWS Bedrock through ``langchain_aws.ChatBedrockConverse``, using the
    standard AWS credential variables.

``openai``
    Any OpenAI-compatible ``/v1`` endpoint through
    ``langchain_openai.ChatOpenAI``.  This is what a ``llama.cpp``
    ``llama-server`` serving a Hugging Face model exposes, so point
    ``OPENAI_BASE_URL`` at that server (llama.cpp ignores the API key, but the
    client still requires a non-empty value).

Every setting can likewise be scoped to a role by inserting ``REASONING`` or
``EXTRACTION`` after the provider prefix -- ``OPENAI_REASONING_BASE_URL``,
``BEDROCK_EXTRACTION_MODEL_ID`` -- falling back to the unscoped name
(``OPENAI_BASE_URL``, ``BEDROCK_MODEL_ID``).  The older ``PRIORITIZE`` spelling
is still accepted as an alias for ``EXTRACTION``.

Both providers are exposed through the same three helpers so the invoke
scripts stay provider agnostic: :func:`reasoning_llm` /
:func:`prioritize_llm` build the models, :func:`describe` reports the backend
and model a built one came from, :func:`retry_exceptions` lists the
transient failures worth retrying in-process, :func:`retry_exit_code` maps a
transient failure onto the 137-150 exit codes that make Nextflow retry the
task, and :func:`split_reasoning` pulls the chain-of-thought and the answer
apart regardless of how the provider reports them.  The helpers that need to
know which backend an already-built model came from derive it from the model
object itself, so a mixed-provider run stays consistent.
"""

import json
import os
import re
import sys

BEDROCK = "bedrock"
OPENAI = "openai"

REASONING = "reasoning"
EXTRACTION = "extraction"

# Env-name infixes tried for each role, most specific first, before falling
# back to the unscoped name.  PRIORITIZE is the pre-split spelling of
# EXTRACTION and is kept so existing .env files keep working.
_ROLE_INFIXES = {
    REASONING: ("REASONING",),
    EXTRACTION: ("EXTRACTION", "PRIORITIZE"),
}

DEFAULT_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"
DEFAULT_BEDROCK_MAX_TOKENS = 65536
DEFAULT_BEDROCK_THINKING_BUDGET = 50000

DEFAULT_OPENAI_BASE_URL = "http://localhost:8080/v1"
DEFAULT_OPENAI_MODEL = "local-model"
DEFAULT_OPENAI_MAX_TOKENS = 65536
DEFAULT_OPENAI_TIMEOUT = 3600.0

# Exit codes in 137..150 are retried by reasonLlm/extractLlm in modules/local/invokeLlms.nf.
EXIT_STREAM_ERROR = 137
EXIT_THROTTLED = 138
EXIT_TIMEOUT = 139
EXIT_UNAVAILABLE = 140
EXIT_CONNECTION = 141
EXIT_TRUNCATED = 142
EXIT_CONTEXT = 143

_THINK_TAGS = re.compile(
    r"<(?P<tag>think|thinking|reasoning)>(?P<body>.*?)</(?P=tag)>",
    re.DOTALL | re.IGNORECASE,
)


def _normalize_provider(name, source):
    name = name.strip().lower()
    if name in (BEDROCK, "aws", "aws-bedrock"):
        return BEDROCK
    if name in (OPENAI, "openai-compatible", "llamacpp", "llama-cpp", "llama_cpp"):
        return OPENAI
    raise ValueError(
        f"Unsupported {source}={name!r}; expected {BEDROCK!r} or {OPENAI!r}"
    )


def provider(role=None):
    """Return the backend selected for ``role``.

    ``REASONING_PROVIDER`` / ``EXTRACTION_PROVIDER`` win for their role; both
    fall back to ``PROVIDER`` and finally to ``bedrock``.
    """
    return _provider_and_source(role)[0]


def _provider_and_source(role=None):
    """``(backend, env name that chose it)``; the name is ``None`` for the default."""
    names = tuple(f"{infix}_PROVIDER" for infix in _ROLE_INFIXES.get(role, ()))
    names += ("PROVIDER",)
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return _normalize_provider(value, name), name
    return BEDROCK, None


def _provider_of(llm):
    """Recover the backend a built chat model came from.

    Derived from the class rather than the environment so the two roles stay
    independent, and without importing a provider package that may not be
    installed.
    """
    names = {cls.__name__ for cls in type(llm).__mro__}
    if names & {"ChatBedrockConverse", "ChatBedrock"}:
        return BEDROCK
    if "ChatOpenAI" in names:
        return OPENAI
    raise ValueError(f"Cannot determine provider for {type(llm).__name__}")


def _names(prefix, suffix, role):
    """Env names for ``suffix``: role-scoped first, then the unscoped name."""
    scoped = tuple(
        f"{prefix}_{infix}_{suffix}" for infix in _ROLE_INFIXES.get(role, ())
    )
    return scoped + (f"{prefix}_{suffix}",)


def _env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_int(*names, default=None):
    value = _env(*names)
    return default if value is None else int(value)


def _env_float(*names, default=None):
    value = _env(*names)
    return default if value is None else float(value)


def _env_json(*names, default=None):
    value = _env(*names)
    if value is None:
        return {} if default is None else default
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{names[0]} must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _chat_openai_class():
    """``ChatOpenAI`` that keeps the non-standard ``reasoning_content`` deltas.

    ``ChatOpenAI`` targets the official OpenAI schema and drops unknown fields,
    but llama-server started with ``--reasoning-format deepseek`` reports the
    chain of thought in exactly such a field.  Re-attach it to the message so
    the reasoning survives into ``split_reasoning``.
    """
    try:
        import langchain_openai
    except ImportError as exc:  # pragma: no cover - dependency hint only
        raise ImportError(
            "PROVIDER=openai requires the langchain-openai package "
            "(pip install -r requirements.txt)"
        ) from exc

    class ChatOpenAIWithReasoning(langchain_openai.ChatOpenAI):
        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info
        ):
            generation_chunk = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info
            )
            if generation_chunk is None:
                return None
            choices = chunk.get("choices") or chunk.get("chunk", {}).get("choices") or []
            delta = (choices[0].get("delta") or {}) if choices else {}
            for key in ("reasoning_content", "reasoning"):
                value = delta.get(key)
                if isinstance(value, str) and value:
                    generation_chunk.message.additional_kwargs["reasoning_content"] = value
                    break
            return generation_chunk

    return ChatOpenAIWithReasoning


def _chat_openai(role, model, temperature=None, max_tokens=None, extra_body=None):
    # Each role gets its own endpoint/key/timeout so the two roles can point at
    # different OpenAI-compatible servers; unscoped names remain the fallback.
    kwargs = {
        "model": model,
        "base_url": _env(
            *_names("OPENAI", "BASE_URL", role),
            *_names("OPENAI", "API_BASE", role),
            default=DEFAULT_OPENAI_BASE_URL,
        ),
        # llama.cpp does not check the key but the client refuses to start without one.
        "api_key": _env(*_names("OPENAI", "API_KEY", role), default="sk-no-key-required"),
        "timeout": _env_float(
            *_names("OPENAI", "TIMEOUT", role), default=DEFAULT_OPENAI_TIMEOUT
        ),
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    body = dict(extra_body or {})
    body.update(_env_json(*_names("OPENAI", "EXTRA_BODY", role)))
    if body:
        kwargs["extra_body"] = body

    return _chat_openai_class()(**kwargs)


def reasoning_llm():
    """Long-form analysis model (thinking enabled where the provider supports it)."""
    if provider(REASONING) == BEDROCK:
        import langchain_aws

        budget = _env_int(
            *_names("BEDROCK", "THINKING_BUDGET_TOKENS", REASONING),
            default=DEFAULT_BEDROCK_THINKING_BUDGET,
        )
        return langchain_aws.ChatBedrockConverse(
            provider="anthropic",
            model_id=_env(
                *_names("BEDROCK", "MODEL_ID", REASONING), default=DEFAULT_BEDROCK_MODEL_ID
            ),
            max_tokens=_env_int(
                *_names("BEDROCK", "MAX_TOKENS", REASONING),
                default=DEFAULT_BEDROCK_MAX_TOKENS,
            ),
            additional_model_request_fields={
                "thinking": {"type": "enabled", "budget_tokens": budget}
            },
        )

    # llama.cpp emits reasoning either as <think> blocks inside the answer or,
    # when started with --reasoning-format deepseek, as a reasoning_content
    # field; split_reasoning() handles both.
    extra_body = {}
    thinking = _env(*_names("OPENAI", "ENABLE_THINKING", REASONING))
    if thinking is not None:
        extra_body["chat_template_kwargs"] = {
            "enable_thinking": thinking.lower() not in ("0", "false", "no")
        }
    return _chat_openai(
        REASONING,
        model=_env(*_names("OPENAI", "MODEL", REASONING), default=DEFAULT_OPENAI_MODEL),
        temperature=_env_float(*_names("OPENAI", "TEMPERATURE", REASONING)),
        max_tokens=_env_int(
            *_names("OPENAI", "MAX_TOKENS", REASONING), default=DEFAULT_OPENAI_MAX_TOKENS
        ),
        extra_body=extra_body,
    )


def prioritize_llm():
    """Extraction model used with structured output; thinking is not needed here."""
    if provider(EXTRACTION) == BEDROCK:
        import langchain_aws

        return langchain_aws.ChatBedrockConverse(
            provider="anthropic",
            model_id=_env(
                *_names("BEDROCK", "MODEL_ID", EXTRACTION),
                default=DEFAULT_BEDROCK_MODEL_ID,
            ),
        )

    extra_body = {}
    # Thinking and sampling stay role-local: extraction wants a deterministic,
    # non-thinking pass even when the reasoning role sets the unscoped names.
    thinking = _env(
        "OPENAI_EXTRACTION_ENABLE_THINKING",
        "OPENAI_PRIORITIZE_ENABLE_THINKING",
        default="false",
    )
    extra_body["chat_template_kwargs"] = {
        "enable_thinking": thinking.lower() not in ("0", "false", "no")
    }
    return _chat_openai(
        EXTRACTION,
        model=_env(*_names("OPENAI", "MODEL", EXTRACTION), default=DEFAULT_OPENAI_MODEL),
        temperature=_env_float(
            "OPENAI_EXTRACTION_TEMPERATURE",
            "OPENAI_PRIORITIZE_TEMPERATURE",
            default=0.0,
        ),
        max_tokens=_env_int(
            *_names("OPENAI", "MAX_TOKENS", EXTRACTION), default=DEFAULT_OPENAI_MAX_TOKENS
        ),
        extra_body=extra_body,
    )


def describe(llm):
    """``(backend, model)`` for a built chat model, for logs and trace metadata."""
    model = (
        getattr(llm, "model_id", None)
        or getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
    )
    return _provider_of(llm), model


def settings(llm, role):
    """Everything that shapes a request from ``llm``, for the task log.

    Read back from the built model rather than the environment, so the record
    shows what is actually sent -- including defaults, and values a stray or
    misspelled variable failed to change.  Credentials are never included.
    """
    backend, model = describe(llm)
    chosen_by = _provider_and_source(role)[1]
    record = {
        "role": role,
        "backend": backend,
        "provider_from": chosen_by or "default (no *PROVIDER variable set)",
        "model": model,
    }
    if backend == BEDROCK:
        record.update(
            region=getattr(llm, "region_name", None) or os.environ.get("AWS_DEFAULT_REGION"),
            temperature=llm.temperature,
            top_p=llm.top_p,
            max_tokens=llm.max_tokens,
            additional_model_request_fields=llm.additional_model_request_fields,
        )
    else:
        record.update(
            base_url=llm.openai_api_base,
            temperature=llm.temperature,
            top_p=llm.top_p,
            max_tokens=llm.max_tokens,
            timeout=llm.request_timeout,
            extra_body=llm.extra_body,
            model_kwargs=llm.model_kwargs or None,
        )
        if role == EXTRACTION:
            record["structured_output_method"] = _structured_output_method()
    # The pre-multi-provider spelling; setting it silently falls back to bedrock.
    if os.environ.get("LLM_PROVIDER", "").strip():
        record["warning"] = "LLM_PROVIDER is set but ignored; use PROVIDER / *_PROVIDER"
    return record


def log_settings(llm, role, file=None):
    """Write :func:`settings` to stderr as one greppable ``[llm-settings]`` JSON line."""
    line = json.dumps(settings(llm, role), sort_keys=False, default=str)
    print(f"[llm-settings] {line}", file=file or sys.stderr, flush=True)


def _structured_output_method():
    return _env(
        *_names("OPENAI", "STRUCTURED_OUTPUT_METHOD", EXTRACTION), default="json_schema"
    )


def structured_output(llm, schema):
    """Bind ``schema`` to ``llm`` using the method each provider handles best."""
    if _provider_of(llm) == BEDROCK:
        return llm.with_structured_output(schema)
    # llama.cpp turns a json_schema response_format into a sampling grammar,
    # which is far more reliable than tool calling on arbitrary HF models.
    return llm.with_structured_output(schema, method=_structured_output_method())


def retry_exceptions(llm):
    """Transient exception types worth retrying inside a single invocation."""
    if _provider_of(llm) == BEDROCK:
        return (llm.client.exceptions.ThrottlingException,)

    import openai

    return (
        openai.RateLimitError,
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.InternalServerError,
        # Raised when the server stopped at max_tokens and the structured
        # response is therefore unparseable.  Worth retrying because the run
        # away decode is not reproducible: the server batches concurrent
        # requests, so the same input can take a different token path.
        openai.LengthFinishReasonError,
    )


def retry_exit_code(exc, llm=None):
    """Map a transient failure to a Nextflow-retryable exit code, else ``None``.

    Pass the model that raised so the right mapping is used; without it both
    are tried, skipping the one whose SDK is not installed.
    """
    if llm is not None:
        if _provider_of(llm) == BEDROCK:
            return _bedrock_exit_code(exc)
        return _openai_exit_code(exc)

    for mapper in (_bedrock_exit_code, _openai_exit_code):
        try:
            code = mapper(exc)
        except ImportError:
            continue
        if code is not None:
            return code
    return None


def _bedrock_exit_code(exc):
    import botocore.exceptions
    import urllib3.exceptions

    if isinstance(exc, botocore.exceptions.EventStreamError):
        return EXIT_STREAM_ERROR
    if isinstance(exc, (urllib3.exceptions.ReadTimeoutError, botocore.exceptions.ReadTimeoutError)):
        return EXIT_TIMEOUT
    if isinstance(exc, botocore.exceptions.ConnectionError):
        return EXIT_CONNECTION
    # ThrottlingException & friends are modelled per-client by botocore, so match
    # them on the error code in the response (falling back to the class name).
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    code = code or type(exc).__name__
    if code in ("ThrottlingException", "TooManyRequestsException"):
        return EXIT_THROTTLED
    if code in (
        "ServiceUnavailableException",
        "ModelNotReadyException",
        "InternalServerException",
    ):
        return EXIT_UNAVAILABLE
    return None


def _is_openai_context_overflow(exc):
    """True for a slot running out of KV cache part-way through a stream.

    llama-server reports this as an SSE error event, which the client surfaces
    as a bare ``APIError`` carrying the server's message -- there is no status
    code and no dedicated class, so it has to be matched on the text.  It is
    worth retrying because the cache is shared between the server's slots: the
    same prompt succeeds when fewer invocations are in flight.  An
    ``APIStatusError`` (the 400 ``exceed_context_size_error`` raised before
    generation starts) means the prompt alone does not fit and is deliberately
    excluded -- retrying cannot make it smaller.
    """
    import openai

    if not isinstance(exc, openai.APIError) or isinstance(exc, openai.APIStatusError):
        return False
    return "context size has been exceeded" in str(exc).lower()


def _openai_exit_code(exc):
    import openai

    # Not an APIStatusError, so it has to be matched before the status checks.
    if isinstance(exc, openai.LengthFinishReasonError):
        return EXIT_TRUNCATED
    if isinstance(exc, openai.RateLimitError):
        return EXIT_THROTTLED
    if isinstance(exc, openai.APITimeoutError):
        return EXIT_TIMEOUT
    if isinstance(exc, openai.APIConnectionError):
        return EXIT_CONNECTION
    if isinstance(exc, openai.InternalServerError):
        return EXIT_UNAVAILABLE
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return EXIT_UNAVAILABLE
    # Matched on the message, so it goes last: every typed check above wins.
    if _is_openai_context_overflow(exc):
        return EXIT_CONTEXT
    return None


def _strip_think_tags(text):
    """Pull ``<think>`` blocks out of ``text``; returns (reasoning, answer)."""
    reasoning = [m.group("body").strip() for m in _THINK_TAGS.finditer(text)]
    answer = _THINK_TAGS.sub("", text)
    # An unterminated opening tag means the stream ended mid-thought.
    head, sep, tail = answer.partition("<think>")
    if sep:
        reasoning.append(tail.strip())
        answer = head
    return "\n\n".join(p for p in reasoning if p), answer.strip()


def split_reasoning(message):
    """Return ``(reasoning_text, main_text)`` for an assistant message.

    Handles Bedrock Converse ``reasoning_content`` blocks, the
    ``reasoning_content`` field llama.cpp adds with ``--reasoning-format
    deepseek``, and plain ``<think>`` tags left inline in the answer.
    """
    reasoning_parts = []
    text_parts = []

    content = message.content
    if isinstance(content, str):
        text_parts.append(content)
    else:
        for block in content:
            if not isinstance(block, dict):
                text_parts.append(str(block))
            elif "reasoning_content" in block:  # Bedrock Converse
                inner = block["reasoning_content"]
                reasoning_parts.append(
                    inner.get("text", "") if isinstance(inner, dict) else str(inner)
                )
            elif block.get("type") in ("reasoning", "thinking"):
                reasoning_parts.append(
                    block.get("reasoning") or block.get("thinking") or block.get("text", "")
                )
            elif block.get("type") == "text" or "text" in block:
                text_parts.append(block.get("text", ""))

    for key in ("reasoning_content", "reasoning"):
        value = getattr(message, "additional_kwargs", {}).get(key)
        if isinstance(value, str) and value.strip():
            reasoning_parts.append(value)

    main_text = "".join(text_parts).strip()
    inline_reasoning, main_text = _strip_think_tags(main_text)
    if inline_reasoning:
        reasoning_parts.append(inline_reasoning)

    return "\n\n".join(p for p in reasoning_parts if p.strip()).strip(), main_text
