from typing import Any

from pydantic import BaseModel


class ArtifactManifest(BaseModel):
    """Manifest for an artifact."""

    artifact_id: str
    version: str
    checksum: str
    size_bytes: int
    metadata: dict[str, Any] | None = None
    created_at: str
