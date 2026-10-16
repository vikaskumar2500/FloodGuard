import os

from app.storage.base import ArtifactStore
from app.storage.checksums import verify_checksum
from app.storage.exceptions import (
    ChecksumMismatchError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
)


class LocalArtifactStore(ArtifactStore):
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    def _get_full_path(self, key: str) -> str:
        return os.path.join(self.base_dir, key)

    def put_bytes(
        self,
        key: str,
        data: bytes,
        overwrite: bool = False,
        expected_checksum: str | None = None,
    ) -> None:
        full_path = self._get_full_path(key)
        if not overwrite and os.path.exists(full_path):
            raise ObjectAlreadyExistsError(f"Object {key} already exists")

        if expected_checksum and not verify_checksum(data, expected_checksum):
            raise ChecksumMismatchError("Checksum mismatch on put")

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(data)

    def get_bytes(self, key: str) -> bytes:
        full_path = self._get_full_path(key)
        if not os.path.exists(full_path):
            raise ObjectNotFoundError(f"Object {key} not found")
        with open(full_path, "rb") as f:
            return f.read()

    def list(self, prefix: str) -> list[str]:
        keys = []
        full_prefix = os.path.join(self.base_dir, prefix)
        for root, _, files in os.walk(self.base_dir):
            for file in files:
                path = os.path.join(root, file)
                if path.startswith(full_prefix):
                    keys.append(os.path.relpath(path, self.base_dir))
        return keys

    def exists(self, key: str) -> bool:
        return os.path.exists(self._get_full_path(key))

    def delete(self, key: str) -> None:
        if self.exists(key):
            os.remove(self._get_full_path(key))
