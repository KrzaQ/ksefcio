import os
from pathlib import Path

DEFAULT_BASENAME = "ksefcio-agent.sock"


def default_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / DEFAULT_BASENAME

    uid = os.getuid()
    candidate = Path(f"/run/user/{uid}")
    if candidate.is_dir():
        return candidate / DEFAULT_BASENAME

    fallback = Path(f"/tmp/ksefcio-{uid}")
    fallback.mkdir(mode=0o700, exist_ok=True)
    return fallback / DEFAULT_BASENAME
