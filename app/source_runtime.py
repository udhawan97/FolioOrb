"""Check the source interpreter before installing packages or opening a profile."""
import sys


def require_source_python():
    """Refuse an unsupported interpreter before importing runtime dependencies."""
    if sys.version_info < (3, 11, 5):
        version = ".".join(str(part) for part in sys.version_info[:3])
        raise SystemExit(
            f"FolioOrb requires Python 3.11.5 or newer. Found {version} at {sys.executable}. "
            "Install a supported Python. If reusing a venv, rename that folder to an "
            "unused backup name and rerun setup. Keep your data directory in place."
        )


if __name__ == "__main__":
    require_source_python()
