# Phase 12 — Flood Prediction Model Verification Report

> **SYNTHETIC DATASET EVALUATION**  
> *All models and evaluation metrics in this report were obtained using synthetic simulation datasets (`v1-3df12444-3a440b39`). Real historical sensor datasets are currently BLOCKED pending PostGIS archive ingestion. Do NOT claim real-world operational predictive accuracy based on these synthetic metrics.*

---

## 1. Executive Summary

Phase 12 (Flood Prediction Model) is **COMPLETE**.

We implemented, trained, evaluated, and persisted reproducible baseline and ML models for 30-minute prospective road flood prediction (`target_flooded_within_horizon`).

### Key Highlights
- **Models Implemented**: Rule-Based Baseline, Logistic Regression Baseline, and XGBoost Classifier.
- **Strict Leakage Prevention**: Feature leakage audit automatically blocks target proxies and temporal leakage; preprocessing and threshold selection are strictly fitted on Train and Validation splits respectively.
- **Decision Threshold Optimization**: Tuned exclusively on the Validation split ($\tau^* = 0.20$) subject to a safety-first $\text{Recall} \ge 0.70$ constraint.
- **Test Performance (Untouched Split)**:
  - **XGBoost**: F1 = **0.9231**, PR-AUC = **0.9185**, ROC-AUC = **0.9421**, Recall = **1.0000** (18/18 detected), Precision = **0.8571** (3 FP).
  - **Logistic**: F1 = **0.6667**, PR-AUC = **0.6421**, ROC-AUC = **0.8079**, Recall = **1.0000**, Precision = **0.5000** (18 FP).
  - **Baseline**: F1 = **0.6000**, PR-AUC = **0.4286**, ROC-AUC = **0.5000**, Recall = **1.0000**, Precision = **0.4286** (24 FP).
- **Inference Latency**: XGBoost single-row median latency is **5.274 ms**, comfortably satisfying real-time routing requirements (<10 ms).
- **Model Persistence**: Serialized pipelines with SHA-256 integrity validation, runtime schema checking, and threshold metadata saved under `ml/artifacts/`.
- **Zero Production Disruption**: Phase 12 is completely offline; production routing and real-time invalidation pipelines (Phases 0–10) remain untouched.

---

## 2. Verification Checklist

| Requirement | Implementation Details | Status |
| :--- | :--- | :--- |
| **Prediction Unit & Horizon** | `(edge_id, observation_time)` with $H = 30$ minutes. | PASSED |
| **Feature Leakage Audit** | `audit_feature_leakage()` strictly blocks `target_*`, timestamps, and spatial IDs. | PASSED |
| **Reproducible Preprocessing** | `ColumnTransformer` with median imputation, `BooleanToNumeric`, and train-only fitting. | PASSED |
| **Rule-Based Baseline** | `RuleBasedFloodBaseline` heuristic evaluated as benchmark. | PASSED |
| **Logistic Regression Pipeline** | `LogisticRegressionFloodModel` with standardization, class weighting, and coefficients. | PASSED |
| **XGBoost Classifier Pipeline** | `XGBoostFloodModel` with conservative hyperparameters and gain importances. | PASSED |
| **Validation-Only Thresholding** | `select_optimal_threshold()` maximizes F1 subject to $\text{Recall} \ge 0.70$ on validation only. | PASSED |
| **Untouched Test Split** | Final evaluation metrics evaluated strictly once at validation-selected threshold. | PASSED |
| **Artifact Persistence** | Model binary (`joblib`), metadata, metrics, threshold, schema, and importances saved. | PASSED |
| **SHA-256 Integrity Verification** | Checksum verified on load; corrupt or tampered artifacts raise `ModelIntegrityError`. | PASSED |
| **Runtime Schema Validation** | `LoadedFloodModel` validates feature existence and types, raising `ModelSchemaError`. | PASSED |
| **Scenario Holdout Evaluation** | Model trained on subset scenarios, tested on held-out `FLASH_FLOOD` scenario. | PASSED |
| **Inference Latency Benchmarks** | Single-record median over 100 runs and batch latencies recorded. | PASSED |
| **CLI Commands** | `train` and `compare-models` subcommands integrated into `floodguard_ml.cli`. | PASSED |
| **ML Unit & Integration Tests** | 51 tests passed across `ml/tests/`. | PASSED |
| **Full System Regressions** | Phase 0–11 backend, simulator, and cache benchmarks fully preserved. | PASSED |

---

## 3. Comparative Evaluation Benchmark

Results obtained by running:
```bash
PYTHONPATH=ml:backend backend/.venv/bin/python ml/floodguard_ml/cli.py compare-models \
    --dataset data/processed/synthetic-v1 \
    --output ml/artifacts
```

### 3.1. Side-by-Side Model Comparison Table

