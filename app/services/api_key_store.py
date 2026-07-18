"""The app's one Anthropic credential — its shape rule, its storage, its client.

Configuring a key is four things at once: deciding what a key even looks like,
writing it to a file that must stay owner-only, swapping the process-wide
Anthropic client so the change lands without a restart, and asking Anthropic
whether the key actually works.  All four used to sit inline in the two route
handlers that trigger them, which left an HTTP layer owning a secrets file, a
module global and a network round trip.

Two names now cover the lot:

    save(api_key) -> bool   # validated, persisted, live; True if Anthropic answered
    clear()                 # forgotten; the client drops back to Local Intelligence

Depth is everything sitting behind them: the canonical ``sk-ant-`` shape rule,
the read-modify-write of a single ``.env`` line, the 0600 mode re-applied on
every write, the client hot-swap, and the heartbeat that stops a well-formed but
dead key from being reported as connected.  A caller hands over a string.

Failures surface as ``InvalidKeyError`` and ``KeyStorageError``.  This module
deliberately holds no HTTP status codes and no reader-facing copy: it is the
seam a route handler, a CLI or a first-run wizard can all sit on, and each
shapes its own answer from the same two outcomes.

The key itself is never logged, never returned and never folded into an
exception message — only the exception *type* of a failure is ever recorded.
"""

from __future__ import annotations

import logging
import os
import re
import stat

from app.paths import data_dir
from app.services.ai_service import claude_api_heartbeat, reinitialize_client

logger = logging.getLogger(__name__)

# The single .env line this module owns.  Callers never name it.
_ENV_KEY = "ANTHROPIC_API_KEY"

# Only accept the canonical Anthropic key format: sk-ant-<variant>-<chars>
# This guards against prompt injection via the key field and nonsense values.
_API_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,300}$")


class InvalidKeyError(ValueError):
    """The supplied string is not shaped like an Anthropic API key."""


class KeyStorageError(RuntimeError):
    """The credential file could not be written."""


def _update_env_file(key: str, value: str) -> None:
    """Write or overwrite a single KEY=value line in the local .env file.

    The file holds secrets (e.g. ANTHROPIC_API_KEY), so it's restricted to
    owner-only read/write (0600) on every write, including first creation —
    other local accounts on the machine can't read it even though it's
    plaintext, which is the standard mitigation for local secret files (same
    approach used by ~/.netrc, ~/.aws/credentials, etc). This is intentional,
    local-only storage: FolioOrb is a single-user, local-first app with no
    server-side secrets store, so the key never leaves the user's machine.

    The write is in place rather than write-temp-then-rename: a crash mid-write
    can truncate the file, and on first creation the mode is tightened just
    after the file appears rather than at open time. Both are long-standing
    behaviour, kept as-is here so this module is a move and not a rewrite.
    """
    env_path = data_dir() / ".env"
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    new_line = f"{key}={value}\n"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    replaced = False
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            replaced = True
            break

    if not replaced:
        # A hand-edited .env may not end in a newline. splitlines() can't tell us
        # that, so without this the appended line is concatenated onto the last
        # entry and both are destroyed.
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new_line)

    env_path.write_text("".join(lines), encoding="utf-8")
    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)


def save(api_key: str) -> bool:
    """Validate, persist and hot-swap the Anthropic key; report whether it works.

    Returns True only when Anthropic answered a live heartbeat using the new
    key.  A well-formed key can still be revoked, mistyped or unreachable, and
    reporting one of those as connected would tell the user AI is live while
    every panel quietly serves local fallbacks — so the reachability check is
    part of saving rather than a second call every caller has to remember.

    Raises InvalidKeyError before touching disk, and KeyStorageError if the
    write fails.  Neither carries the key.
    """
    key = (api_key or "").strip()

    # Reject anything that doesn't look like a real Anthropic key
    if not _API_KEY_RE.match(key):
        raise InvalidKeyError("API key is not in the canonical Anthropic format")

    try:
        _update_env_file(_ENV_KEY, key)
    except OSError as exc:
        logger.error("Failed to write API key to .env: %s", type(exc).__name__)
        raise KeyStorageError("Could not write the API key to disk") from exc

    # Swap the live client so AI endpoints work immediately (no restart needed)
    reinitialize_client(key)
    logger.info("Anthropic API key updated via dashboard (key not logged)")

    return bool(claude_api_heartbeat().get("live"))


def clear() -> None:
    """Forget the stored key and drop the live client back to Local Intelligence.

    The .env line is blanked rather than deleted so a later save() edits that
    same line instead of appending a second one.  The live client is only
    dropped once the file has agreed: a failed write raises KeyStorageError and
    leaves Claude connected, which is the honest state.
    """
    try:
        _update_env_file(_ENV_KEY, "")
    except OSError as exc:
        logger.error("Failed to clear API key in .env: %s", type(exc).__name__)
        raise KeyStorageError("Could not clear the API key on disk") from exc

    reinitialize_client("")
    logger.info("Anthropic API key removed via dashboard")
