from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import time

class FaultAction(Enum):
    FAIL_ONCE = "fail_once"
    FAIL_N_TIMES = "fail_n_times"
    DELAY = "delay"
    TIMEOUT = "timeout"
    HTTP_500 = "http_500"
    HTTP_429 = "http_429"
    MALFORMED_RESPONSE = "malformed_response"
    DROP_CONNECTION = "drop_connection"
    UNAVAILABLE = "unavailable"

@dataclass
class FaultScenario:
    id: str
    target: str
    action: FaultAction
    exception: Optional[Exception] = None
    delay_s: float = 0.0
    n_times: int = 1
    custom_payload: Any = None
    
@dataclass
class FaultInjectionResult:
    scenario_id: str
    target: str
    success: bool
    detection_time_ms: float
    error_raised: bool
    error_type: Optional[str] = None
    degraded_behavior_observed: bool = False

@dataclass
class RecoveryResult:
    scenario_id: str
    recovered: bool
    recovery_time_ms: float
    data_loss: int = 0
    system_healthy: bool = True

@dataclass
class ExperimentReport:
    scenario_id: str
    target: str
    baseline_behavior: str
    fault_injected: str
    impact_observed: str
    recovery_behavior: str
    verification: str
    injection_result: FaultInjectionResult
    recovery_result: RecoveryResult
    labels: List[str] = field(default_factory=list)

