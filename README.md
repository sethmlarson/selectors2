# selectors2

[![Travis Build Status](https://img.shields.io/travis/SethMichaelLarson/selectors2/master.svg?style=flat-square)]()
[![AppVeyor Build Status](https://img.shields.io/appveyor/ci/SethMichaelLarson/selectors2/master.svg?style=flat-square)]()
[![Available on PyPI](https://img.shields.io/pypi/v/selectors2.svg?style=flat-square)]()

Drop-in replacement of the selectors module for Python 2.6+ that integrates PEP 475.

- Support for all major platforms. (Linux, Mac OS, Windows)
- Support many different selectors:
  - [`select.kqueue`](https://docs.python.org/3/library/select.html#select.kqueue) (BSD, Mac OS)
  - [`select.devpoll`](https://docs.python.org/3/library/select.html#select.devpoll) (Solaris)
  - [`select.epoll`](https://docs.python.org/3/library/select.html#select.epoll) (Linux 2.5.44+)
  - [`select.poll`](https://docs.python.org/3/library/select.html#select.poll) (Linux, Mac OS)
  - [`select.select`](https://docs.python.org/3/library/select.html#select.select) - (Linux, Mac OS, Windows)
- Support for PEP 475 (Retries syscalls on interrupt)

## About

This module was originally written by me for the [urllib3](https://github.com/shazow/urllib3) project (history in PR [#1001](https://github.com/shazow/urllib3/pull/1001)) but it was decided that it would be beneficial for everyone to have access to this work.

#### Can this module be used in place of [`selectors`](https://docs.python.org/3/library/selectors.html)?

Yes! This module is a 1-to-1 drop-in replacement for `selectors` and 
provides all selector types that would be available in `selectors` including
`DevpollSelector`, `KqueueSelector`, `EpollSelector`, `PollSelector`, and `SelectSelector`.

#### What is different between `selectors2` and `selectors34`?

This module is similar to `selectors34` in that it supports Python 2.6 - 3.3
but differs in that this module also implements [PEP 475](https://www.python.org/dev/peps/pep-0475/) for the backported selectors.
This allows similar behaviour between Python 3.5+ selectors and selectors from before PEP 475.
In `selectors34`, an interrupted system call would result in an incorrect return of no events, which
for some use cases is not an acceptable behavior.

#### What types of objects are supported?

At this current time `selectors2` only support the `SelectSelector` for Windows which cannot select on non-socket objects.
On Linux and Mac OS, both sockets and pipes are supported (some other types may be supported as well, such as fifos or special file devices).

#### What if I have to support a platform without [`select.select`](https://docs.python.org/3/library/select.html)?

There are a few platforms that don't have a selector available, notably 
Google AppEngine, but there are probably a lot more. If you must support these
platforms, one should check `selectors.HAS_SELECTOR` for a True value before
trying to use `selectors.DefaultSelector`.  Note this is not available for
`selectors` or `selectors34`.

#### Windows has IOCP, why don't you support it?

Yes, Windows has access to IOCP which is more performant than `SelectSelector` but
is also much harder to implement and requires the `win32` module to expose the interface.
This is something I would like in the future, feel free to send a PR! :)

## License

This module is dual-licensed under MIT and PSF License.

## Installation

`python -m pip install selectors2`

## Usage

```python
import sys
if sys.version_info > (3, 5):  # Python 3.5+
    import selectors
else:  # Python 2.6 - 3.4
    import selectors2 as selectors

# Use DefaultSelector, it picks the fastest
# selector available for your platform! :)
s = selectors.DefaultSelector()

import socket

# We're going to use Google as an example.
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(("www.google.com", 80))

# Register the file to be watched for write availibility.
s.register(sock, selectors.EVENT_WRITE)

# Give a timeout in seconds or no
# timeout to block until an event happens.
events = s.select(timeout=1.0)

# Loop over all events that happened.
for key, event in events:
    if event & selectors.EVENT_WRITE:
        key.fileobj.send(b'HEAD / HTTP/1.1\r\n\r\n')

# Change what event you're waiting for.
s.modify(sock, selectors.EVENT_READ)

# Timeout of None let's the selector wait as long as it needs to.
events = s.select(timeout=None)
for key, event in events:
    if event & selectors.EVENT_READ:
        data = key.fileobj.recv(4096)
        print(data)

# Stop watching the socket.
s.unregister(sock)
sock.close()
```
