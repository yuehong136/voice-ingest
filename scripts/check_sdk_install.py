"""Run with a fresh interpreter containing only the installed base wheel."""

import importlib.util

import voice_ingest
from voice_ingest.synthesis.contracts import CreateSynthesis

assert voice_ingest.AsyncVoiceClient
assert CreateSynthesis(text="SDK isolation check").options.format == "mp3"
for package in ("fastapi", "sqlalchemy", "fastmcp", "websockets", "torch", "dashscope"):
    assert importlib.util.find_spec(package) is None, f"Unexpected SDK-only dependency: {package}"
print("SDK-only imports passed; no server or inference packages installed")
