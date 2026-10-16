from typing import Dict, Any, Optional
import json
from datetime import datetime
from backend.app.storage.base import ArtifactStore
from backend.app.storage.models import ArtifactManifest
from backend.app.storage.keys import generate_artifact_key
from backend.app.storage.checksums import calculate_checksum

class BaseArtifactRepository:
    def __init__(self, store: ArtifactStore, prefix: str):
        self.store = store
        self.prefix = prefix
        self.artifact_type = "base"

    def _get_manifest_key(self, name: str, version: str) -> str:
        return generate_artifact_key(self.prefix, self.artifact_type, name, version, "manifest.json")
        
    def _get_data_key(self, name: str, version: str, filename: str) -> str:
        return generate_artifact_key(self.prefix, self.artifact_type, name, version, filename)

    def publish(self, name: str, version: str, data: bytes, filename: str, metadata: Optional[Dict[str, Any]] = None) -> ArtifactManifest:
        checksum = calculate_checksum(data)
        data_key = self._get_data_key(name, version, filename)
        
        self.store.put_bytes(data_key, data, overwrite=False)
        
        manifest = ArtifactManifest(
            artifact_id=f"{name}-{version}",
            version=version,
            checksum=checksum,
            size_bytes=len(data),
            metadata=metadata,
            created_at=datetime.utcnow().isoformat()
        )
        
        manifest_key = self._get_manifest_key(name, version)
        self.store.put_bytes(manifest_key, json.dumps(manifest.dict()).encode("utf-8"), overwrite=False)
        return manifest

    def fetch(self, name: str, version: str, filename: str) -> tuple[bytes, ArtifactManifest]:
        manifest_key = self._get_manifest_key(name, version)
        manifest_data = self.store.get_bytes(manifest_key)
        manifest = ArtifactManifest(**json.loads(manifest_data.decode("utf-8")))
        
        data_key = self._get_data_key(name, version, filename)
        data = self.store.get_bytes(data_key)
        
        from backend.app.storage.exceptions import ChecksumMismatchError
        if calculate_checksum(data) != manifest.checksum:
            raise ChecksumMismatchError("Checksum verification failed on fetch")
            
        return data, manifest

class DatasetArtifactRepository(BaseArtifactRepository):
    def __init__(self, store: ArtifactStore, prefix: str):
        super().__init__(store, prefix)
        self.artifact_type = "datasets"

class ModelArtifactRepository(BaseArtifactRepository):
    def __init__(self, store: ArtifactStore, prefix: str):
        super().__init__(store, prefix)
        self.artifact_type = "models"
