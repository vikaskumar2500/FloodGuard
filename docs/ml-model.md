# FloodGuard ML Flood Prediction Model Architecture

> **SYNTHETIC DATASET EVALUATION ADVISORY**  
> *All models trained and evaluated in Phase 12 use synthetic simulation scenarios (`SYNTHETIC` provenance). Real historical training is currently blocked pending PostGIS historical sensor archive population. These models establish architectural parity, reproducible offline pipelines, and baseline benchmarks. Do NOT claim real-world operational safety or predictive accuracy from synthetic metrics.*

---

## 1. Problem Formulation

- **Prediction Unit**: `(edge_id, observation_time)` representing a directed road segment at time $T$.
- **Prediction Horizon**: $H = 30$ minutes.
- **Target Variable**: `target_flooded_within_horizon` $\in \{0, 1\}$.
  - `0`: No `HIGH` or `SEVERE` flood risk state occurs on the edge in $(T, T + H]$.
  - `1`: Edge transitions to or experiences `HIGH` or `SEVERE` flood state in $(T, T + H]$.
- **Objective**: Accurately predict upcoming road segment inundation prior to physical occurrence, allowing downstream rerouting engines to proactively avoid hazardous passages.

---

## 2. Feature Specification (`MODEL_FEATURES_V1`)

Models consume a canonical set of 29 features derived exclusively from observations at or before time $T$:

### Numeric Features (22)
- `rainfall_rate_now_mm_h`: Instantaneous rainfall rate (mm/h).
- `rainfall_accum_15m_mm`, `rainfall_accum_30m_mm`, `rainfall_accum_1h_mm`, `rainfall_accum_3h_mm`: Rolling rainfall accumulation windows.
- `temperature_c`, `humidity_pct`, `wind_speed_mps`: Environmental surface conditions.
- `weather_freshness_seconds`: Observation latency from environmental data source.
- `water_depth_current_cm`: Latest measured water depth on edge.
- `water_depth_trend_cm_per_min`: Rate of water level change over the preceding 10 minutes.
- `water_depth_max_30m_cm`: Peak water depth observed in the last 30 minutes.
- `nearby_sensor_count`, `sensor_confidence`, `sensor_freshness_seconds`: Sensor metadata.
- `length_m`, `speed_limit_mps`, `edge_elevation_m`: Static road geometry and elevation attributes.
- `hour_of_day`, `day_of_week`, `month`: Temporal cycle features.
- `historical_flood_count_30d`: Cumulative flood events on edge over previous 30 days.

### Categorical Features (2)
- `road_class`: Road type classification (`motorway`, `trunk`, `primary`, `secondary`, `tertiary`, `residential`).
- `season_category`: Seasonal meteorological regime (`MONSOON`, `PRE_MONSOON`, `POST_MONSOON`, `DRY`).

### Boolean Indicator Features (5)
- `is_bridge`, `is_tunnel`: Structural flood vulnerability indicators.
- `is_rainfall_missing`, `is_water_depth_missing`, `is_temperature_missing`: Explicit missingness indicators distinguishing true zero measurements ($0.0$) from unobserved telemetry (`None`).

### Explicitly Excluded Columns (Leakage Audit)
- `edge_id`: Spatial memorization avoidance.
- `observation_time`: Raw timestamp string (captured by temporal cycle indicators).
- `dist_to_flood_zone_m`: 100% missing in synthetic fixture environment; excluded to eliminate spurious pseudo-signals.
- `source_type`: Constant across synthetic records (`SYNTHETIC`); zero discriminative variance.
- `prediction_horizon_minutes`: Constant configuration parameter.
- `target_flooded_within_horizon`: Supervised prediction label.

---

## 3. Preprocessing Architecture

The preprocessing pipeline is built using `sklearn.compose.ColumnTransformer`:

