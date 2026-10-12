"""Shared fixtures, and isolation from whatever `.env` the developer has.

`bin/invoke_*.py` call `dotenv.load_dotenv()` at import, so without this a test
run would pick up real provider credentials and real Langfuse settings -- which
at best makes results depend on the machine and at worst ships test spans to a
live Langfuse project.
"""

import pytest


@pytest.fixture(scope="module")
def monkeypatch_module():
    """`monkeypatch`, but scoped to a module so it can guard an import."""
    patcher = pytest.MonkeyPatch()
    yield patcher
    patcher.undo()


@pytest.fixture(autouse=True)
def no_ambient_langfuse_settings(monkeypatch):
    """Keep LANGFUSE_* out of every test; each test opts in to what it needs."""
    import os

    for name in [n for n in os.environ if n.startswith("LANGFUSE")]:
        monkeypatch.delenv(name, raising=False)
