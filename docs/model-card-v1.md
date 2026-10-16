# Model Card: FloodGuard XGBoost Flood Predictor v1 (`xgboost-v1`)

## 1. Model Details

- **Model Name**: FloodGuard XGBoost Flood Predictor v1
- **Model Identifier**: `xgboost-v1`
- **Model Type**: Supervised Binary Classifier (Gradient Boosted Trees via XGBoost)
- **Version**: `1.0.0`
- **Release Date**: October 2026
- **Model Developer**: FloodGuard AI / ML Systems Team
- **Pipeline Artifacts**: `ml/artifacts/xgboost-v1/`
- **Model SHA-256 Checksum**: `5f459d781b5ba2c36e2fbde5e103c78fe45533bac83c17dbe398131d4fba9fdf`

---

## 2. Intended Use

- **Primary Application**: Predict whether a road segment `(edge_id)` will experience a `HIGH` or `SEVERE` flood risk state within the next 30 minutes ($T + 30\text{m}$) given environmental, sensor, and topographic features observed up to $T$.
- **Downstream Consumer**: Phase 13 ML-augmented routing service (proactive risk penalty calculation for Dijkstra/A* engines).
- **Target Users**: Emergency responders, civil defense planners, and routing dispatch platforms.

---

## 3. Out-of-Scope & Misuse

- **NOT for Real-World Operational Life Safety**: Training and validation were conducted exclusively on deterministic synthetic simulation data. This model must **NOT** be used for physical evacuation decisions in real weather events until validated on real historical telemetry.
- **Long-Horizon Forecasting**: The model is calibrated strictly for $H = 30$ minutes. Predicting beyond 30 minutes is invalid without retraining.
- **Unseen Topologies**: Inference on geographic regions outside the ingestion graph bounds is uncalibrated.

---

## 4. Training & Evaluation Data

- **Dataset Identifier**: `v1-3df12444-3a440b39`
- **Data Provenance**: `SYNTHETIC` (deterministic simulation scenarios from Phase 7: `NORMAL`, `MODERATE_RAIN`, `SEVERE_RAIN`, `FLASH_FLOOD`, `RECOVERY`)
- **Total Samples**: 246 rows across 6 road edges
- **Chronological Split Allocation**:
  - **Train**: 168 rows (21.43% positive rate; 36 positives, 132 negatives)
  - **Validation**: 36 rows (36.11% positive rate; 13 positives, 23 negatives)
  - **Test**: 42 rows (42.86% positive rate; 18 positives, 24 negatives)
- **Target Label**: `target_flooded_within_horizon` (water depth $\ge 15.0$ cm or severe flood polygon intersection in $(T, T + 30\text{m}]$).

---

## 5. Hyperparameters

| Parameter | Value | Rationale |
| :--- | :--- | :--- |
| `n_estimators` | `50` | Prevents overfitting on modest sample size |
| `max_depth` | `3` | Restricts tree depth to 3-way feature interactions |
| `learning_rate` | `0.05` | Conservative shrinkage rate |
| `subsample` | `0.8` | Row subsampling for tree variance reduction |
| `colsample_bytree` | `0.8` | Column subsampling per split |
| `min_child_weight` | `2.0` | Minimum sum of instance weight in a leaf |
| `scale_pos_weight` | `1.0` | Balanced weight; class ratio handled by threshold tuning |
| `eval_metric` | `logloss` | Standard binary cross-entropy loss |

---

## 6. Quantitative Performance

> **SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.**

### Test Split Performance (Untouched Evaluation, $\tau = 0.20$)
The decision threshold was tuned strictly on the validation set ($\tau = 0.20$) and evaluated on the test set:

| Metric | Score | Benchmark Comparison |
| :--- | :--- | :--- |
| **Precision** | **0.8571** | vs 0.4286 (Baseline), 0.5000 (Logistic) |
| **Recall** | **1.0000** | 100% of flooded edges detected (18 / 18) |
| **F1-Score** | **0.9231** | vs 0.6000 (Baseline), 0.6667 (Logistic) |
| **ROC-AUC** | **0.9421** | vs 0.5000 (Baseline), 0.8079 (Logistic) |
| **PR-AUC** | **0.9185** | vs 0.4286 (Baseline), 0.6421 (Logistic) |
| **Brier Score** | **0.0619** | vs 0.4671 (Baseline), 0.2315 (Logistic) |
| **Accuracy** | **0.9286** | 39 / 42 correctly classified |
| **Balanced Accuracy** | **0.9375** | Macro average between classes |

