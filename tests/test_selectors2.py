from __future__ import with_statement
import errno
import os
import psutil
import platform
import mock
import select
import signal
import sys
import time
from .support import socketpair, AlarmMixin, TimerMixin

import selectors2

try:  # Python 2.6 unittest module doesn't have skip decorators.
    from unittest import skipIf, skipUnless
    import unittest
except ImportError:
    from unittest2 import skipIf, skipUnless
    import unittest2 as unittest

try:  # Python 2.x doesn't define time.perf_counter.
    from time import perf_counter as get_time
except ImportError:
    from time import time as get_time

try:  # Python 2.6 doesn't have the resource module.
    import resource
except ImportError:
    resource = None

HAS_ALARM = hasattr(signal, "alarm")

LONG_SELECT = 1.0
SHORT_SELECT = 0.01


skipUnlessHasSelector = skipUnless(hasattr(selectors2, 'SelectSelector'), "Platform doesn't have a selector")
skipUnlessHasENOSYS = skipUnless(hasattr(errno, 'ENOSYS'), "Platform doesn't have errno.ENOSYS")
skipUnlessHasAlarm = skipUnless(hasattr(signal, 'alarm'), "Platform doesn't have signal.alarm()")
skipUnlessJython = skipUnless(platform.system() == 'Java', "Platform is not Jython")
skipIfRetriesInterrupts = skipIf(sys.version_info >= (3, 5), "Platform retries interrupts")


def patch_select_module(testcase, *keep, **replace):
    """ Helper function that removes all selectors from the select module
    except those listed in *keep and **replace. Those in keep will be kept
    if they exist in the select module and those in replace will be patched
    with the value that is given regardless if they exist or not. Cleanup
    will restore previous state. This helper also resets the selectors module
    so that a call to DefaultSelector() will do feature detection again. """

    selectors2._DEFAULT_SELECTOR = None
    for s in ['select', 'poll', 'epoll', 'kqueue']:
        if s in replace:
            if hasattr(select, s):
                old_selector = getattr(select, s)
                testcase.addCleanup(setattr, select, s, old_selector)
            else:
                testcase.addCleanup(delattr, select, s)
            setattr(select, s, replace[s])
        elif s not in keep and hasattr(select, s):
            old_selector = getattr(select, s)
            testcase.addCleanup(setattr, select, s, old_selector)
            delattr(select, s)


@skipUnlessHasSelector
class _BaseSelectorTestCase(unittest.TestCase, AlarmMixin, TimerMixin):
    """ Implements the tests that each type of selector must pass. """

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
        s = selectors2.DefaultSelector()
        self.addCleanup(s.close)
        return s

    def standard_setup(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)
        s.register(wr, selectors2.EVENT_WRITE)
        return s, rd, wr


