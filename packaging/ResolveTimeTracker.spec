# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-Build-Spec fuer das eigenstaendige App-Bundle.

Nach dem Muster von node-toggle (siehe /Users/maximilianlamm/Code/node-toggle
/maxlamm_Node_Toggle.spec): dieselbe Kombination aus Homebrew-Python 3.13,
gebuendeltem Python-Dylib und Resolve-Scripting-API, dort als fertiges
Bundle bereits gegen ein echtes Resolve verifiziert.

DaVinciResolveScript wird bewusst NICHT gebuendelt -- resolve_probe.py haengt
den Modules-Ordner der beim Nutzer installierten Resolve-Kopie zur Laufzeit an
sys.path an (ensure_environment()), das funktioniert unveraendert auch im
gefrorenen Bundle.
"""

import os

# SPECPATH wird von PyInstaller vor dem exec() dieser Datei bereits ins
# Namespace injiziert (Verzeichnis dieser .spec-Datei) -- __file__ existiert
# hier nicht, da der Spec-Inhalt exec'd statt importiert wird.
SRC_DIR = os.path.join(SPECPATH, "..", "src")
ICON_PATH = os.path.join(SPECPATH, "icon.icns")

a = Analysis(
    [os.path.join(SPECPATH, "app_entry.py")],
    pathex=[SRC_DIR],
    binaries=[],
    datas=[],
    hiddenimports=[
        "rumps",
        "AppKit",
        "Foundation",
        "Quartz",
        "objc",
        "ServiceManagement",
        # keyring waehlt sein macOS-Backend ueber einen entry_points-Scan zur
        # Laufzeit aus (importlib.metadata), PyInstallers statische Analyse
        # findet das nicht von selbst -- ohne diese Zeile scheitert der
        # Token-Zugriff im Bundle erst beim Empfaenger.
        "keyring.backends.macOS",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ResolveTimeTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch="arm64",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ResolveTimeTracker",
)

app = BUNDLE(
    coll,
    name="Resolve Time Tracker.app",
    icon=ICON_PATH,
    bundle_identifier="com.monacoframe.resolve-time-tracker",
    info_plist={
        "CFBundleDisplayName": "Resolve Time Tracker",
        "CFBundleShortVersionString": "0.1.0",
        # Kein Dock-Icon, reine Menubar-App -- das war das eigentliche Problem
        # der alten Shell-Wrapper-App: exec ersetzte deren Programm-Image, das
        # Info.plist des eigenen Bundles wurde dadurch nie ausgewertet. Ein
        # PyInstaller-Bundle bleibt dagegen durchgehend derselbe Prozess.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
)
