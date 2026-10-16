from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .registry import ActiveRouteRegistry

RouteMode = Literal["FASTEST", "BALANCED", "SAFEST"]


@dataclass(frozen=True)
class RerouteDecision:
    should_reroute: bool
    reason: str
    unsafe_latched: bool

    def __getitem__(self, key: str) -> bool | str:
        return getattr(self, key)


class RouteImpactDetector:
    def __init__(self, registry: ActiveRouteRegistry) -> None:
        self.registry = registry

    def detect_affected_routes(
        self, affected_edge_ids: set[str], *, threshold: float = 0.3
    ) -> set[str]:
        del threshold
        return {
            route_id
            for route_id in self.registry.routes_using_edges(affected_edge_ids)
            if self.registry.get(route_id) is not None
        }


class RouteReroutingService:
    """Central mode policy. Risk values use the normalized 0..1 scale."""

    def __init__(
        self,
        *,
        risk_change_threshold: float | None = None,
        reroute_improvement_threshold: float = 0.1,
        unsafe_threshold: float = 0.7,
        recovery_threshold: float = 0.55,
        cooldown_seconds: float = 30.0,
        safest_eta_tradeoff: float = 0.5,
        balanced_cost_improvement: float = 0.1,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        del risk_change_threshold
        self.reroute_improvement_threshold = reroute_improvement_threshold
        self.unsafe_threshold = unsafe_threshold
        self.recovery_threshold = recovery_threshold
        self.cooldown_seconds = cooldown_seconds
        self.safest_eta_tradeoff = safest_eta_tradeoff
        self.balanced_cost_improvement = balanced_cost_improvement
        self.clock = clock or (lambda: datetime.now(UTC))

    def decide(
        self,
        *,
        mode: RouteMode = "SAFEST",
        current_risk: float,
        current_eta_s: float,
        candidate_risk: float,
        candidate_eta_s: float,
        affected_edge_ids: set[str],
        route_is_affected: bool,
        current_level: str,
        candidate_level: str,
        unsafe_latched: bool = False,
        last_rerouted_at: datetime | None = None,
    ) -> RerouteDecision:
        if not route_is_affected or not affected_edge_ids:
            return RerouteDecision(False, "not_affected", unsafe_latched)
        latched = (
            current_level in {"HIGH", "SEVERE"}
            or current_risk >= self.unsafe_threshold
            or (unsafe_latched and current_risk > self.recovery_threshold)
        )
        severe = current_level == "SEVERE"
        if (
            last_rerouted_at
            and not severe
            and (self.clock() - last_rerouted_at).total_seconds() < self.cooldown_seconds
        ):
            return RerouteDecision(False, "cooldown", latched)
        improvement = current_risk - candidate_risk
        eta_ratio = candidate_eta_s / max(current_eta_s, 0.001)
        safer = improvement >= self.reroute_improvement_threshold or severe
        if mode == "FASTEST":
            should = severe or (
                current_level == "HIGH"
                and candidate_level in {"LOW", "MODERATE"}
                and eta_ratio <= 1.1
            )
        elif mode == "BALANCED":
            old_cost = current_eta_s * (1 + current_risk)
            new_cost = candidate_eta_s * (1 + candidate_risk)
            should = (
                safer
                and (old_cost - new_cost) / max(old_cost, 0.001) >= self.balanced_cost_improvement
            )
        else:
            should = safer and latched and eta_ratio <= 1 + self.safest_eta_tradeoff
        return RerouteDecision(should, "route_unsafe" if should else "policy_rejected", latched)
