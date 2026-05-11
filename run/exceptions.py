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

        # Check for shutdown signals first to allow for graceful exits      
        scheduler = getattr(sim, "event_scheduler", None)
        tick = getattr(scheduler, "tick", None) if scheduler is not None else None
        if tick is not None and getattr(tick, "shutdown", None) and tick.shutdown.is_set():
            raise ShutdownInterrupt("Shutdown signal received.")

        vehicle_tick = getattr(scheduler, "vehicle_update_tick", None) if scheduler is not None else None
        if vehicle_tick is not None and getattr(vehicle_tick, "shutdown", None) and vehicle_tick.shutdown.is_set():
            raise ShutdownInterrupt("Shutdown signal received.")
        
        # Check for trial invalidation to trigger a restart
        trial_invalid = getattr(sim, "trial_invalid", None)
        if trial_invalid is not None and trial_invalid.is_set():
            reason = getattr(sim, "abort_reason", "Unknown reason")
            raise RestartInterrupt(f"Aborted {func.__name__}: Restart signal set ({reason}).")

        return func(self, *args, **kwargs)
    return wrapper