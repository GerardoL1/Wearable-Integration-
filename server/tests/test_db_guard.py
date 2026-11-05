import os
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]


def run_import(**env: str) -> subprocess.CompletedProcess[str]:
    # A fresh Python, because conftest already set RECOVERY_DB for this one.
    clean = {k: v for k, v in os.environ.items() if k not in ("RECOVERY_DB", "CLAUDECODE")}
    return subprocess.run(
        [sys.executable, "-c", "import app.core.db"],
        cwd=SERVER,
        env={**clean, **env},
        capture_output=True,
        text=True,
    )


def test_claude_code_runs_cannot_open_the_real_database(tmp_path: Path) -> None:
    refused = run_import(CLAUDECODE="1")
    assert refused.returncode != 0
    assert "must not open server/platform.db" in refused.stderr

    # Naming the real file outright is refused too.
    named = run_import(CLAUDECODE="1", RECOVERY_DB=str(SERVER / "platform.db"))
    assert named.returncode != 0

    scratch = run_import(CLAUDECODE="1", RECOVERY_DB=str(tmp_path / "scratch.db"))
    assert scratch.returncode == 0, scratch.stderr
