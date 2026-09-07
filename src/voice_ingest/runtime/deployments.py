"""Composition root: adapter factories are registered here, outside the scheduler."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from voice_ingest.media.source import SignedSource
from voice_ingest.media.storage import S3Storage
from voice_ingest.providers.aliyun import AliyunProvider
from voice_ingest.providers.aliyun_speech import AliyunSpeechAdapter
from voice_ingest.providers.aliyun_upload import AliyunTemporarySource
from voice_ingest.providers.base import ASRProvider
from voice_ingest.providers.mock import MockProvider
from voice_ingest.providers.mock_speech import MockSpeechAdapter
from voice_ingest.providers.registry import Deployment, Registry
from voice_ingest.runtime.settings import Settings


class DeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    revision: str = "1"
    adapter: Literal["aliyun", "mock"]
    region: Literal["beijing", "singapore"] = "beijing"
    workspace_id: str | None = None
    credential_env: str = "VOICE_ALIYUN_API_KEY"
    source_mode: Literal["signed_url", "temporary_upload"] = "signed_url"
    max_inflight: int = Field(default=2, ge=1, le=100)


def create_registry(
    settings: Settings, storage: S3Storage, client: ASRProvider | None = None
) -> Registry:
    if settings.deployments_file:
        configs = [
            DeploymentConfig.model_validate(item)
            for item in json.loads(Path(settings.deployments_file).read_text(encoding="utf-8"))
        ]
        if not configs or len({c.adapter == "mock" for c in configs}) > 1:
            raise ValueError("Do not mix test deployments with real providers")
    else:
        configs = [
            DeploymentConfig(
                id="default",
                adapter=settings.provider,
                region=settings.aliyun_region,
                workspace_id=settings.aliyun_workspace_id,
                source_mode=settings.aliyun_source_mode,
                max_inflight=settings.max_inflight,
            )
        ]
    deployments = []
    for config in configs:
        secret = (
            os.environ.get(config.credential_env, "")
            if settings.deployments_file
            else settings.aliyun_api_key.get_secret_value()
        )
        local_settings = Settings.model_validate(
            {
                **settings.model_dump(),
                "provider": config.adapter,
                "aliyun_region": config.region,
                "aliyun_workspace_id": config.workspace_id,
                "aliyun_source_mode": config.source_mode,
                "aliyun_api_key": SecretStr(secret),
            }
        )
        provider = client or (
            AliyunProvider(local_settings) if config.adapter == "aliyun" else MockProvider()
        )
        adapter = (AliyunSpeechAdapter if config.adapter == "aliyun" else MockSpeechAdapter)(
            provider, local_settings
        )
        source = (
            AliyunTemporarySource(storage, local_settings)
            if config.source_mode == "temporary_upload"
            else SignedSource(storage)
        )
        deployments.append(
            Deployment(
                config.id,
                adapter,
                config.revision,
                "cloud" if config.adapter == "aliyun" else "test",
                config.max_inflight,
                {
                    "region": config.region,
                    "endpoint": local_settings.aliyun_base_url,
                    "workspace_id": config.workspace_id,
                    "source_mode": config.source_mode,
                    "credential_env": config.credential_env,
                },
                source,
            )
        )
    return Registry(deployments)
