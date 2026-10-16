"""Risk Fusion Layer combining deterministic physical assessments with ML predictions.

Enforces CRITICAL INVARIANT 1:
ML can never reduce a stronger deterministic safety assessment:
R_fused >= R_deterministic
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.core.config import Settings
from app.ml.models import MLFloodPrediction
from app.risk.config import RiskConfig
from app.risk.models import EdgeRiskAssessment
from app.risk.normalization import clamp01
from app.risk.scoring import risk_level


@dataclass(frozen=True)
class FusedRiskAssessment(EdgeRiskAssessment):
    """Fused edge risk assessment extending deterministic assessment with ML telemetry."""

    deterministic_risk_score: float = 0.0
    deterministic_risk_level: str = "LOW"
    ml_probability: float | None = None
    ml_prediction_active: bool = False
    fused_risk_score: float = 0.0
    fused_risk_level: str = "LOW"
    model_version: str | None = None
    feature_version: str | None = None


class RiskFusionService:
    """Combines deterministic risk assessments with ML predictions according to configured mode."""

    def __init__(
        self,
        risk_weight: float | None = None,
        config: RiskConfig | None = None,
        settings: Settings | None = None,
    ) -> None:
        if settings is not None and risk_weight is None:
            risk_weight = settings.ml_risk_weight
        self.risk_weight = clamp01(risk_weight if risk_weight is not None else 0.35)
        self.config = config or RiskConfig()
        self.settings = settings

    def fuse_edge(
        self,
        deterministic: EdgeRiskAssessment,
        ml_prediction: MLFloodPrediction | None,
        mode: Literal["DISABLED", "SHADOW", "ACTIVE"] = "SHADOW",
    ) -> FusedRiskAssessment:
        """Fuse single edge assessment with ML prediction.

        Formula (ACTIVE mode):
        R_fused = max(R_det, (1 - alpha) * R_det + alpha * P_ml)
        Guarantees R_fused >= R_det at all times.
        """
        r_det = deterministic.risk_score
        lvl_det = deterministic.risk_level

        # Case 1: ML DISABLED or no ML prediction available
        if mode == "DISABLED" or ml_prediction is None:
            return FusedRiskAssessment(
                edge_id=deterministic.edge_id,
                risk_score=r_det,
                risk_level=lvl_det,
                confidence=deterministic.confidence,
                flood_zone_score=deterministic.flood_zone_score,
                water_depth_score=deterministic.water_depth_score,
                rainfall_score=deterministic.rainfall_score,
                prediction_score=deterministic.prediction_score,
                incident_score=deterministic.incident_score,
                evidence_age_seconds=deterministic.evidence_age_seconds,
                explanation=deterministic.explanation,
                high_risk_distance_m=deterministic.high_risk_distance_m,
                deterministic_risk_score=r_det,
                deterministic_risk_level=lvl_det,
                ml_probability=None,
                ml_prediction_active=False,
                fused_risk_score=r_det,
                fused_risk_level=lvl_det,
                model_version=None,
                feature_version=None,
            )

        p_ml = ml_prediction.probability
        m_version = ml_prediction.model_version
        f_version = ml_prediction.feature_version

        # Case 2: SHADOW mode (predictions logged/reported, but routing cost uses R_det)
        if mode == "SHADOW":
            shadow_explanation = deterministic.explanation
            if p_ml >= 0.5:
                shadow_explanation += (
                    f" ML model predicts {int(p_ml * 100)}% probability of HIGH/SEVERE flood "
                    f"within 30m (SHADOW mode: routing unaffected)."
                )
            return FusedRiskAssessment(
                edge_id=deterministic.edge_id,
                risk_score=r_det,
                risk_level=lvl_det,
                confidence=deterministic.confidence,
                flood_zone_score=deterministic.flood_zone_score,
                water_depth_score=deterministic.water_depth_score,
                rainfall_score=deterministic.rainfall_score,
                prediction_score=deterministic.prediction_score,
                incident_score=deterministic.incident_score,
                evidence_age_seconds=deterministic.evidence_age_seconds,
                explanation=shadow_explanation,
                high_risk_distance_m=deterministic.high_risk_distance_m,
                deterministic_risk_score=r_det,
                deterministic_risk_level=lvl_det,
                ml_probability=round(p_ml, 4),
                ml_prediction_active=False,
                fused_risk_score=r_det,
                fused_risk_level=lvl_det,
                model_version=m_version,
                feature_version=f_version,
            )

        # Case 3: ACTIVE mode (ML influences edge risk)
        # Conservative fusion formula: R_fused = max(R_det, (1 - alpha) * R_det + alpha * P_ml)
        alpha = self.risk_weight
        blended = (1.0 - alpha) * r_det + alpha * p_ml
        r_fused = clamp01(max(r_det, blended))
        lvl_fused = risk_level(r_fused, self.config)

        # Critical Deterministic Evidence Override:
        # If deterministic assessment has critical observations, ML can NEVER downgrade level
        has_critical_evidence = (
            deterministic.water_depth_score >= 0.75
            or deterministic.flood_zone_score >= 0.75
            or deterministic.incident_score >= 0.75
            or r_det >= 0.75
            or lvl_det in ("HIGH", "SEVERE")
        )
        if has_critical_evidence:
            r_fused = max(r_fused, r_det)
            # Ensure level floor
            if lvl_det == "SEVERE":
                lvl_fused = "SEVERE"
            elif lvl_det == "HIGH" and lvl_fused in ("LOW", "MODERATE"):
                lvl_fused = "HIGH"

        # Formulate clear explainability text
        explanation = deterministic.explanation
        if r_fused > r_det:
            explanation += (
                f" ML model predicts {int(p_ml * 100)}% probability of HIGH/SEVERE flood "
                f"within 30m, increasing risk from {r_det:.2f} to {r_fused:.2f}."
            )
        elif has_critical_evidence and p_ml < r_det:
            explanation += (
                f" Final risk remains {lvl_fused} because critical observed evidence "
                f"overrides lower model prediction ({int(p_ml * 100)}%)."
            )

        # Low deterministic confidence notice
        if deterministic.confidence < 0.30 and p_ml >= 0.50:
            explanation += " (Prediction primarily model-derived; direct observations are limited.)"

        conf = max(
            deterministic.confidence,
            0.5 if p_ml >= 0.5 else deterministic.confidence,
        )

        return FusedRiskAssessment(
            edge_id=deterministic.edge_id,
            risk_score=round(r_fused, 4),
            risk_level=lvl_fused,
            confidence=conf,
            flood_zone_score=deterministic.flood_zone_score,
            water_depth_score=deterministic.water_depth_score,
            rainfall_score=deterministic.rainfall_score,
            prediction_score=max(deterministic.prediction_score, round(p_ml, 4)),
            incident_score=deterministic.incident_score,
            evidence_age_seconds=deterministic.evidence_age_seconds,
            explanation=explanation,
            high_risk_distance_m=deterministic.high_risk_distance_m if r_fused >= 0.5 else 0.0,
            deterministic_risk_score=r_det,
            deterministic_risk_level=lvl_det,
            ml_probability=round(p_ml, 4),
            ml_prediction_active=True,
            fused_risk_score=round(r_fused, 4),
            fused_risk_level=lvl_fused,
            model_version=m_version,
            feature_version=f_version,
        )

    def fuse_assessments(
        self,
        assessments: dict[UUID, EdgeRiskAssessment],
        predictions: dict[UUID, MLFloodPrediction],
        mode: Literal["DISABLED", "SHADOW", "ACTIVE"] = "SHADOW",
    ) -> dict[UUID, FusedRiskAssessment]:
        """Fuse all edge assessments with ML predictions."""
        return {
            edge_id: self.fuse_edge(
                deterministic=assessment,
                ml_prediction=predictions.get(edge_id),
                mode=mode,
            )
            for edge_id, assessment in assessments.items()
        }
