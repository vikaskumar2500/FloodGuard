import boto3
from app.storage.base import ArtifactStore
from app.storage.checksums import verify_checksum
from app.storage.exceptions import (
    ChecksumMismatchError,
    ConfigurationError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
)
from botocore.exceptions import ClientError


class S3ArtifactStore(ArtifactStore):
    def __init__(self, bucket_name: str, region_name: str | None = None, use_sse: bool = True):
        self.bucket_name = bucket_name
        self.use_sse = use_sse
        try:
            self.s3_client = boto3.client("s3", region_name=region_name)
        except Exception as e:
            raise ConfigurationError(f"Failed to initialize S3 client: {e}")

    def put_bytes(
        self,
        key: str,
        data: bytes,
        overwrite: bool = False,
        expected_checksum: str | None = None,
    ) -> None:
        if not overwrite and self.exists(key):
            raise ObjectAlreadyExistsError(f"Object {key} already exists")

        if expected_checksum and not verify_checksum(data, expected_checksum):
            raise ChecksumMismatchError("Checksum mismatch on put")

        kwargs = {"Bucket": self.bucket_name, "Key": key, "Body": data}
        if self.use_sse:
            kwargs["ServerSideEncryption"] = "AES256"

        try:
            self.s3_client.put_object(**kwargs)
        except ClientError as e:
            raise ConfigurationError(f"Failed to put object: {e}")

    def get_bytes(self, key: str) -> bytes:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise ObjectNotFoundError(f"Object {key} not found")
            raise

    def list(self, prefix: str) -> list[str]:
        keys = []
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        keys.append(obj["Key"])
            return keys
        except ClientError as e:
            raise ConfigurationError(f"Failed to list objects: {e}")

    def exists(self, key: str) -> bool:
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def delete(self, key: str) -> None:
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            raise ConfigurationError(f"Failed to delete object: {e}")
