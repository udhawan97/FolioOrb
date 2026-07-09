# PyInstaller build spec for FolioSenseAI (onedir desktop bundle).
#
#   pyinstaller packaging/pyinstaller/FolioSenseAI.spec
#
# Onedir (not onefile): faster startup, no temp self-extraction, fewer antivirus
# false positives. The DMG / Inno installer wraps the resulting folder so users
# never see it. Entry point is desktop/main.py (uvicorn + pywebview window).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent.parent  # packaging/pyinstaller -> repo root
sys.path.insert(0, str(ROOT))
from app.version import __version__  # noqa: E402

ICON_ICNS = str(ROOT / "packaging" / "icons" / "FolioSenseAI.icns")
ICON_ICO = str(ROOT / "packaging" / "icons" / "FolioSenseAI.ico")

# Bundled read-only resources (unpacked under sys._MEIPASS at runtime).
datas = [
    (str(ROOT / "static"), "static"),
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / ".env.example"), "."),
]
binaries = []
# curl_cffi ships a compiled backend + CA bundle that its dynamic imports load
# at runtime, so it needs a full collect_all; uvicorn resolves its protocol/loop
# implementations by name. yfinance is imported directly throughout app/, so the
# normal dependency graph already captures it — no collect_all needed there.
hiddenimports = ["_cffi_backend"]
hiddenimports += collect_submodules("uvicorn")
curl_datas, curl_binaries, curl_hidden = collect_all("curl_cffi")
datas += curl_datas
binaries += curl_binaries
hiddenimports += curl_hidden

# certifi's CA bundle (cacert.pem) MUST ship: the in-app updater points its TLS
# context at certifi.where() so HTTPS to GitHub verifies on the user's machine
# (the frozen OpenSSL's default cert path is a build-machine location that won't
# exist there). PyInstaller's built-in certifi hook usually collects it, but
# make it explicit so this can never silently regress and reintroduce the
# "always offline" bug.
datas += collect_data_files("certifi")
hiddenimports += ["certifi", "ssl"]

# Heavy packages that are not in requirements.txt and are never imported by this
# app, but can be present in a developer's ambient Python environment (e.g. from
# unrelated ML projects sharing the interpreter). Without an explicit exclude,
# PyInstaller's optional-dependency probing for numpy/pandas/scipy can pull them
# into the frozen bundle, ballooning it by hundreds of MB to gigabytes. CI builds
# from a clean requirements-only environment where this can't happen, but the
# exclude makes every build — local or CI — deterministic regardless of what
# else happens to be installed.
excludes = [
    "torch", "torchvision", "torchaudio",
    "tensorflow", "tensorboard",
    "onnxruntime",
    "scipy",
    "matplotlib",
    "IPython", "jupyter", "notebook",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
    "pytest", "sklearn",
]

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FolioSenseAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=(ICON_ICO if sys.platform == "win32" else ICON_ICNS),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FolioSenseAI",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FolioSenseAI.app",
        icon=ICON_ICNS,
        bundle_identifier="com.foliosenseai.app",
        version=__version__,
        info_plist={
            "CFBundleName": "FolioSenseAI",
            "CFBundleDisplayName": "FolioSenseAI",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
