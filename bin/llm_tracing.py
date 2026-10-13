"""Optional Langfuse tracing for the rerank LLM steps.

Every model call in :mod:`invoke_reasoning_llm` and :mod:`invoke_prioritize_llm`
runs inside :func:`trace`, which hands the call a LangChain ``config`` carrying
the Langfuse callback handler.  Tracing stays off unless
``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are set (``LANGFUSE_HOST``
picks a self-hosted instance, ``LANGFUSE_TRACING_ENABLED=false`` turns it off
again), so a run without those variables behaves exactly as before and
:func:`trace` yields an empty config.

Traces are grouped by sample: the Nextflow ``run_id`` becomes the Langfuse
session id, so one sample's ``invocationnumber_n`` votes and their extraction
passes sit together in one session, each tagged with its role and backend.

Because each Nextflow task is a short-lived process, :func:`trace` flushes on
the way out -- the background exporter would otherwise be killed before it
sends anything.  Tracing is best effort throughout: a missing package, bad
credentials or an unreachable Langfuse server is reported once on stderr and
never fails the task.
"""

import contextlib
import os
import sys

PIPELINE = "la_marrvel_rerank"

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")

# Built on first use and reused for the rest of the process; None means tracing
# is unavailable and we already said so.
_handler = None
_client = None
_disabled = False


def _env(name, default=None):
    value = os.environ.get(name)
    return value.strip() if value is not None and value.strip() else default


def _warn(message):
    print(f"langfuse tracing: {message}", file=sys.stderr)


def is_enabled():
    """True when credentials are configured and tracing is not switched off."""
    if _disabled:
        return False
    # Same variable the Langfuse client itself honours.
    if (_env("LANGFUSE_TRACING_ENABLED", "true") or "").lower() in _FALSE:
        return False
    return bool(_env("LANGFUSE_PUBLIC_KEY") and _env("LANGFUSE_SECRET_KEY"))


def _setup():
    """Return ``(client, handler)``, or None once tracing has been given up on."""
    global _handler, _client, _disabled

    if _disabled:
        return None
    if _handler is not None:
        return _client, _handler

    try:
        import langfuse
        import langfuse.langchain
    except ImportError as exc:
        _disabled = True
        _warn(f"disabled, {exc} (pip install -r requirements.txt)")
        return None

    try:
        # Env-driven, and a no-op past the first call: the SDK keeps one set of
        # resources per public key, so the two roles share an exporter.
        client = langfuse.Langfuse()
        handler = langfuse.langchain.CallbackHandler()
    except Exception as exc:  # pragma: no cover - depends on SDK internals
        _disabled = True
        _warn(f"disabled, {type(exc).__name__}: {exc}")
        return None

    _client, _handler = client, handler
    return _client, _handler


def _metadata(role, run_id, iteration, extra):
    # Values are coerced to strings and truncated by the SDK, so keep them short.
    metadata = {"pipeline": PIPELINE, "role": role}
    if run_id is not None:
        metadata["run_id"] = run_id
    if iteration is not None:
        metadata["iteration"] = iteration
    metadata.update({k: v for k, v in (extra or {}).items() if v is not None})
    return metadata


@contextlib.contextmanager
def trace(role, run_id=None, iteration=None, tags=(), **metadata):
    """Yield the LangChain ``config`` that traces one model call as ``role``.

    The config is empty when tracing is off, which every caller can still pass
    straight to ``invoke``/``stream``.  ``run_id`` groups a sample's calls into
    one Langfuse session and ``iteration`` records which of the N votes this is;
    any further keyword becomes trace metadata (the backend and model id, say).
    """
    if not is_enabled():
        yield {}
        return

    parts = _setup()
    if parts is None:
        yield {}
        return
    client, handler = parts

    import langfuse

    name = f"{PIPELINE}.{role}"
    resolved = _metadata(role, run_id, iteration, metadata)
    all_tags = [PIPELINE, role] + [t for t in tags if t]

    try:
        context = langfuse.propagate_attributes(
            session_id=run_id,
            trace_name=name,
            tags=all_tags,
            metadata={k: str(v) for k, v in resolved.items()},
        )
    except Exception as exc:  # pragma: no cover - depends on SDK internals
        _warn(f"call not traced, {type(exc).__name__}: {exc}")
        yield {}
        return

    try:
        with context:
            yield {
                "callbacks": [handler],
                "run_name": name,
                "metadata": resolved,
                "tags": all_tags,
            }
    finally:
        # The task process exits right after this, before the batch exporter's
        # own timer would fire.
        try:
            client.flush()
        except Exception as exc:  # pragma: no cover - network dependent
            _warn(f"flush failed, {type(exc).__name__}: {exc}")
