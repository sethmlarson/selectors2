from __future__ import with_statement
import errno
import os
import psutil
import signal
import socket
import sys
import time

import selectors2 as selectors
from support import (
    resource,
    get_time,
    socketpair,
    AlarmMixin,
    TimerMixin
)

try:  # Python 2.6 unittest module doesn't have skip decorators.
    from unittest import skip, skipIf, skipUnless
    import unittest
except ImportError:
    from unittest2 import skip, skipIf, skipUnless
    import unittest2 as unittest


HAS_ALARM = hasattr(signal, "alarm")
LONG_SELECT = 0.2
SHORT_SELECT = 0.01


@skipUnless(selectors.HAS_SELECT, "Platform doesn't have a selector")
class BaseSelectorTestCase(unittest.TestCase, AlarmMixin, TimerMixin):
    """ Implements the tests that each type of selector must pass. """
    SELECTOR = selectors.DefaultSelector

    def make_socketpair(self):
        rd, wr = socketpair()

        # Make non-blocking so we get errors if the
        # sockets are interacted with but not ready.
        rd.settimeout(0.0)
        wr.settimeout(0.0)

        self.addCleanup(rd.close)
        self.addCleanup(wr.close)
        return rd, wr

    def make_selector(self):
        s = self.SELECTOR()
        self.addCleanup(s.close)
        return s

    def standard_setup(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)
        return s, rd, wr

    def test_get_key(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors.EVENT_READ, "data")
        self.assertEqual(key, s.get_key(rd))

        # Unknown fileobj
        self.assertRaises(KeyError, s.get_key, 999999)

    def test_get_map(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        keys = s.get_map()
        self.assertFalse(keys)
        self.assertEqual(len(keys), 0)
        self.assertEqual(list(keys), [])
        key = s.register(rd, selectors.EVENT_READ, "data")
        self.assertIn(rd, keys)
        self.assertEqual(key, keys[rd])
        self.assertEqual(len(keys), 1)
        self.assertEqual(list(keys), [rd.fileno()])
        self.assertEqual(list(keys.values()), [key])

        # Unknown fileobj
        self.assertRaises(KeyError, keys.__getitem__, 999999)

        # Read-only mapping
        with self.assertRaises(TypeError):
            del keys[rd]

        # Doesn't define __setitem__
        with self.assertRaises(TypeError):
            keys[rd] = key

    def test_register(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        # Ensure that the file is not yet added.
        self.assertEqual(0, len(s.get_map()))
        self.assertRaises(KeyError, lambda: s.get_map()[rd.fileno()])
        self.assertRaises(KeyError, s.get_key, rd)
        self.assertEqual(None, s._key_from_fd(rd.fileno()))

        data = object()
        key = s.register(rd, selectors.EVENT_READ, data)
        self.assertIsInstance(key, selectors.SelectorKey)
        self.assertEqual(key.fileobj, rd)
        self.assertEqual(key.fd, rd.fileno())
        self.assertEqual(key.events, selectors.EVENT_READ)
        self.assertIs(key.data, data)
        self.assertEqual(1, len(s.get_map()))
        for fd in s.get_map():
            self.assertEqual(fd, rd.fileno())

    def test_register_bad_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        self.assertRaises(ValueError, s.register, rd, 99999)

    def test_register_negative_fd(self):
        s = self.make_selector()
        self.assertRaises(ValueError, s.register, -1, selectors.EVENT_READ)

    def test_register_invalid_fileobj(self):
        s = self.make_selector()
        self.assertRaises(ValueError, s.register, "string", selectors.EVENT_READ)

    def test_reregister_fd_same_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd, selectors.EVENT_READ)

    def test_reregister_fd_different_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd.fileno(), selectors.EVENT_READ)

    def test_context_manager(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        with s as sel:
            rd_key = sel.register(rd, selectors.EVENT_READ)
            wr_key = sel.register(wr, selectors.EVENT_WRITE)
            self.assertEqual(rd_key, sel.get_key(rd))
            self.assertEqual(wr_key, sel.get_key(wr))

        self.assertRaises(RuntimeError, s.get_key, rd)
        self.assertRaises(RuntimeError, s.get_key, wr)

    def test_unregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        self.assertRaises(KeyError, s.unregister, 99999)

    def test_reunregister(self):
        s, rd, wr = self.standard_setup()
        s.unregister(rd)

        self.assertRaises(KeyError, s.unregister, rd)

    def test_unregister_after_fd_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        rdfd = rd.fileno()
        wrfd = wr.fileno()
        s.register(rdfd, selectors.EVENT_READ)
        s.register(wrfd, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rdfd)
        s.unregister(wrfd)

        self.assertEqual(0, len(s.get_map()))

    def test_unregister_after_fileobj_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        s.register(wr, selectors.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rd)
        s.unregister(wr)

        self.assertEqual(0, len(s.get_map()))

    @skipUnless(os.name == "posix", "Platform doesn't support os.dup2")
    def test_unregister_after_reuse_fd(self):
        s, rd, wr = self.standard_setup()
        rdfd = rd.fileno()
        wrfd = wr.fileno()

        rd2, wr2 = self.make_socketpair()
        rd.close()
        wr.close()
        os.dup2(rd2.fileno(), rdfd)
        os.dup2(wr2.fileno(), wrfd)

        s.unregister(rdfd)
        s.unregister(wrfd)

        self.assertEqual(0, len(s.get_map()))

    def test_modify(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors.EVENT_READ)

        # Modify events
        key2 = s.modify(rd, selectors.EVENT_WRITE)
        self.assertNotEqual(key.events, key2.events)
        self.assertEqual(key2, s.get_key(rd))

        s.unregister(rd)

        # Modify data
        d1 = object()
        d2 = object()

        key = s.register(rd, selectors.EVENT_READ, d1)
        key2 = s.modify(rd, selectors.EVENT_READ, d2)
        self.assertEqual(key.events, key2.events)
        self.assertIsNot(key.data, key2.data)
        self.assertEqual(key2, s.get_key(rd))
        self.assertIs(key2.data, d2)

        # Modify invalid fileobj
        self.assertRaises(KeyError, s.modify, 999999, selectors.EVENT_READ)

    def test_empty_select(self):
        s = self.make_selector()
        self.assertEqual([], s.select(timeout=SHORT_SELECT))

    def test_select_multiple_event_types(self):
        s = self.make_selector()

        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ | selectors.EVENT_WRITE)

        self.assertEqual([(key, selectors.EVENT_WRITE)], s.select(0.001))

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key, selectors.EVENT_READ | selectors.EVENT_WRITE)], s.select(0.001))

    def test_select_multiple_selectors(self):
        s1 = self.make_selector()
        s2 = self.make_selector()
        rd, wr = self.make_socketpair()
        key1 = s1.register(rd, selectors.EVENT_READ)
        key2 = s2.register(rd, selectors.EVENT_READ)

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key1, selectors.EVENT_READ)], s1.select(timeout=0.001))
        self.assertEqual([(key2, selectors.EVENT_READ)], s2.select(timeout=0.001))

    def test_select_no_event_types(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        self.assertRaises(ValueError, s.register, rd, 0)

    def test_select_many_events(self):
        s = self.make_selector()
        readers = []
        writers = []
        for _ in range(32):
            rd, wr = self.make_socketpair()
            readers.append(rd)
            writers.append(wr)
            s.register(rd, selectors.EVENT_READ)

        self.assertEqual(0, len(s.select(0.001)))

        # Write a byte to each end.
        for wr in writers:
            wr.send(b'x')

        # Give time to flush the writes.
        time.sleep(0.01)

        ready = s.select(0.001)
        self.assertEqual(32, len(ready))
        for key, events in ready:
            self.assertEqual(selectors.EVENT_READ, events)
            self.assertIn(key.fileobj, readers)

        # Now read the byte from each endpoint.
        for rd in readers:
            data = rd.recv(1)
            self.assertEqual(b'x', data)

        self.assertEqual(0, len(s.select(0.001)))

    def test_select_timeout_none(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(wr, selectors.EVENT_WRITE)

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(1, len(s.select(timeout=None)))

    def test_select_timeout_ready(self):
        s, rd, wr = self.standard_setup()

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(1, len(s.select(timeout=0)))
            self.assertEqual(1, len(s.select(timeout=-1)))
            self.assertEqual(1, len(s.select(timeout=0.001)))

    def test_select_timeout_not_ready(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=0)))

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=SHORT_SELECT)))

    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_select_timing(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with self.assertTakesTime(upper=SHORT_SELECT):
            ready = s.select(LONG_SELECT)
        self.assertEqual([(key, selectors.EVENT_READ)], ready)

    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_select_interrupt_no_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: None)

        with self.assertTakesTime(lower=LONG_SELECT, upper=LONG_SELECT):
            self.assertEqual([], s.select(LONG_SELECT))

    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_select_interrupt_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertEqual([(key, selectors.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_select_multiple_interrupts_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)
        key = s.get_key(rd)

        def second_alarm(*args):
            wr.send(b'x')

        def first_alarm(*args):
            self._begin_alarm_thread(SHORT_SELECT)
            signal.signal(signal.SIGALRM, second_alarm)

        self.set_alarm(SHORT_SELECT, first_alarm)

        with self.assertTakesTime(lower=SHORT_SELECT * 2, upper=SHORT_SELECT * 2):
            self.assertEqual([(key, selectors.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_selector_error(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        def alarm_exception(*args):
            err = OSError()
            err.errno = errno.EACCES
            raise err

        self.set_alarm(SHORT_SELECT, alarm_exception)

        try:
            s.select(LONG_SELECT)
        except selectors.SelectorError as e:
            self.assertEqual(e.errno, errno.EACCES)
        except Exception as e:
            self.fail("Raised incorrect exception: " + str(e))
        else:
            self.fail("select() didn't raise SelectorError")

    # Test ensures that _syscall_wrapper properly raises the
    # exception that is raised from an interrupt handler.
    @skipUnless(HAS_ALARM, "Platform doesn't have signal.alarm()")
    def test_select_interrupt_exception(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors.EVENT_READ)

        class AlarmInterrupt(Exception):
            pass

        def alarm_exception(*args):
            raise AlarmInterrupt()

        self.set_alarm(SHORT_SELECT, alarm_exception)

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertRaises(AlarmInterrupt, s.select, LONG_SELECT)

    def test_fileno(self):
        s = self.make_selector()
        if hasattr(s, "fileno"):
            fd = s.fileno()
            self.assertTrue(isinstance(fd, int))
            self.assertGreaterEqual(fd, 0)
        else:
            self.skipTest("Selector doesn't implement fileno()")

    # According to the psutil docs, open_files() has strange behavior
    # on Windows including giving back incorrect results so to
    # stop random failures from occurring we're skipping on Windows.
    @skipIf(sys.platform == "win32", "psutil.Process.open_files() is unstable on Windows.")
    def test_leaking_fds(self):
        proc = psutil.Process()
        before_fds = len(proc.open_files())
        s = self.make_selector()
        s.close()
        after_fds = len(proc.open_files())
        self.assertEqual(before_fds, after_fds)


class ScalableSelectorMixin(object):
    """ Mixin to test selectors that allow more fds than FD_SETSIZE """
    @skipUnless(resource, "Could not import the resource module")
    def test_above_fd_setsize(self):
        # A scalable implementation should have no problem with more than
        # FD_SETSIZE file descriptors. Since we don't know the value, we just
        # try to set the soft RLIMIT_NOFILE to the hard RLIMIT_NOFILE ceiling.
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard == resource.RLIM_INFINITY:
            self.skipTest("RLIMIT_NOFILE is infinite")

        try:  # If we're on a *BSD system, the limit tag is different.
            _, bsd_hard = resource.getrlimit(resource.RLIMIT_OFILE)
            if bsd_hard == resource.RLIM_INFINITY:
                self.skipTest("RLIMIT_OFILE is infinite")
            if bsd_hard < hard:
                hard = bsd_hard

        # NOTE: AttributeError resource.RLIMIT_OFILE is not defined on Mac OS.
        except (OSError, resource.error, AttributeError):
            pass

        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
            self.addCleanup(resource.setrlimit, resource.RLIMIT_NOFILE,
                            (soft, hard))
            limit_nofile = min(hard, 2 ** 16)
        except (OSError, ValueError):
            limit_nofile = soft

        # Guard against already allocated FDs
        limit_nofile -= 256
        limit_nofile = max(0, limit_nofile)

        s = self.make_selector()

        for i in range(limit_nofile // 2):
            rd, wr = self.make_socketpair()
            s.register(rd, selectors.EVENT_READ)
            s.register(wr, selectors.EVENT_WRITE)

        self.assertEqual(limit_nofile // 2, len(s.select()))


@skipUnless(hasattr(selectors, "SelectSelector"), "Platform doesn't have a SelectSelector")
class SelectSelectorTestCase(BaseSelectorTestCase):
    SELECTOR = getattr(selectors, "SelectSelector", None)


@skipUnless(hasattr(selectors, "PollSelector"), "Platform doesn't have a PollSelector")
class PollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "PollSelector", None)


@skipUnless(hasattr(selectors, "EpollSelector"), "Platform doesn't have an EpollSelector")
class EpollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "EpollSelector", None)


@skipUnless(hasattr(selectors, "KqueueSelector"), "Platform doesn't have a KqueueSelector")
class KqueueSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "KqueueSelector", None)


@skipUnless(hasattr(selectors, "DevpollSelector"), "Platform doesn't have a DevpollSelector")
class DevpollSelectorTestCase(BaseSelectorTestCase, ScalableSelectorMixin):
    SELECTOR = getattr(selectors, "DevpollSelector", None)
