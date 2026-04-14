"""Execute Python code in a subprocess (ported from solve_tools._run_python).

Preserves:
- sys.executable use (commit 29db46b) — the Python interpreter that shipped
  with zylch, so the script can import zylch deps.
- Temp script location OUTSIDE /tmp/zylch/ (commit 144df25) — otherwise the
  script file would leak into the output dir the user inspects.

This tool is destructive (arbitrary code execution), so it's in
APPROVAL_TOOLS and fires the approval gate in ChatService.
"""

import logging
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict

from .base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


class RunPythonTool(Tool):
    """Execute Python code with a 60s timeout in /tmp/zylch/."""

    def __init__(self):
        super().__init__(
            name="run_python",
            description=(
                "Execute Python code in a subprocess."
                " Use for: PDF processing, file manipulation,"
                " data transformation, calculations."
                " The user will review the code before execution."
                " Output files go to /tmp/zylch/."
            ),
        )

    async def execute(
        self,
        code: str = "",
        description: str = "",
        **kwargs,
    ) -> ToolResult:
        logger.debug(
            f"[run_python] execute(args={{'code_len': {len(code)},"
            f" 'description_len': {len(description)}}})"
        )

        if not code or not code.strip():
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error="No code provided",
            )
            logger.debug(f"[run_python] -> status={result.status}")
            return result

        output_dir = "/tmp/zylch"
        os.makedirs(output_dir, exist_ok=True)

        # Script temp file in /tmp (NOT /tmp/zylch) to avoid showing up
        # when user code scans the output directory. (commit 144df25)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".py",
            delete=False,
        ) as f:
            f.write(code)
            script_path = f.name

        try:
            # sys.executable ensures we use the venv Python. (commit 29db46b)
            python = sys.executable or "python3"
            proc = subprocess.run(
                [python, script_path],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=output_dir,
            )
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            returncode = int(proc.returncode)

            parts = []
            if stdout.strip():
                parts.append(stdout.strip())
            if stderr.strip():
                parts.append(f"STDERR:\n{stderr.strip()}")
            if returncode != 0:
                parts.append(f"Exit code: {returncode}")
            message = "\n".join(parts) if parts else "OK (no output)"

            status = (
                ToolStatus.SUCCESS
                if returncode == 0
                else ToolStatus.ERROR
            )
            result = ToolResult(
                status=status,
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                },
                message=message,
                error=(None if status == ToolStatus.SUCCESS else message),
            )
            logger.debug(
                f"[run_python] -> status={result.status}"
                f" rc={returncode}"
            )
            return result

        except subprocess.TimeoutExpired:
            result = ToolResult(
                status=ToolStatus.ERROR,
                data={
                    "stdout": "",
                    "stderr": "",
                    "returncode": -1,
                },
                error="Timed out (60s limit)",
            )
            logger.debug(f"[run_python] -> status={result.status} timeout")
            return result
        except Exception as e:
            logger.error(f"[run_python] failed: {e}")
            result = ToolResult(
                status=ToolStatus.ERROR,
                data=None,
                error=f"Execution failed: {e}",
            )
            logger.debug(f"[run_python] -> status={result.status}")
            return result
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Brief description of what the code does"
                        ),
                    },
                },
                "required": ["code", "description"],
            },
        }