class _AllSelectorsTestCase(_BaseSelectorTestCase):
    def test_get_key(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        key = s.register(rd, selectors2.EVENT_READ, "data")
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
        key = s.register(rd, selectors2.EVENT_READ, "data")
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
        key = s.register(rd, selectors2.EVENT_READ, data)
        self.assertIsInstance(key, selectors2.SelectorKey)
        self.assertEqual(key.fileobj, rd)
        self.assertEqual(key.fd, rd.fileno())
        self.assertEqual(key.events, selectors2.EVENT_READ)
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
        self.assertRaises(ValueError, s.register, -1, selectors2.EVENT_READ)

    def test_register_invalid_fileobj(self):
        s = self.make_selector()
        self.assertRaises(ValueError, s.register, "string", selectors2.EVENT_READ)

    def test_reregister_fd_same_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd, selectors2.EVENT_READ)

    def test_reregister_fd_different_fileobj(self):
        s, rd, wr = self.standard_setup()
        self.assertRaises(KeyError, s.register, rd.fileno(), selectors2.EVENT_READ)

    def test_context_manager(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()

        with s as sel:
            rd_key = sel.register(rd, selectors2.EVENT_READ)
            wr_key = sel.register(wr, selectors2.EVENT_WRITE)
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
        s.register(rdfd, selectors2.EVENT_READ)
        s.register(wrfd, selectors2.EVENT_WRITE)

        rd.close()
        wr.close()

        s.unregister(rdfd)
        s.unregister(wrfd)

        self.assertEqual(0, len(s.get_map()))

    def test_unregister_after_fileobj_close(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)
        s.register(wr, selectors2.EVENT_WRITE)

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

        key = s.register(rd, selectors2.EVENT_READ)

        # Modify events
        key2 = s.modify(rd, selectors2.EVENT_WRITE)
        self.assertNotEqual(key.events, key2.events)
        self.assertEqual(key2, s.get_key(rd))

        s.unregister(rd)

        # Modify data
        d1 = object()
        d2 = object()

        key = s.register(rd, selectors2.EVENT_READ, d1)
        key2 = s.modify(rd, selectors2.EVENT_READ, d2)
        self.assertEqual(key.events, key2.events)
        self.assertIsNot(key.data, key2.data)
        self.assertEqual(key2, s.get_key(rd))
        self.assertIs(key2.data, d2)

        # Modify invalid fileobj
        self.assertRaises(KeyError, s.modify, 999999, selectors2.EVENT_READ)

    def test_empty_select(self):
        s = self.make_selector()
        self.assertEqual([], s.select(timeout=SHORT_SELECT))

    def test_select_multiple_event_types(self):
        s = self.make_selector()

        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors2.EVENT_READ | selectors2.EVENT_WRITE)

        self.assertEqual([(key, selectors2.EVENT_WRITE)], s.select(0.001))

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key, selectors2.EVENT_READ | selectors2.EVENT_WRITE)], s.select(0.001))

    def test_select_multiple_selectors(self):
        s1 = self.make_selector()
        s2 = self.make_selector()
        rd, wr = self.make_socketpair()
        key1 = s1.register(rd, selectors2.EVENT_READ)
        key2 = s2.register(rd, selectors2.EVENT_READ)

        wr.send(b'x')
        time.sleep(0.01)  # Wait for the write to flush.

        self.assertEqual([(key1, selectors2.EVENT_READ)], s1.select(timeout=0.001))
        self.assertEqual([(key2, selectors2.EVENT_READ)], s2.select(timeout=0.001))

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
            s.register(rd, selectors2.EVENT_READ)

        self.assertEqual(0, len(s.select(0.001)))

        # Write a byte to each end.
        for wr in writers:
            wr.send(b'x')

        # Give time to flush the writes.
        time.sleep(0.01)

        ready = s.select(0.001)
        self.assertEqual(32, len(ready))
        for key, events in ready:
            self.assertEqual(selectors2.EVENT_READ, events)
            self.assertIn(key.fileobj, readers)

        # Now read the byte from each endpoint.
        for rd in readers:
            data = rd.recv(1)
            self.assertEqual(b'x', data)

        self.assertEqual(0, len(s.select(0.001)))

    def test_select_timeout_none(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(wr, selectors2.EVENT_WRITE)

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
        s.register(rd, selectors2.EVENT_READ)

        with self.assertTakesTime(upper=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=0)))

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertEqual(0, len(s.select(timeout=SHORT_SELECT)))

    @skipUnlessHasAlarm
    def test_select_timing(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        key = s.register(rd, selectors2.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with self.assertTakesTime(upper=SHORT_SELECT):
            ready = s.select(LONG_SELECT)
        self.assertEqual([(key, selectors2.EVENT_READ)], ready)

    @skipUnlessHasAlarm
    def test_select_interrupt_no_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)

        self.set_alarm(SHORT_SELECT, lambda *args: None)

        with self.assertTakesTime(lower=LONG_SELECT, upper=LONG_SELECT):
            self.assertEqual([], s.select(LONG_SELECT))

    @skipUnlessHasAlarm
    def test_select_interrupt_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)
        key = s.get_key(rd)

        self.set_alarm(SHORT_SELECT, lambda *args: wr.send(b'x'))

        with self.assertTakesTime(lower=SHORT_SELECT, upper=SHORT_SELECT):
            self.assertEqual([(key, selectors2.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnlessHasAlarm
    def test_select_multiple_interrupts_with_event(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)
        key = s.get_key(rd)

        def second_alarm(*args):
            wr.send(b'x')

        def first_alarm(*args):
            self._begin_alarm_thread(SHORT_SELECT)
            signal.signal(signal.SIGALRM, second_alarm)

        self.set_alarm(SHORT_SELECT, first_alarm)

        with self.assertTakesTime(lower=SHORT_SELECT * 2, upper=SHORT_SELECT * 2):
            self.assertEqual([(key, selectors2.EVENT_READ)], s.select(LONG_SELECT))
        self.assertEqual(rd.recv(1), b'x')

    @skipUnlessHasAlarm
    def test_selector_error(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)

        def alarm_exception(*args):
            err = OSError()
            err.errno = errno.EACCES
            raise err

        self.set_alarm(SHORT_SELECT, alarm_exception)

        try:
            s.select(LONG_SELECT)
        except OSError as e:
            self.assertEqual(e.errno, errno.EACCES)
        except Exception as e:
            self.fail("Raised incorrect exception: " + str(e))
        else:
            self.fail("select() didn't raise OSError")

    # Test ensures that _syscall_wrapper properly raises the
    # exception that is raised from an interrupt handler.
    @skipUnlessHasAlarm
    def test_select_interrupt_exception(self):
        s = self.make_selector()
        rd, wr = self.make_socketpair()
        s.register(rd, selectors2.EVENT_READ)

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
            s.register(rd, selectors2.EVENT_READ)
            s.register(wr, selectors2.EVENT_WRITE)

        self.assertEqual(limit_nofile // 2, len(s.select()))


@skipUnlessHasSelector
class TestUniqueSelectScenarios(_BaseSelectorTestCase):
    def test_long_filenos_instead_of_int(self):
        # This test tries the module on objects that have 64bit filenos.
        selector = self.make_selector()
        big_fileno = 2 ** 64
        
        mock_socket = mock.Mock()
        mock_socket.fileno.return_value = big_fileno
        
        selector.register(big_fileno, selectors2.EVENT_READ)
        selector.unregister(big_fileno)
        
        selector.register(mock_socket, selectors2.EVENT_READ)
        selector.unregister(mock_socket)
    
    def test_select_module_patched_after_import(self):
        # This test is to make sure that after import time
        # calling DefaultSelector() will still give a good
        # return value. This issue is caused by gevent, eventlet.

        # Now remove all selectors except `select.select`.
        patch_select_module(self, 'select')

        # Make sure that the selector returned only uses the selector available.
        selector = self.make_selector()
        self.assertIsInstance(selector, selectors2.SelectSelector)

    @skipUnlessHasENOSYS
    def test_select_module_defines_does_not_implement_poll(self):
        # This test is to make sure that if a platform defines
        # a selector as being available but does not actually
        # implement it.

        # Reset the _DEFAULT_SELECTOR value as if using for the first time.
        selectors2._DEFAULT_SELECTOR = None

        # Now we're going to patch in a bad `poll`.
        class BadPoll(object):
            def poll(self, timeout):
                raise OSError(errno.ENOSYS)

        # Remove all selectors except `select.select` and replace `select.poll`.
        patch_select_module(self, 'select', poll=BadPoll)

        selector = self.make_selector()
        self.assertIsInstance(selector, selectors2.SelectSelector)

    @skipUnlessHasENOSYS
    def test_select_module_defines_does_not_implement_epoll(self):
        # Same as above test except with `select.epoll`.

        # Reset the _DEFAULT_SELECTOR value as if using for the first time.
        selectors2._DEFAULT_SELECTOR = None

        # Now we're going to patch in a bad `epoll`.
        def bad_epoll(*args, **kwargs):
            raise OSError(errno.ENOSYS)

        # Remove all selectors except `select.select` and replace `select.epoll`.
        patch_select_module(self, 'select', epoll=bad_epoll)

        selector = self.make_selector()
        self.assertIsInstance(selector, selectors2.SelectSelector)
        
    @skipIfRetriesInterrupts
    def test_selector_raises_timeout_error_on_interrupt_over_time(self):
        selectors2._DEFAULT_SELECTOR = None

        mock_socket = mock.Mock()
        mock_socket.fileno.return_value = 1

        def slow_interrupting_select(*args, **kwargs):
            time.sleep(0.2)
            error = OSError()
            error.errno = errno.EINTR
            raise error

        patch_select_module(self, select=slow_interrupting_select)

        selector = self.make_selector()
        selector.register(mock_socket, selectors2.EVENT_READ)

        try:
            selector.select(timeout=0.1)
        except OSError as e:
            self.assertEqual(e.errno, errno.ETIMEDOUT)
        else:
            self.fail('Didn\'t raise an OSError')
        
    @skipIfRetriesInterrupts
    def test_timeout_is_recalculated_after_interrupt(self):
        selectors2._DEFAULT_SELECTOR = None

        mock_socket = mock.Mock()
        mock_socket.fileno.return_value = 1

        class InterruptingSelect(object):
            """ Helper object that imitates a select that interrupts
            after sleeping some time then returns a result. """
            def __init__(self):
                self.call_count = 0
                self.calls = []

            def select(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                self.call_count += 1
                if self.call_count == 1:
                    time.sleep(0.1)
                    error = OSError()
                    error.errno = errno.EINTR
                    raise error
                else:
                    return [1], [], []

        mock_select = InterruptingSelect()

        patch_select_module(self, select=mock_select.select)

        selector = self.make_selector()
        selector.register(mock_socket, selectors2.EVENT_READ)

        result = selector.select(timeout=1.0)

        # Make sure the mocked call actually completed correctly.
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0].fileobj, mock_socket)
        self.assertEqual(result[0][1], selectors2.EVENT_READ)

        # There should be two calls to the mock_select.select() function
        self.assertEqual(mock_select.call_count, 2)

        # Timeout should be less in the second call.
        # The structure of mock_select.calls is [(args, kwargs), (args, kwargs)] where
        # args is ([r], [w], [x], timeout).
        self.assertLess(mock_select.calls[1][0][3], mock_select.calls[0][0][3])


class TestSelectors2Module(unittest.TestCase):
    def test__all__has_correct_contents(self):
        for entry in dir(selectors2):
            if entry.endswith('Selector'):
                self.assertIn(entry, selectors2.__all__)

        for entry in selectors2.__all__:
            self.assertIn(entry, dir(selectors2))


@skipUnless(hasattr(selectors2, "SelectSelector"), "Platform doesn't have a SelectSelector")
class SelectSelectorTestCase(_AllSelectorsTestCase):
    def setUp(self):
        patch_select_module(self, 'select')


@skipUnless(hasattr(selectors2, "PollSelector"), "Platform doesn't have a PollSelector")
class PollSelectorTestCase(_AllSelectorsTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'poll')


@skipUnless(hasattr(selectors2, "EpollSelector"), "Platform doesn't have an EpollSelector")
class EpollSelectorTestCase(_AllSelectorsTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'epoll')


@skipUnless(hasattr(selectors2, "DevpollSelector"), "Platform doesn't have an DevpollSelector")
class DevpollSelectorTestCase(_AllSelectorsTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'devpoll')


@skipUnless(hasattr(selectors2, "KqueueSelector"), "Platform doesn't have a KqueueSelector")
class KqueueSelectorTestCase(_AllSelectorsTestCase, ScalableSelectorMixin):
    def setUp(self):
        patch_select_module(self, 'kqueue')


@skipUnlessJython
@skipUnless(hasattr(selectors2, "JythonSelectSelector"), "Platform doesn't have a SelectSelector")
class JythonSelectSelectorTestBase(_AllSelectorsTestCase):
    def setUp(self):
        patch_select_module(self, 'select')
