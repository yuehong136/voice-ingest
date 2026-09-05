from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VOICE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://voice:voice@localhost:55432/voice"
    api_key: SecretStr = Field(default=SecretStr(""))
    s3_endpoint: str = "http://localhost:19000"
    s3_public_endpoint: str = "http://localhost:19000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "voice-ingest"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")
    provider: Literal["mock", "aliyun"] = "mock"
    aliyun_region: Literal["beijing", "singapore"] = "beijing"
    aliyun_workspace_id: str | None = None
    aliyun_api_key: SecretStr = SecretStr("")
    max_inflight: int = Field(default=2, ge=1, le=100)
    lease_seconds: int = Field(default=90, ge=15)
    poll_seconds: float = Field(default=5, ge=0.1)
    max_retry_count: int = Field(default=8, ge=1)
    job_deadline_seconds: int = Field(default=23 * 3600, ge=60, le=23 * 3600)
    download_url_ttl: int = Field(default=24 * 3600, ge=3600, le=7 * 86400)
    upload_url_ttl: int = Field(default=900, ge=60, le=3600)
    ffprobe_binary: str = "ffprobe"
    enable_mcp: bool = True
    allow_sqlite_tests: bool = False

    @model_validator(mode="after")
    def validate_runtime(self):
        if not self.api_key.get_secret_value():
            raise ValueError("VOICE_API_KEY must be configured")
        if not self.allow_sqlite_tests and not self.database_url.startswith(
            "postgresql+asyncpg://"
        ):
            raise ValueError("Production task scheduling requires PostgreSQL")
        for endpoint in (self.s3_endpoint, self.s3_public_endpoint):
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("S3 endpoints must be HTTP(S) origins")
            if parsed.path not in {"", "/"} or parsed.query or parsed.username:
                raise ValueError(
                    "S3 endpoints must not contain paths, query strings or credentials"
                )
        if self.provider == "aliyun" and not self.aliyun_api_key.get_secret_value():
            raise ValueError("VOICE_ALIYUN_API_KEY must be configured")
        if self.provider == "aliyun" and self.aliyun_api_key.get_secret_value().startswith(
            "sk-sp-"
        ):
            raise ValueError(
                "Token Plan/Coding Plan keys cannot use this DashScope ASR backend. "
                "Configure a regular regional Model Studio API key; "
                "no billing fallback is performed."
            )
        return self

    @property
    def aliyun_base_url(self) -> str:
        if self.aliyun_workspace_id:
            region = "cn-beijing" if self.aliyun_region == "beijing" else "ap-southeast-1"
            return f"https://{self.aliyun_workspace_id}.{region}.maas.aliyuncs.com/api/v1"
        host = "dashscope" if self.aliyun_region == "beijing" else "dashscope-intl"
        return f"https://{host}.aliyuncs.com/api/v1"
