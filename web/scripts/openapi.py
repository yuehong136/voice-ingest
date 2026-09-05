"""Export contracts without connecting to storage or requiring credentials."""

import json
from pathlib import Path
from types import SimpleNamespace

from voice_ingest.interfaces.http import create_app
from voice_ingest.runtime.settings import Settings

settings = Settings(_env_file=None, api_key="schema-export", enable_mcp=False)
app = create_app(settings, runtime=SimpleNamespace())
Path(".openapi.json").write_text(json.dumps(app.openapi()))
