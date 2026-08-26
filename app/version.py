"""Single source of truth for the application version.

Consumed by the FastAPI app metadata, the desktop entry point, the PyInstaller
spec, the Windows installer script, and the release workflow's tag/version guard.
Main may carry the intended next version before a stable tag is cut.
"""

__version__ = "5.16.0"
