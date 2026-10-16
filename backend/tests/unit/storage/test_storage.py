import boto3
import pytest
from app.storage.exceptions import (
    ChecksumMismatchError,
    ObjectAlreadyExistsError,
    ObjectNotFoundError,
)
from app.storage.local import LocalArtifactStore
from app.storage.s3 import S3ArtifactStore
from moto import mock_aws


def test_local_artifact_store(tmp_path):
    store = LocalArtifactStore(str(tmp_path))

    # Test put and get
    store.put_bytes("test/key.txt", b"hello world")
    assert store.get_bytes("test/key.txt") == b"hello world"

    # Test exists
    assert store.exists("test/key.txt")
    assert not store.exists("test/notfound.txt")

    # Test checksum mismatch
    with pytest.raises(ChecksumMismatchError):
        store.put_bytes("test/key2.txt", b"hello", expected_checksum="invalid")

    # Test overwrite
    with pytest.raises(ObjectAlreadyExistsError):
        store.put_bytes("test/key.txt", b"hello world 2", overwrite=False)

    store.put_bytes("test/key.txt", b"hello world 2", overwrite=True)
    assert store.get_bytes("test/key.txt") == b"hello world 2"


@mock_aws
def test_s3_artifact_store():
    # Setup mock S3
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="test-bucket")

    store = S3ArtifactStore("test-bucket", region_name="us-east-1", use_sse=False)

    store.put_bytes("test/key.txt", b"hello world s3")
    assert store.get_bytes("test/key.txt") == b"hello world s3"

    assert store.exists("test/key.txt")
    assert not store.exists("test/notfound.txt")

    with pytest.raises(ObjectNotFoundError):
        store.get_bytes("test/notfound.txt")
