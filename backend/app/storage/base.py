from abc import ABC, abstractmethod


class ArtifactStore(ABC):
    """Base class for artifact storage."""

    @abstractmethod
    def put_bytes(
        self,
        key: str,
        data: bytes,
        overwrite: bool = False,
        expected_checksum: str | None = None,
    ) -> None:
        """Put bytes into storage."""
        pass

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        """Get bytes from storage."""
        pass

    @abstractmethod
    def list(self, prefix: str) -> list[str]:
        """List keys with the given prefix."""
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a key exists in storage."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete an object from storage."""
        pass
