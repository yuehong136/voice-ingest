FROM python:3.13.11-slim-bookworm
ARG VOICE_APT_MIRROR=deb.debian.org
ARG VOICE_PYPI_INDEX_URL=https://pypi.org/simple
ARG VOICE_PYPI_TRUSTED_HOST=
RUN if [ "$VOICE_APT_MIRROR" != "deb.debian.org" ]; then \
        sed -i "s|deb.debian.org|$VOICE_APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN trusted_host_args="" \
    && if [ -n "$VOICE_PYPI_TRUSTED_HOST" ]; then \
        trusted_host_args="--trusted-host $VOICE_PYPI_TRUSTED_HOST"; \
    fi \
    && pip install --no-cache-dir --index-url "$VOICE_PYPI_INDEX_URL" \
        $trusted_host_args uv==0.12.3
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN if [ -n "$VOICE_PYPI_TRUSTED_HOST" ]; then \
        export UV_INSECURE_HOST="$VOICE_PYPI_TRUSTED_HOST"; \
    fi \
    && UV_DEFAULT_INDEX="$VOICE_PYPI_INDEX_URL" \
        uv sync --frozen --no-dev --extra server --extra mcp --no-editable
COPY migrations ./migrations
COPY alembic.ini ./
COPY deploy/init_storage.py ./deploy/init_storage.py
COPY deploy/storage_snapshot.py ./deploy/storage_snapshot.py
RUN useradd --uid 10001 --user-group --create-home voice-ingest
USER voice-ingest
ENV PATH="/app/.venv/bin:$PATH" VOICE_HOST="0.0.0.0" VOICE_PORT="18080"
EXPOSE 18080
CMD ["voice-ingest-server"]
