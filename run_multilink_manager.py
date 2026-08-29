"""Thin PyInstaller entry point for the one-file Windows build.

PyInstaller's ``Analysis`` step wants a plain script to start from rather
than a ``python -m package`` invocation; this file exists purely so the
packaging spec (``packaging/MultiLinkManager.spec``) has one, and simply
delegates immediately to the real, tested entry point in
``multilink_manager.app.main()`` -- no logic lives here.

This is NOT used for normal development/test runs (``python -m
multilink_manager.app`` remains the documented way to run from source);
it exists only for the packaged ``.exe`` build. See README "Windows
executable (prebuilt build)" for how the resulting ``MultiLinkManager.exe``
behaves.
"""

from __future__ import annotations

import sys

from multilink_manager.app import main

if __name__ == "__main__":
    sys.exit(main())
