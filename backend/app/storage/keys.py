def generate_artifact_key(
    prefix: str, artifact_type: str, artifact_name: str, version: str, filename: str
) -> str:
    """
    Generate a storage key for an artifact.
    Example: {prefix}/{artifact_type}/{artifact_name}/{version}/{filename}
    """
    return f"{prefix}/{artifact_type}/{artifact_name}/{version}/{filename}".strip("/")
