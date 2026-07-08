"""Single source of truth for the application version.

Consumed by the FastAPI app metadata, the desktop entry point, the PyInstaller
spec, the Windows installer script, and the release workflow's tag/version guard.
Bump this one line when cutting a release.
"""

__version__ = "4.3.3"
