# Phase 17: S3 Data & Model Artifact Storage

This phase implements S3-based artifact storage for both datasets and trained models.

## Features
- Modular `backend/app/storage/` system.
- Support for both Local and S3 storage.
- Checksum validation on upload and download.
- CLI commands in `ml/floodguard_ml/cli.py` to publish and fetch models and datasets.
- Runtime fallback to deterministic logic when ML model is unavailable.

## Configuration
To use S3 for artifact storage, configure the following environment variables:
- `ML_S3_BUCKET`: The S3 bucket name.
- `AWS_REGION`: The AWS region.
- `ML_S3_KEY`: (Optional) The S3 key for the model.

If S3 download fails, the system falls back to the locally cached model or deterministic logic.
