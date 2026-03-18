from dataclasses import dataclass, field
from time import sleep
from typing import Callable, Any, Optional
import queue
import concurrent.futures

# Dispatch class that serialize access to BeamNG API, most of their classes are thread-safe but this is a simple precaution.
@dataclass
class EventMsg:
    fn: Callable[..., Any]
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    future: Optional[concurrent.futures.Future] = None

    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
            if self.future is not None:
                self.future.set_result(res)
            return res
        
        except Exception as e:
            if self.future is not None:
                self.future.set_exception(e)
            else:
                raise


class Dispatcher:
    def __init__(self, simulation_check):
        self.simulation_check = simulation_check
        self.dispatchqueue = queue.Queue(maxsize = 1000)

    def send(self, fn, *args, **kwargs):
        self.dispatchqueue.put(EventMsg(fn, args, kwargs))

    def send_sync(self, fn, *args, timeout: Optional[float] = None, **kwargs):
        # Blocking return that waits for results, use for retrival from beamng using the dispatcher
        fut = concurrent.futures.Future()
        self.dispatchqueue.put(EventMsg(fn, args, kwargs, future=fut))
        return fut.result(timeout=timeout)

    def run(self):
        while self.simulation_check():
            try:
                msg = self.dispatchqueue.get(timeout=0.005)
                try:
                    msg.run()
                finally:
                    self.dispatchqueue.task_done()
            except queue.Empty:
                continue