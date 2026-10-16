import pytest
import os
from backend.app.storage.local import LocalArtifactStore
from ml.floodguard_ml.artifacts.repository import DatasetArtifactRepository, ModelArtifactRepository

def test_dataset_repository(tmp_path):
    store = LocalArtifactStore(str(tmp_path))
    repo = DatasetArtifactRepository(store, "ml")
    
    data = b"dataset_content"
    manifest = repo.publish("synthetic-v1", "v1.0", data, "data.csv")
    
    assert manifest.artifact_id == "synthetic-v1-v1.0"
    
    fetched_data, fetched_manifest = repo.fetch("synthetic-v1", "v1.0", "data.csv")
    assert fetched_data == b"dataset_content"
    assert fetched_manifest.checksum == manifest.checksum

def test_model_repository(tmp_path):
    store = LocalArtifactStore(str(tmp_path))
    repo = ModelArtifactRepository(store, "ml")
    
    data = b"model_content"
    manifest = repo.publish("xgboost", "v1.0", data, "model.json")
    
    assert manifest.artifact_id == "xgboost-v1.0"
    
    fetched_data, fetched_manifest = repo.fetch("xgboost", "v1.0", "model.json")
    assert fetched_data == b"model_content"
    assert fetched_manifest.checksum == manifest.checksum
