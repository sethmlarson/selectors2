Changelog
=========

Release 2.0.0 (May 26, 2017)
----------------------------

* [FEATURE] Add support for Jython with ``JythonSelectSelector``
* [CHANGE] Raises a ``RuntimeError`` instead of ``ValueError`` if there is no selector available.
* [BUGFIX] Detect defects in a system that defines a selector but fails on usage.
* [BUGFIX] Can now detect a change in the ``select`` module post-import such as when
  ``gevent.monkey.monkey_patch()`` is called before importing ``selectors2``.

Release 1.1.1 (February 6, 2017)
--------------------------------

* [BUGFIX] Platforms that define ``select.kqueue`` would not have ``KqueueSelector`` as the ``DefaultSelector``.

Release 1.1.0 (January 17, 2017)
--------------------------------

* [FEATURE] Make system calls faster for Python versions that support PEP 475.
* [FEATURE] Wheels are now universal.

Release 1.0.0 (November 3, 2016)
--------------------------------

* Initial implementation of ``selectors2``.
