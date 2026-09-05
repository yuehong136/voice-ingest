FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.12.3
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --extra server --extra mcp --no-editable
COPY migrations ./migrations
COPY alembic.ini ./
COPY deploy/init_storage.py ./deploy/init_storage.py
RUN useradd --uid 10001 --create-home voice && chown -R voice:voice /app
USER voice
ENV PATH="/app/.venv/bin:$PATH" VOICE_HOST="0.0.0.0" VOICE_PORT="18080"
EXPOSE 18080
CMD ["voice-ingest-server"]
