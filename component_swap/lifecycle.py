"""POSIX cooperative parent cancellation, including the Popen handle gap."""
import signal
import threading
from contextlib import contextmanager

class Cancelled(BaseException):
    """An operator cancelled trusted adapter execution."""
    def __init__(self, signum):
        self.signum = signum

@contextmanager
def cancellation():
    if threading.current_thread() is not threading.main_thread():
        raise ValueError('Adapter execution requires the main thread for cancellation cleanup.')
    state = {'spawning': False, 'signal': None, 'cleaning': False}
    def handler(signum, frame):
        if state['signal'] is None:
            state['signal'] = signum
        if not state['spawning'] and not state['cleaning']:
            state['cleaning'] = True
            raise Cancelled(signum)
    previous = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    completed = False
    try:
        for s in previous:
            signal.signal(s, handler)
        yield state
        completed = True
    finally:
        # Never interrupt restoration; do not replace an existing exception.
        state['cleaning'] = True
        for s, old in previous.items():
            signal.signal(s, old)
        if completed and state['signal'] is not None:
            raise Cancelled(state['signal'])
