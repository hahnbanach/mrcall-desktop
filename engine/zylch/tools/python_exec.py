"""The one place model-written Python runs.

Both `RunPythonTool` and the solve executor's `run_python` call
`run_python_code`. On a hosted engine (`runtime.is_serving()`) it refuses:
the subprocess would inherit the daemon's environment (the profile `.env`
is loaded into it) and has no network or filesystem limit, so it is not a
sandbox. Locally it runs as before, in the scratch folder.
"""

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass

from zylch import runtime
from zylch.tools.paths import scratch_dir

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 60
HOSTED_REFUSAL = (
    "run_python is not available on a hosted engine. Read documents with"
    " read_document; other processing needs a local engine."
)


@dataclass
class PythonRun:
    stdout: str = ""
    stderr: str = ""
    returncode: int = -1
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.returncode == 0

    def summary(self) -> str:
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(f"STDERR:\n{self.stderr.strip()}")
        if self.error:
            parts.append(self.error)
        elif self.returncode != 0:
            parts.append(f"Exit code: {self.returncode}")
        return "\n".join(parts) if parts else "OK (no output)"


def run_python_code(code: str) -> PythonRun:
    if not code or not code.strip():
        return PythonRun(error="No code provided")
    if runtime.is_serving():
        logger.info("[run_python] refused: hosted engine")
        return PythonRun(error=HOSTED_REFUSAL)

    output_dir = scratch_dir()
    # The script lives outside the scratch dir so it does not show up when
    # the user's code lists its own output folder.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        script_path = f.name
    try:
        python = sys.executable or "python3"
        proc = subprocess.run(
            [python, script_path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            cwd=output_dir,
            check=False,
        )
        return PythonRun(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=int(proc.returncode),
        )
    except subprocess.TimeoutExpired:
        return PythonRun(error=f"Timed out ({TIMEOUT_SECONDS}s limit)")
    except (OSError, ValueError) as e:
        logger.error(f"[run_python] failed: {e}")
        return PythonRun(error=f"Execution failed: {e}")
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
