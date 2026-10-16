"""FloodGuard ML Model Training and Evaluation package."""

from floodguard_ml.models.artifacts import (
    LoadedFloodModel,
    ModelIntegrityError,
    ModelSchemaError,
    save_model_artifacts,
)
from floodguard_ml.models.baseline import RuleBasedFloodBaseline
from floodguard_ml.models.evaluation import (
    ConfusionMatrix,
    ModelMetrics,
    evaluate_predictions,
    select_optimal_threshold,
)
from floodguard_ml.models.logistic import LogisticRegressionFloodModel
from floodguard_ml.models.preprocessing import (
    BooleanToNumeric,
    build_preprocessor,
    extract_raw_matrices,
    get_transformed_feature_names,
)
from floodguard_ml.models.selection import (
    BOOLEAN_FEATURES_V1,
    CATEGORICAL_FEATURES_V1,
    EXCLUDED_COLUMNS_V1,
    MODEL_FEATURES_V1,
    NUMERIC_FEATURES_V1,
    FeatureLeakageAuditError,
    audit_feature_leakage,
)
from floodguard_ml.models.training import (
    ModelTrainingResult,
    benchmark_latency,
    evaluate_scenario_holdout,
    train_and_compare_all_models,
    train_and_evaluate_model,
)
from floodguard_ml.models.xgboost_model import XGBoostFloodModel

__all__ = [
    "BOOLEAN_FEATURES_V1",
    "BooleanToNumeric",
    "CATEGORICAL_FEATURES_V1",
    "ConfusionMatrix",
    "EXCLUDED_COLUMNS_V1",
    "FeatureLeakageAuditError",
    "LoadedFloodModel",
    "LogisticRegressionFloodModel",
    "MODEL_FEATURES_V1",
    "ModelIntegrityError",
    "ModelMetrics",
    "ModelSchemaError",
    "ModelTrainingResult",
    "NUMERIC_FEATURES_V1",
    "RuleBasedFloodBaseline",
    "XGBoostFloodModel",
    "audit_feature_leakage",
    "benchmark_latency",
    "build_preprocessor",
    "evaluate_predictions",
    "evaluate_scenario_holdout",
    "extract_raw_matrices",
    "get_transformed_feature_names",
    "save_model_artifacts",
    "select_optimal_threshold",
    "train_and_compare_all_models",
    "train_and_evaluate_model",
]

