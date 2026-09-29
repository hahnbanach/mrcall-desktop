"""Execute Python code — thin Tool wrapper over `zylch.tools.python_exec`.

Destructive (arbitrary code execution), so it is in APPROVAL_TOOLS and
fires the approval gate in ChatService; on a hosted engine it is refused
outright (see python_exec).
"""

import logging
from typing import Any, Dict

from .base import Tool, ToolResult, ToolStatus
from .python_exec import run_python_code

logger = logging.getLogger(__name__)


class RunPythonTool(Tool):
    """Execute Python code with a 60s timeout in the scratch folder."""

    def __init__(self):
        super().__init__(
            name="run_python",
            description=(
                "Execute Python code in a subprocess."
                " Use for: PDF processing, file manipulation,"
                " data transformation, calculations."
                " The user will review the code before execution."
                " Output files go to the scratch folder."
            ),
        )

    async def execute(self, code: str = "", description: str = "", **kwargs) -> ToolResult:
        logger.debug(
            f"[run_python] execute(args={{'code_len': {len(code)},"
            f" 'description_len': {len(description)}}})"
        )
        run = run_python_code(code)
        message = run.summary()
        status = ToolStatus.SUCCESS if run.ok else ToolStatus.ERROR
        result = ToolResult(
            status=status,
            data=(
                {"stdout": run.stdout, "stderr": run.stderr, "returncode": run.returncode}
                if run.error != "No code provided"
                else None
            ),
            message=message,
            error=None if run.ok else message,
        )
        logger.debug(f"[run_python] -> status={result.status} rc={run.returncode}")
        return result

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
                        "description": ("Brief description of what the code does"),
                    },
                },
                "required": ["code", "description"],
            },
        }
