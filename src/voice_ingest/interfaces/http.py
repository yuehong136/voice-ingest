import contextlib
import hmac
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from starlette.types import ASGIApp, Receive, Scope, Send

from voice_ingest.exports.render import CONTENT_TYPES, EXTENSIONS
from voice_ingest.media.contracts import CreateUpload, SignedPart, UploadView
from voice_ingest.runtime.container import Runtime, configure_logging
from voice_ingest.runtime.database import Job, WorkerHeartbeat, now
from voice_ingest.runtime.settings import Settings
from voice_ingest.transcription.contracts import (
    ACTIVE,
    AssetView,
    CreateTranscription,
    DomainError,
    ExportFormat,
    JobPage,
    JobView,
    ModelCapability,
    RetryRequest,
    Transcript,
    TranscriptPage,
)


class AuthMiddleware:
    def __init__(self, app: ASGIApp, api_key: str):
        self.app, self.api_key = app, api_key.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        path = scope.get("path", "")
        if path not in {"/health/live", "/health/ready"}:
            header = dict(scope.get("headers", [])).get(b"authorization", b"")
            if not hmac.compare_digest(header, b"Bearer " + self.api_key):
                response = JSONResponse(
                    {
                        "error": {
                            "code": "unauthorized",
                            "message": "Valid Bearer API key required",
                            "retryable": False,
                            "request_id": request_id,
                        }
                    },
                    status_code=401,
                )
                return await response(scope, receive, send)
        try:
            await self.app(scope, receive, guarded_send)
        except DomainError as exc:
            if started:
                return
            response = JSONResponse(
                {"error": exc.info.model_copy(update={"request_id": request_id}).model_dump()},
                status_code=exc.status,
            )
            await response(scope, receive, send)
        except Exception:
            if started:
                return
            # Do not expose or log raw transport/SQL exceptions containing credentials.
            response = JSONResponse(
                {
                    "error": {
                        "code": "internal_error",
                        "message": "Service operation failed",
                        "retryable": False,
                        "request_id": request_id,
                    }
                },
                status_code=500,
            )
            await response(scope, receive, send)


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    configure_logging()
    settings = settings or Settings()
    owned = runtime is None
    runtime = runtime or Runtime(settings)
    mcp_app = None
    if settings.enable_mcp:
        from voice_ingest.interfaces.mcp import create_mcp

        mcp_app = create_mcp(runtime.transcriptions).http_app(path="/")

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with contextlib.AsyncExitStack() as stack:
            if mcp_app:
                await stack.enter_async_context(mcp_app.lifespan(mcp_app))
            try:
                yield
            finally:
                if owned:
                    await runtime.close()

    app = FastAPI(title="Voice Ingest", version="0.1.0", lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(AuthMiddleware, api_key=settings.api_key.get_secret_value())

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(
            {
                "error": exc.info.model_copy(
                    update={"request_id": request.state.request_id}
                ).model_dump()
            },
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "invalid_request",
                    "message": "Request does not match the API schema",
                    "retryable": False,
                    "request_id": request.state.request_id,
                }
            },
            status_code=422,
        )

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        try:
            async with runtime.sessions() as session:
                await session.execute(text("SELECT 1"))
                await session.execute(select(Job.id).limit(1))
            await runtime.storage.health()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready", "provider": settings.provider}

    @app.get("/metrics")
    async def metrics():
        async with runtime.sessions() as session:
            counts = (
                await session.execute(select(Job.state, func.count()).group_by(Job.state))
            ).all()
            oldest = await session.scalar(
                select(func.min(Job.created_at)).where(Job.state.in_(ACTIVE))
            )
            workers = await session.scalar(
                select(func.count())
                .select_from(WorkerHeartbeat)
                .where(
                    WorkerHeartbeat.seen_at > now() - timedelta(seconds=settings.lease_seconds * 2)
                )
            )
            errors = (
                (await session.execute(select(Job.error).where(Job.error.is_not(None))))
                .scalars()
                .all()
            )
        lines = [f'voice_jobs{{state="{state}"}} {count}' for state, count in counts]
        age = max(0, now().timestamp() - oldest.timestamp()) if oldest else 0
        lines.append(f"voice_queue_oldest_seconds {age}")
        lines.append(f"voice_workers_alive {workers or 0}")
        for category in (
            "provider_unavailable",
            "provider_rate_limited",
            "provider_file_failed",
            "result_download_failed",
        ):
            count = sum((e or {}).get("code") == category for e in errors)
            lines.append(f'voice_jobs_with_error{{code="{category}"}} {count}')
        return Response("\n".join(lines) + "\n", media_type="text/plain")

    @app.post("/v1/uploads", status_code=201)
    async def create_upload(body: CreateUpload) -> UploadView:
        return await runtime.uploads.create(body)

    @app.get("/v1/uploads/{upload_id}")
    async def get_upload(upload_id: str) -> UploadView:
        return await runtime.uploads.get(upload_id)

    @app.post("/v1/uploads/{upload_id}/parts/{part}")
    async def sign_part(upload_id: str, part: int) -> SignedPart:
        return await runtime.uploads.sign(upload_id, part)

    @app.post("/v1/uploads/{upload_id}/complete")
    async def complete_upload(upload_id: str) -> UploadView:
        return await runtime.uploads.complete(upload_id)

    @app.delete("/v1/uploads/{upload_id}", status_code=204)
    async def abort_upload(upload_id: str):
        await runtime.uploads.abort(upload_id)

    @app.get("/v1/assets/{asset_id}")
    async def get_asset(asset_id: str) -> AssetView:
        return await runtime.uploads.get_asset(asset_id)

    @app.delete("/v1/assets/{asset_id}", status_code=204)
    async def delete_asset(asset_id: str):
        await runtime.uploads.delete_asset(asset_id)

    @app.get("/v1/models")
    async def models() -> list[ModelCapability]:
        return runtime.transcriptions.models()

    @app.post("/v1/transcriptions", status_code=202)
    async def create_transcription(
        body: CreateTranscription, idempotency_key: str = Header(min_length=1, max_length=200)
    ) -> JobView:
        return await runtime.transcriptions.create(body, idempotency_key)

    @app.get("/v1/transcriptions")
    async def list_transcriptions(
        cursor: str | None = None, limit: int = Query(50, ge=1, le=100)
    ) -> JobPage:
        return await runtime.transcriptions.list(cursor, limit)

    @app.get("/v1/transcriptions/{job_id}")
    async def get_transcription(job_id: str) -> JobView:
        return await runtime.transcriptions.get(job_id)

    @app.post("/v1/transcriptions/{job_id}/cancel")
    async def cancel(job_id: str) -> JobView:
        return await runtime.transcriptions.cancel(job_id)

    @app.post("/v1/transcriptions/{job_id}/retry")
    async def retry(job_id: str, body: RetryRequest) -> JobView:
        return await runtime.transcriptions.retry(job_id, body.acknowledge_duplicate_risk)

    @app.get("/v1/transcriptions/{job_id}/result")
    async def result(job_id: str) -> Transcript:
        return await runtime.transcriptions.result(job_id)

    @app.get("/v1/transcriptions/{job_id}/segments")
    async def segments(
        job_id: str,
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TranscriptPage:
        return await runtime.transcriptions.read(job_id, cursor, limit, start_ms, end_ms)

    @app.get("/v1/transcriptions/{job_id}/exports/{format}")
    async def export(job_id: str, format: ExportFormat):
        data = await runtime.transcriptions.export(job_id, format)
        return Response(
            data,
            media_type=CONTENT_TYPES[format],
            headers={
                "Content-Disposition": f'attachment; filename="transcript.{EXTENSIONS[format]}"'
            },
        )

    @app.delete("/v1/transcriptions/{job_id}", status_code=204)
    async def delete_transcription(job_id: str):
        await runtime.transcriptions.delete(job_id)

    if mcp_app:
        app.mount("/mcp", mcp_app)
    return app
