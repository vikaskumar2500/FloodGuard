import hashlib


def calculate_checksum(data: bytes) -> str:
    """Calculate the SHA-256 checksum of the given bytes."""
    return hashlib.sha256(data).hexdigest()


def verify_checksum(data: bytes, expected_checksum: str) -> bool:
    """Verify that the checksum of the given bytes matches the expected checksum."""
    return calculate_checksum(data) == expected_checksum
