class RestartInterrupt(Exception):
    """Raised to instantly unwind the thread stack for a clean restart."""
    pass

class ShutdownInterrupt(Exception):
    """Raised to signal a thread to stop without treating it as an error."""
    pass

from functools import wraps
def interruptable(func):
    """Decorator that raises RestartInterrupt if the simulation is flagged to abort."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # Gracefully target the simulation object whether 'self' is the Simulation or Scheduler
        sim = getattr(self, "simulation", self)
        
        if hasattr(sim, "trial_invalid") and sim.trial_invalid.is_set():
            reason = getattr(sim, "abort_reason", "Unknown reason")
            raise RestartInterrupt(f"Aborted {func.__name__}: Restart signal set ({reason}).")
            
        return func(self, *args, **kwargs)
    return wrapper