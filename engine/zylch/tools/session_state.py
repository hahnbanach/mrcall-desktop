"""Shared session state for tool runtime context."""

from typing import Dict, Optional


class SessionState:
    """Shared session state that can be updated at runtime.

    This allows tools to access current values (like business_id, owner_id)
    that may change during the session (e.g., when user runs /mrcall <id>).

    Also manages task focus mode - when a user enters a task "virtualenv" to
    work on a specific task with dedicated orchestration.

    Also manages MrCall config mode - when a user enters `/mrcall open` to
    configure their MrCall assistant with dedicated orchestration.
    """

    def __init__(
        self,
        business_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ):
        self.business_id = business_id
        self.owner_id = owner_id
        # Task focus mode
        self.task_id: Optional[str] = None
        self.task_context: Optional[Dict] = None
        self.last_action_result: Optional[Dict] = None
        # MrCall config mode
        self.mrcall_config_mode: bool = False
        self.mrcall_config_business_id: Optional[str] = None
        # Sandbox mode (None = no sandbox, "mrcall" = MrCall Dashboard)
        self.sandbox_mode: Optional[str] = None

    def set_business_id(self, business_id: Optional[str]):
        """Update the current business ID."""
        self.business_id = business_id

    def get_business_id(self) -> Optional[str]:
        """Get the current business ID."""
        return self.business_id

    def set_owner_id(self, owner_id: Optional[str]):
        """Update the current owner ID."""
        self.owner_id = owner_id

    def get_owner_id(self) -> Optional[str]:
        """Get the current owner ID."""
        return self.owner_id

    # Task focus mode methods
    def enter_task_mode(self, task_id: str, task_data: Dict):
        """Enter task focus mode for a specific task.

        Args:
            task_id: UUID of the task to focus on
            task_data: Full task data from task_items table
        """
        self.task_id = task_id
        self.task_context = task_data
        self.last_action_result = None

    def exit_task_mode(self):
        """Exit task focus mode and return to normal chat."""
        self.task_id = None
        self.task_context = None
        self.last_action_result = None

    def is_task_mode(self) -> bool:
        """Check if currently in task focus mode."""
        return self.task_id is not None

    def get_task_id(self) -> Optional[str]:
        """Get the current task ID (None if not in task mode)."""
        return self.task_id

    def get_task_context(self) -> Optional[Dict]:
        """Get the current task context data."""
        return self.task_context

    def set_last_action_result(self, result: Dict):
        """Store the result of the last action for confirmation."""
        self.last_action_result = result

    def get_last_action_result(self) -> Optional[Dict]:
        """Get the result of the last action."""
        return self.last_action_result

    # MrCall config mode methods
    def enter_mrcall_config_mode(self, business_id: str):
        """Enter MrCall configuration mode for a specific assistant.

        Args:
            business_id: UUID of the MrCall assistant to configure
        """
        self.mrcall_config_mode = True
        self.mrcall_config_business_id = business_id
        # MrCall config mode and task mode are mutually exclusive
        self.exit_task_mode()

    def exit_mrcall_config_mode(self):
        """Exit MrCall configuration mode."""
        self.mrcall_config_mode = False
        self.mrcall_config_business_id = None

    def is_mrcall_config_mode(self) -> bool:
        """Check if currently in MrCall configuration mode."""
        return self.mrcall_config_mode

    def get_mrcall_config_business_id(self) -> Optional[str]:
        """Get the business ID for the current MrCall config session."""
        return self.mrcall_config_business_id
