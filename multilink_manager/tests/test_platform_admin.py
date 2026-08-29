"""Tests for is_admin() Administrator-elevation detection. The real
ctypes.windll call does not exist off Windows, so the isolated
_windows_is_admin_impl() function is monkeypatched directly, mirroring
how is_windows()/run_powershell_json() are already monkeypatched
elsewhere in this test suite."""

from __future__ import annotations

import multilink_manager.utils.platform_utils as platform_mod
from multilink_manager.utils.platform_utils import is_admin


def test_is_admin_false_off_windows(monkeypatch):
    monkeypatch.setattr(platform_mod, "is_windows", lambda: False)
    assert is_admin() is False


def test_is_admin_true_when_elevated_on_windows(monkeypatch):
    monkeypatch.setattr(platform_mod, "is_windows", lambda: True)
    monkeypatch.setattr(platform_mod, "_windows_is_admin_impl", lambda: True)
    assert is_admin() is True


def test_is_admin_false_when_not_elevated_on_windows(monkeypatch):
    monkeypatch.setattr(platform_mod, "is_windows", lambda: True)
    monkeypatch.setattr(platform_mod, "_windows_is_admin_impl", lambda: False)
    assert is_admin() is False


def test_is_admin_fails_safe_closed_on_exception(monkeypatch):
    def _raise():
        raise OSError("boom")

    monkeypatch.setattr(platform_mod, "is_windows", lambda: True)
    monkeypatch.setattr(platform_mod, "_windows_is_admin_impl", _raise)
    assert is_admin() is False
