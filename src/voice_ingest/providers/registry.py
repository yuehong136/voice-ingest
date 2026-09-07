"""Explicit deployments, immutable configuration snapshots and capability routing."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from voice_ingest.media.source import SourcePreparer
from voice_ingest.providers.speech import SpeechAdapter, SpeechRequest
from voice_ingest.transcription.contracts import DomainError, ModelCapability


@dataclass
class Deployment:
    id: str
    adapter: SpeechAdapter
    revision: str = "1"
    location: Literal["cloud", "local", "test"] = "cloud"
    max_inflight: int = 2
    configuration: dict[str, Any] = field(default_factory=dict)
    source: SourcePreparer | None = None

    def snapshot(self) -> dict[str, Any]:
        # configuration may contain credential references, never credential values.
        data = dict(
            id=self.id,
            revision=self.revision,
            adapter=self.adapter.name,
            location=self.location,
            configuration=self.configuration,
        )
        data["fingerprint"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        return data


class Registry:
    def __init__(self, deployments: list[Deployment]):
        self.deployments: dict[str, Deployment] = {}
        for deployment in deployments:
            if deployment.id in self.deployments or deployment.max_inflight < 1:
                raise ValueError("Duplicate deployment or invalid capacity")
            self.deployments[deployment.id] = deployment

    def models(self) -> list[ModelCapability]:
        return [
            model.model_copy(
                update={
                    "deployment_id": d.id,
                    "deployment_revision": d.revision,
                    "location": d.location,
                }
            )
            for d in self.deployments.values()
            for model in d.adapter.models()
        ]

    def select(self, request: SpeechRequest) -> Deployment:
        options = request.options
        candidates = [
            d
            for d in self.deployments.values()
            if (not options.get("deployment_id") or d.id == options["deployment_id"])
            and (options.get("routing") != "local_only" or d.location == "local")
            and any(m.id == options["model"] and m.kind == request.kind for m in d.adapter.models())
        ]
        if not candidates:
            raise DomainError("unsupported_deployment", "No deployment supports this request")
        if len(candidates) != 1:
            raise DomainError("deployment_required", "Select an explicit deployment")
        candidates[0].adapter.validate(request)
        return candidates[0]

    def restore(self, snapshot: dict[str, Any]) -> Deployment:
        deployment = self.deployments.get(snapshot.get("id", ""))
        if not deployment or deployment.snapshot() != snapshot:
            raise DomainError(
                "provider_configuration_changed",
                "Restore the deployment revision used by this attempt",
                409,
            )
        return deployment

    def match_historical(self, provider: str, region: str, request: dict[str, Any]) -> Deployment:
        deployment = self.deployments.get("default")
        if deployment:
            config = deployment.configuration
            endpoint = "mock" if deployment.location == "test" else config.get("endpoint")
            if (
                deployment.adapter.name == provider
                and config.get("region") == region
                and config.get("source_mode") == request.get("source_mode")
                and endpoint == request.get("endpoint")
            ):
                return deployment
        raise DomainError(
            "provider_configuration_changed",
            "Restore the recorded historical deployment before recovery",
            409,
        )