```
Input Record (dict)
        │
        ├──> Numeric [22 cols]     ──> SimpleImputer(median) ──> [StandardScaler (Logistic only)]
        │
        ├──> Categorical [2 cols]  ──> SimpleImputer("UNKNOWN") ──> OneHotEncoder(ignore_unknown)
        │
        └──> Boolean [5 cols]      ──> BooleanToNumeric() ──> SimpleImputer(most_frequent)
```

### Strict Train-Only Fitting Contract
The `ColumnTransformer` is fitted **exclusively on the training split**. Validation and test records are strictly transformed using the train-fitted imputers, scalers, and encoders to guarantee zero data leakage across split boundaries.

---

## 4. Model Candidates

### 4.1. Rule-Based Baseline (`RuleBasedFloodBaseline`)
Deterministic heuristic predictor used as an unlearned benchmark:
$$\hat{y} = 1 \iff (\text{water\_depth\_current\_cm} \ge 15.0) \lor (\text{rainfall\_rate\_now\_mm\_h} \ge 30.0)$$

### 4.2. Logistic Regression Baseline (`LogisticRegressionFloodModel`)
- Regularized linear probabilistic model with `L2` penalty ($C = 1.0$).
- Standardized numeric features via `StandardScaler`.
- `class_weight="balanced"` to address flood incidence class imbalance.
- Provides standardized regression coefficients for linear feature interpretability.

### 4.3. XGBoost Classifier (`XGBoostFloodModel`)
- Gradient boosted decision tree pipeline using unscaled numeric inputs.
- Conservative hyperparameters tailored for tabular stability:
  - `max_depth = 3`
  - `n_estimators = 50`
  - `learning_rate = 0.05`
  - `subsample = 0.8`
  - `colsample_bytree = 0.8`
  - `min_child_weight = 2.0`
  - `eval_metric = "logloss"`
- Provides gain-based feature importances ranking predictive contribution.

---

## 5. Threshold Tuning Protocol (Validation Isolation)

To reflect the mission-critical safety requirements of flood routing:
1. False Negatives (predicting dry when an edge floods) carry significantly higher cost than False Positives (unnecessary reroute).
2. The optimal decision threshold $\tau^*$ is selected **exclusively on the validation split**:
   $$\tau^* = \arg\max_{\tau \in \{0.2, 0.3, \dots, 0.8\}} F_1(\tau) \quad \text{subject to } \text{Recall}(\tau) \ge 0.70$$
3. The test split is held completely untouched during threshold tuning and is only evaluated once at $\tau^*$.

---

## 6. Artifact Persistence & Schema Validation

Model binaries and runtime metadata are persisted under `ml/artifacts/<model_version>/`:

```
ml/artifacts/xgboost-v1/
├── model.joblib              # Serialized pipeline binary
├── metadata.json             # Model version, SHA-256 hash, dataset version, hyperparameters
├── metrics.json              # Train, validation, and test performance metrics
├── threshold.json            # Selected decision threshold and tuning curve
├── feature_schema.json       # Expected feature column names and counts
└── feature_importance.json   # Ranked feature contributions (gain / coefficients)
```

### Loaded Model Runtime (`LoadedFloodModel`)
- Validates SHA-256 file checksum against `metadata.json` upon loading.
- Rejects corrupt or tampered model weights with `ModelIntegrityError`.
- Validates inference record schemas against `feature_schema.json`, raising `ModelSchemaError` if required features are absent.

---

## 7. CLI Usage

### Train Single Model
```bash
PYTHONPATH=ml:backend backend/.venv/bin/python ml/floodguard_ml/cli.py train \
    --dataset data/processed/synthetic-v1 \
    --model xgboost \
    --output ml/artifacts \
    --min-recall 0.70
```

### Compare and Benchmark All Models
```bash
PYTHONPATH=ml:backend backend/.venv/bin/python ml/floodguard_ml/cli.py compare-models \
    --dataset data/processed/synthetic-v1 \
    --output ml/artifacts
```