| Metric | Rule-Based Baseline | Logistic Regression | XGBoost Classifier | Winner / Analysis |
| :--- | :---: | :---: | :---: | :--- |
| **Selected Threshold ($\tau^*$)** | `0.20` | `0.30` | `0.20` | Validation-tuned |
| **Test Recall** | **1.0000** (18/18) | **1.0000** (18/18) | **1.0000** (18/18) | All models detected all floods |
| **Test Precision** | `0.4286` | `0.5000` | **0.8571** | **XGBoost (+35.7% vs Logistic)** |
| **Test F1-Score** | `0.6000` | `0.6667` | **0.9231** | **XGBoost (+38.5% vs Logistic)** |
| **Test ROC-AUC** | `0.5000` | `0.8079` | **0.9421** | **XGBoost (+16.6% vs Logistic)** |
| **Test PR-AUC** | `0.4286` | `0.6421` | **0.9185** | **XGBoost (+43.0% vs Logistic)** |
| **Brier Score (Loss)** | `0.4671` | `0.2315` | **0.0619** | **XGBoost (73.3% lower error)** |
| **Test Accuracy** | `0.4286` | `0.5714` | **0.9286** | **XGBoost (+62.5% vs Logistic)** |
| **Balanced Accuracy** | `0.5000` | `0.6250` | **0.9375** | **XGBoost (+50.0% vs Logistic)** |
| **Single-Row Latency (ms)** | `<0.01 ms` | `4.813 ms` | `5.274 ms` | All well within <10ms budget |
| **Batch Latency (42 rows)** | `0.036 ms` | `4.840 ms` | `5.188 ms` | ~0.12 ms per record in batch |

---

## 4. Confusion Matrices (Test Split: 42 Samples)

### Rule-Based Baseline
```
                  Predicted Negative    Predicted Positive
Actual Negative            0                    24           (TN=0,  FP=24)
Actual Positive            0                    18           (FN=0,  TP=18)
```
*Analysis: The rule baseline achieves 100% recall by essentially flagging almost every segment as flooded during rain, resulting in 24 false alarms.*

### Logistic Regression Baseline
```
                  Predicted Negative    Predicted Positive
Actual Negative            6                    18           (TN=6,  FP=18)
Actual Positive            0                    18           (FN=0,  TP=18)
```
*Analysis: Logistic Regression filters 6 true negatives, reducing false alarms from 24 to 18 while keeping recall at 1.000.*

### XGBoost Classifier
```
                  Predicted Negative    Predicted Positive
Actual Negative           21                     3           (TN=21, FP=3)
Actual Positive            0                    18           (FN=0,  TP=18)
```
*Analysis: XGBoost correctly identifies 21 of 24 dry scenarios, dropping false alarms by 83% (from 18 down to 3) while maintaining 100% detection of all 18 imminent flood occurrences.*

---

## 5. Scenario-Holdout Generalization Test

In this evaluation, models were trained exclusively on `NORMAL`, `MODERATE_RAIN`, `SEVERE_RAIN`, and `RECOVERY` scenarios and tested on the unseen `FLASH_FLOOD` scenario:

| Model | Holdout Precision | Holdout Recall | Holdout F1 | Holdout PR-AUC | Holdout ROC-AUC |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Rule-Based Baseline** | `0.3333` | `0.7692` | `0.4651` | `0.3397` | `0.4498` |
| **Logistic Regression** | **1.0000** | `0.2308` | `0.3750` | `0.6574` | `0.7525` |
| **XGBoost Classifier** | `0.6667` | **0.4615** | **0.5455** | **0.6682** | `0.7074` |

*Takeaway: XGBoost achieved the best balanced generalization (F1 = 0.5455) when confronted with an unseen flash-flood scenario, demonstrating superior non-linear transfer compared to linear and rule baselines.*

---

## 6. Feature Importance Comparison

### XGBoost Gain-Based Importances
1. `length_m` (`0.2512`): Road length controls accumulation runoff area.
2. `rainfall_accum_1h_mm` (`0.1665`): 1-hour precipitation volume dictates drainage saturation.
3. `nearby_sensor_count` (`0.1579`): Coverage density reflects telemetry confidence.
4. `hour_of_day` (`0.0968`): Diurnal storm progression cycle.
5. `water_depth_max_30m_cm` (`0.0775`): Antecedent peak water levels.

### Logistic Regression Standardized Coefficients
1. `hour_of_day` (`+2.1714`): Temporal trend correlation.
2. `rainfall_accum_15m_mm` (`+1.8480`): Fast precipitation onset.
3. `water_depth_trend_cm_per_min` (`-1.3804`): Water level velocity.
4. `nearby_sensor_count` (`+1.1027`): Sensor availability.
5. `length_m` (`-1.1027`): Segment geometry attribute.

---

## 7. Artifact Manifest

All artifacts are persisted in `ml/artifacts/`:

```
ml/artifacts/
├── comparison_report.json
├── baseline-v1/
│   ├── model.joblib
│   ├── metadata.json
│   ├── metrics.json
│   ├── threshold.json
│   └── feature_schema.json
├── logistic-v1/
│   ├── model.joblib
│   ├── metadata.json
│   ├── metrics.json
│   ├── threshold.json
│   ├── feature_schema.json
│   └── feature_importance.json
└── xgboost-v1/
    ├── model.joblib (SHA-256: 5f459d781b5ba2c36e2fbde5e103c78fe45533bac83c17dbe398131d4fba9fdf)
    ├── metadata.json
    ├── metrics.json
    ├── threshold.json
    ├── feature_schema.json
    └── feature_importance.json
```

---

## 8. Conclusion & Readiness for Phase 13

Phase 12 delivers a complete, reproducible offline model development and benchmarking engine. XGBoost has been quantitatively established as the leading candidate architecture with **0.9231 F1**, **1.000 Recall**, **0.8571 Precision**, and **5.27 ms inference latency**.

Phase 13 can now cleanly ingest `LoadedFloodModel` to incorporate predictive flood penalties into the Dijkstra and A* routing graph without modifying core algorithm structures.

