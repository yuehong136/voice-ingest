import argparse
import contextlib
import os
from pathlib import Path

from fastmcp import FastMCP

from voice_ingest.client import AsyncVoiceClient
from voice_ingest.interfaces.mcp import WRITE, register_tools
from voice_ingest.transcription.contracts import AssetView, DomainError


def allowed_file(path: str, roots: list[Path]) -> Path:
    resolved = Path(path).expanduser().resolve(strict=True)
    if not resolved.is_file() or not any(resolved.is_relative_to(root) for root in roots):
        raise DomainError(
            "path_not_allowed", "File must be inside an explicitly allowed directory", 403
        )
    return resolved


def create_local_mcp(client: AsyncVoiceClient, allowed_roots: list[Path]) -> FastMCP:
    roots = [root.expanduser().resolve(strict=True) for root in allowed_roots]

    @contextlib.asynccontextmanager
    async def lifespan(server):
        try:
            yield {}
        finally:
            await client.close()

    mcp = FastMCP(
        "Voice Ingest Local",
        lifespan=lifespan,
        instructions="Upload only files explicitly requested by the user from allowed directories.",
    )
    register_tools(mcp, client)

    @mcp.tool(annotations=WRITE)
    async def upload_local_audio(path: str) -> AssetView:
        """Upload a local audio file from an allowed directory; returns an asset ID.

        This sends the audio to the configured backend. It does not start paid recognition.
        """
        return await client.upload(allowed_file(path, roots))

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Local stdio MCP bridge to Voice Ingest")
    parser.add_argument("--allow-dir", action="append", required=True, type=Path)
    parser.add_argument("--url", default=os.getenv("VOICE_URL", "http://localhost:18080"))
    args = parser.parse_args()
    key = os.getenv("VOICE_API_KEY", "")
    if not key:
        parser.error("VOICE_API_KEY is required")
    create_local_mcp(AsyncVoiceClient(args.url, key), args.allow_dir).run(transport="stdio")
