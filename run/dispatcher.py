from dataclasses import dataclass, field
from typing import Callable, Any, Optional
import queue
import concurrent.futures
import const
import traceback

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

    def send_sync(self, fn, *args, timeout: float = 120.0, **kwargs):
        fut = concurrent.futures.Future()
        self.dispatchqueue.put(EventMsg(fn, args, kwargs, future=fut))
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            func_name = getattr(fn, '__name__', str(fn))
            print("[Dispatcher Error] send_sync call traceback (most recent call last):")
            print("".join(traceback.format_stack()[:-1]))
            raise TimeoutError(f"Dispatcher command '{func_name}' timed out.") from e

    def run(self):
        while self.simulation_check():
            try:
                msg = self.dispatchqueue.get(timeout=0.005)
                try:
                    msg.run()
                except Exception as e:
                    print(f"Dispatcher task failed: {e}")
                    traceback.print_exc()
                finally:
                    self.dispatchqueue.task_done()
            except queue.Empty:
                continue

    def clear(self):
        while not self.dispatchqueue.empty():
            try:
                msg = self.dispatchqueue.get_nowait()
                if hasattr(msg, "future") and msg.future is not None:
                    msg.future.set_exception(RuntimeError("Task cancelled during cleanup"))
                self.dispatchqueue.task_done()
            except queue.Empty:
                break