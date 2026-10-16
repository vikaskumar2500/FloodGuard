class StorageError(Exception):
    """Base exception for storage errors."""

    pass


class ObjectNotFoundError(StorageError):
    """Raised when an object is not found in storage."""

    pass


class ObjectAlreadyExistsError(StorageError):
    """Raised when an object already exists and overwrite is False."""

    pass


class ChecksumMismatchError(StorageError):
    """Raised when the calculated checksum does not match the expected checksum."""

    pass


class ConfigurationError(StorageError):
    """Raised when the storage configuration is invalid."""

    pass
