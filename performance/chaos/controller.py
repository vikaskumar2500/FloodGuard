from typing import Dict, Any, Optional
import asyncio
from performance.chaos.models import FaultScenario, FaultAction

class ChaosController:
    """Central registry and controller for fault injection."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.active_faults = {}
            cls._instance.enabled = False
        return cls._instance
        
    def enable(self):
        self.enabled = True
        
    def disable(self):
        self.enabled = False
        self.active_faults.clear()
        
    def inject(self, scenario: FaultScenario):
        if not self.enabled:
            return
        self.active_faults[scenario.target] = scenario
        
    def restore(self, target: str):
        if target in self.active_faults:
            del self.active_faults[target]
            
    async def maybe_fault(self, target: str) -> Any:
        """Called by mocked infrastructure to potentially trigger a fault."""
        if not self.enabled or target not in self.active_faults:
            return None
            
        scenario = self.active_faults[target]
        
        if scenario.action == FaultAction.UNAVAILABLE:
            raise scenario.exception or Exception(f"Dependency {target} is unavailable (Chaos)")
            
        elif scenario.action == FaultAction.FAIL_ONCE:
            self.restore(target)
            raise scenario.exception or Exception(f"Transient failure on {target} (Chaos)")
            
        elif scenario.action == FaultAction.FAIL_N_TIMES:
            scenario.n_times -= 1
            if scenario.n_times <= 0:
                self.restore(target)
            raise scenario.exception or Exception(f"Counted failure on {target} (Chaos)")
            
        elif scenario.action == FaultAction.DELAY:
            await asyncio.sleep(scenario.delay_s)
            
        elif scenario.action == FaultAction.TIMEOUT:
            await asyncio.sleep(scenario.delay_s or 0.1)
            raise TimeoutError(f"Timeout on {target} (Chaos)")
            
        elif scenario.action == FaultAction.MALFORMED_RESPONSE:
            return scenario.custom_payload
            
        return None

def get_chaos_controller() -> ChaosController:
    return ChaosController()

