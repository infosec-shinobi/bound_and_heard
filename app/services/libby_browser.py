from pathlib import Path
import subprocess
import sys


class LibbyBrowserError(RuntimeError):
    """Raised when the local Libby browser session cannot be opened."""


def open_libby_browser_session(profile_dir: str, *, headless: bool = False) -> None:
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    try:
        command = [sys.executable, "-m", "app.services.libby_browser_worker", profile_dir]
        if headless:
            command.append("--headless")
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise LibbyBrowserError(str(exc)) from exc