### Confusion Matrix (Test Split)
```
                  Predicted Negative    Predicted Positive
Actual Negative           21                    3           (TN=21, FP=3)
Actual Positive            0                   18           (FN=0,  TP=18)
```
- **Zero False Negatives**: All 18 imminent flood occurrences were preemptively identified.
- **Low False Positive Count**: 3 false alarms out of 24 dry scenarios.

### Inference Latency Benchmark
- **Single-Record Median Latency**: `5.274 ms` (measured over 100 independent calls)
- **Batch Latency (42 records)**: `5.188 ms` total (~0.12 ms/record)

---

## 7. Feature Importances (Gain-Based)

Top 5 predictive contributors identified by tree splits:

1. `length_m` (`0.2512`): Road edge length; longer segments aggregate larger surface runoff pools.
2. `rainfall_accum_1h_mm` (`0.1665`): 1-hour cumulative precipitation; critical soil saturation indicator.
3. `nearby_sensor_count` (`0.1579`): Telemetry coverage density.
4. `hour_of_day` (`0.0968`): Temporal progression indicator within simulated diurnal event cycles.
5. `water_depth_max_30m_cm` (`0.0775`): Peak historical water depth in the preceding 30 minutes.

---

## 8. Safety Advisory & Caveats

1. **Synthetic Data Provenance**: The underlying data originates from the FloodGuard deterministic simulator. While physical flow models are physically plausible, real stormwater drainage networks introduce unmodeled blockages, sediment buildup, and debris flows.
2. **Missing Sensor Degradation**: When real-time sensors go offline, the model gracefully relies on rainfall accumulation and road geography, but predictive uncertainty increases.
3. **Threshold Calibration**: The threshold $\tau = 0.20$ prioritizes recall ($1.00$) at the cost of a slightly higher false alarm rate ($12.5\%$). This reflects the life-safety preference for caution over complacency.

---

## 9. Operational Deployment & Routing Integration (Phase 13)

- **Integration Status**: Deployed to the FloodGuard routing and risk evaluation pipeline in Phase 13.
- **Serving Architecture**:
  - Precomputed batch inference per candidate graph bounding box prior to A*/Dijkstra exploration (ensuring $O(1)$ edge cost lookup during path relaxation).
  - Online feature generation via `OnlineFeatureBuilder` using canonical routines from `floodguard_ml.features.*` (zero training-serving skew).
  - Redis prediction cache with canonical key `floodguard:v1:ml-prediction:{graph_version_id}:{model_version}:{risk_revision}:{edge_id}:{config_hash}`.
- **Operating Modes**:
  - `SHADOW` (Default): Model generates predictions and telemetry for all road segments, logging shadow disagreements when model signals diverge from physical sensors, while routing costs remain 100% deterministic.
  - `ACTIVE`: Predictions are blended into edge costs via $R_{\text{fused}} = \max(R_{\text{det}}, (1 - \alpha) R_{\text{det}} + \alpha P_{\text{ml}})$.
  - `DISABLED`: ML inference is completely bypassed.
- **Safety Overrides**:
  - Asymmetric safety guarantee: $R_{\text{fused}} \ge R_{\text{det}}$ at all times.
  - Critical deterministic floor: Severe physical evidence (water depth $\ge 15.0$ cm, high-risk flood polygons) strictly prevents any risk downgrade regardless of model probability.
  - Graceful fallback: Any inference timeout (>500 ms) or exception automatically falls back to deterministic risk scoring.
- **Serving Latency Benchmarks**:
  - Feature extraction: $0.148\text{ ms}$ total ($0.037\text{ ms}$/edge)
  - Batch model inference: $13.68\text{ ms}$ total chunk (~$3.4\text{ ms}$/edge)
  - Redis cache lookup: $0.108\text{ ms}$
  - Warm added overhead: $\mathbf{0.157\text{ ms}}$

