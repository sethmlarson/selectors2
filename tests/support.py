import os
import signal
import socket
import threading
import time

__all__ = [
    "get_time",
    "resource",
    "socketpair",
    "AlarmMixin",
    "TimerMixin"
]

# Tolerance values for timer/speed fluctuations.
TOLERANCE = 0.5

# Detect whether we're running on Travis or AppVeyor.  This
# is used to skip some verification points inside of tests to
# not randomly fail our CI due to wild timer/speed differences.
TRAVIS_CI = "TRAVIS" in os.environ
APPVEYOR = "APPVEYOR" in os.environ

try:  # Python 2.x doesn't define time.perf_counter.
    from time import perf_counter as get_time
except ImportError:
    from time import time as get_time

try:  # Python 2.6 doesn't have the resource module.
    import resource
except ImportError:
    resource = None

if hasattr(socket, 'socketpair'):
    # Since Python 3.5, socket.socketpair() is now also available on Windows
    socketpair = socket.socketpair
else:
    # Replacement for socket.socketpair()
    def socketpair(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
        """A socket pair usable as a self-pipe, for Windows.
        Origin: https://gist.github.com/4325783, by Geert Jansen.
        Public domain.
        """
        if family == socket.AF_INET:
            host = '127.0.0.1'
        elif family == socket.AF_INET6:
            host = '::1'
        else:
            raise ValueError("Only AF_INET and AF_INET6 socket address "
                             "families are supported")
        if type != socket.SOCK_STREAM:
            raise ValueError("Only SOCK_STREAM socket type is supported")
        if proto != 0:
            raise ValueError("Only protocol zero is supported")

        # We create a connected TCP socket. Note the trick with setblocking(0)
        # that prevents us from having to create a thread.
        lsock = socket.socket(family, type, proto)
        try:
            lsock.bind((host, 0))
            lsock.listen(1)
            # On IPv6, ignore flow_info and scope_id
            addr, port = lsock.getsockname()[:2]
            csock = socket.socket(family, type, proto)
            try:
                csock.setblocking(False)
                try:
                    csock.connect((addr, port))
                except (OSError, socket.error):
                    pass
                csock.setblocking(True)
                ssock, _ = lsock.accept()
            except:
                csock.close()
                raise
        finally:
            lsock.close()
        return ssock, csock


class AlarmThread(threading.Thread):
    def __init__(self, timeout):
        super(AlarmThread, self).__init__(group=None)
        self.setDaemon(True)
        self.timeout = timeout
        self.canceled = False

    def cancel(self):
        self.canceled = True

    def run(self):
        time.sleep(self.timeout)
        if not self.canceled:
            os.kill(os.getpid(), signal.SIGALRM)


class AlarmMixin(object):
    alarm_thread = None

    def _begin_alarm_thread(self, timeout):
        if not hasattr(signal, "SIGALRM"):
            self.skipTest("Platform doesn't have signal.SIGALRM")
        self.addCleanup(self._cancel_alarm_thread)
        self.alarm_thread = AlarmThread(timeout)
        self.alarm_thread.start()

    def _cancel_alarm_thread(self):
        if self.alarm_thread is not None:
            self.alarm_thread.cancel()
            self.alarm_thread.join(0.0)
        self.alarm_thread = None

    def set_alarm(self, duration, handler):
        sigalrm_handler = signal.signal(signal.SIGALRM, handler)
        self.addCleanup(signal.signal, signal.SIGALRM, sigalrm_handler)
        self._begin_alarm_thread(duration)


class TimerContext(object):
    def __init__(self, testcase, lower=None, upper=None):
        self.testcase = testcase
        self.lower = lower
        self.upper = upper
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = get_time()

    def __exit__(self, *args, **kwargs):
        self.end_time = get_time()
        total_time = self.end_time - self.start_time

        # Skip timing on CI due to flakiness.
        if TRAVIS_CI or APPVEYOR:
            return

        if self.lower is not None:
            self.testcase.assertGreaterEqual(total_time, self.lower * (1.0 - TOLERANCE))
        if self.upper is not None:
            self.testcase.assertLessEqual(total_time, self.upper * (1.0 + TOLERANCE))


class TimerMixin(object):
    def assertTakesTime(self, lower=None, upper=None):
        return TimerContext(self, lower=lower, upper=upper)