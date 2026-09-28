"""Read-only clock capability; no shell, profile data or customer context."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from zylch.tools.base import Tool, ToolResult, ToolStatus


class CurrentTime(Tool):
    def __init__(self, *, trace=None):
        super().__init__(
            "get_current_time",
            "Read the current date and time in an explicit IANA timezone, e.g. "
            "Europe/Rome or UTC. Use for fresh current-time questions; previous "
            "results and prompt timestamps are historical, not the current clock.",
        )
        self.trace = trace

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {"timezone": {"type": "string", "maxLength": 128}},
                "required": ["timezone"],
                "additionalProperties": False,
            },
        }

    async def execute(self, validation_only=False, **kwargs):
        zone = kwargs.get("timezone")
        try:
            if set(kwargs) != {"timezone"} or not isinstance(zone, str) or len(zone) > 128:
                raise ValueError
            tz = ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            # Never echo an invalid argument (paths, instructions or credentials).
            result = ToolResult(ToolStatus.ERROR, None, error="A valid IANA timezone is required")
            if self.trace:
                self.trace.record("clock_result", result=None, error=result.error)
            return result
        if validation_only:
            return ToolResult(ToolStatus.SUCCESS, {"timezone": zone, "clock_read": False})
        if self.trace:
            self.trace.record("clock_started", arguments={"timezone": zone})
        now = datetime.now(timezone.utc).astimezone(tz)
        result = ToolResult(
            ToolStatus.SUCCESS,
            {
                "datetime": now.isoformat(timespec="seconds"),
                "timezone": zone,
                "utc_offset_seconds": int(now.utcoffset().total_seconds()),
                "source": "system_clock",
            },
        )
        if self.trace:
            self.trace.record("clock_result", result=result.data, error=None)
        return result
