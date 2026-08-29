# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one-file, windowed (no console) MultiLinkManager.exe.

Build locally on Windows (only if PyInstaller is already installed --
see requirements-build.txt; do not install it just to run pytest):

    pip install -r requirements.txt -r requirements-build.txt
    pyinstaller packaging\\MultiLinkManager.spec --noconfirm

Produces ``dist\\MultiLinkManager.exe``. The same command (minus the
manual pip install step) is what ``.github/workflows/windows-build.yml``
runs on ``windows-latest`` to produce the downloadable build artifact.

Notes:
- ``console=False`` below means no console window ever appears -- this is
  a normal, unelevated, un-console'd desktop app. Steering (opt-in,
  off-by-default automatic failover) still requires the user to
  right-click -> "Run as administrator" *at launch time* if they want to
  use it; this spec does NOT request or embed any elevation manifest, so
  the exe launches as a normal user by default, exactly like running from
  source with ``python -m multilink_manager.app``.
- No extra ``datas``/hidden-import hooks beyond the explicit
  ``hiddenimports`` list below should be necessary: PySide6 ships its own
  PyInstaller hook (bundles required Qt plugins/DLLs automatically), and
  every ``multilink_manager`` submodule is reachable from
  ``run_multilink_manager.py`` via ``multilink_manager.app.main()``'s own
  imports. The explicit list is kept anyway as a safety net since some of
  those imports happen lazily inside function bodies rather than at
  module top-level (see ``app.py``'s docstring).
"""

from pathlib import Path

block_cipher = None
repo_root = Path(SPECPATH).resolve().parent  # noqa: F821 (SPECPATH is injected by PyInstaller)

HIDDEN_IMPORTS = [
    "multilink_manager",
    "multilink_manager.app",
    "multilink_manager.gui",
    "multilink_manager.gui.main_window",
    "multilink_manager.gui.worker",
    "multilink_manager.gui.charts",
    "multilink_manager.gui.theme",
    "multilink_manager.models",
    "multilink_manager.models.enums",
    "multilink_manager.models.interface",
    "multilink_manager.models.traffic",
    "multilink_manager.models.probe",
    "multilink_manager.models.connection",
    "multilink_manager.models.history",
    "multilink_manager.models.score",
    "multilink_manager.models.steering",
    "multilink_manager.networking",
    "multilink_manager.networking.interfaces",
    "multilink_manager.networking.probing",
    "multilink_manager.networking.routes",
    "multilink_manager.monitoring",
    "multilink_manager.monitoring.counters",
    "multilink_manager.monitoring.distribution",
    "multilink_manager.monitoring.connections",
    "multilink_manager.monitoring.selection",
    "multilink_manager.scoring",
    "multilink_manager.scoring.aggregation",
    "multilink_manager.scoring.scorer",
    "multilink_manager.steering",
    "multilink_manager.steering.policy",
    "multilink_manager.steering.controller",
    "multilink_manager.storage",
    "multilink_manager.storage.history_store",
    "multilink_manager.utils",
    "multilink_manager.utils.platform_utils",
    "multilink_manager.utils.logging_config",
]

a = Analysis(  # noqa: F821 (Analysis/PYZ/EXE are injected by PyInstaller when exec'ing this spec)
    [str(repo_root / "run_multilink_manager.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MultiLinkManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
