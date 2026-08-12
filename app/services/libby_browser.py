from pathlib import Path
import subprocess
import sys


class LibbyBrowserError(RuntimeError):
    """Raised when the local Libby browser session cannot be opened."""


def open_libby_browser_session(profile_dir: str) -> None:
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.services.libby_browser_worker", profile_dir],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise LibbyBrowserError(str(exc)) from exc
