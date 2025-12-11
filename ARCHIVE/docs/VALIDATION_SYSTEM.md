# Validation System (`--check` flag)

## Overview

The validation system provides semantic AI-powered validation for Zylch commands before execution. Users can preview what a command would do without actually executing it using the `--check` flag.

## Architecture

### API-First Design

All validation logic is in the service layer with **zero CLI dependencies**. The CLI is just one interface - the same validation logic can be called from:
- CLI commands
- REST API endpoints
- Tutorial sandbox mode
- Any future interface

### Components

```
┌─────────────────────────────────────────────────────┐
│                  User Interface                      │
│              (CLI / API / Tutorial)                  │
└────────────────────┬────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────┐
│            ValidationService                         │
│   • AI semantic analysis (Claude Haiku)             │
│   • Returns ValidationResult                         │
│   • Detects semantic issues                         │
└────────────────────┬────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────┐
│                 Tool Layer                           │
│   • execute(validation_only=True)                   │
│   • Returns preview without side effects            │
└─────────────────────────────────────────────────────┘
```

### Two-Step Validation

1. **AI Semantic Validation**: Claude analyzes if the command makes semantic sense
   - Checks for keyword mismatches (e.g., "always" in `/trigger`)
   - Suggests correct command if needed
   - Returns structured ValidationResult

2. **Tool Preview**: Tool executes in validation-only mode
   - Shows what would happen
   - No side effects (no database writes, no API calls)
   - Returns preview data

## Usage

### CLI Commands

```bash
# Validate new triggered instruction without saving
/trigger --add --check

# Validate removal without removing
/trigger --remove trigger_abc123 --check

# Future: memory commands
/memory --add --check
/memory --remove mem_123 --check
```

### Interactive Example

```
$ /trigger --add --check

=== 🔍 Validate Triggered Instruction (Check Mode) ===

Available trigger types:
  1. session_start    - When a new session starts
  2. email_received   - When a new email arrives
  3. sms_received     - When a new SMS arrives
  4. call_received    - When a new call is received

Select trigger type (1-4): 1
Enter instruction: always use formal tone

✅ Validation Result:
  This instruction uses "always" which indicates always-on behavior,
  but you're trying to add it as a triggered instruction. Triggered
  instructions execute when events occur, not continuously.

  Semantic issues detected:
    • No event trigger detected - this is always-on behavior

  💡 Suggestion: Use /memory --add "always use formal tone" instead

  This command will NOT be executed.
```

## Implementation Details

### File Locations

- **Service**: `zylch/services/validation_service.py`
- **Tool Base**: `zylch/tools/base.py`
- **Trigger Tools**: `zylch/tools/instruction_tools.py`
- **CLI Integration**: `zylch/cli/main.py`
  - Lines 143-144: Instance variables
  - Lines 189-192: Initialization
  - Lines 615-661: Display method
  - Lines 785-886: Check methods
- **Tutorial**: `zylch/tutorial/steps/triggers_demo.py`

### ValidationService API

```python
from zylch.services.validation_service import CommandValidator, ValidationResult

# Initialize
validator = CommandValidator(anthropic_api_key=settings.anthropic_api_key)

# Validate command
result: ValidationResult = await validator.validate_command(
    command="/trigger",
    parameters={
        "action": "add",
        "instruction": "always use formal tone",
        "trigger": "session_start"
    },
    context={"user_id": "user123"}
)

# Check result
if result.valid:
    print("✅", result.explanation)
else:
    print("❌", result.explanation)
    if result.suggestion:
        print("💡", result.suggestion)
    for issue in result.semantic_issues:
        print("  •", issue)
```

### ValidationResult Fields

```python
@dataclass
class ValidationResult:
    valid: bool                    # True if command is semantically correct
    status: ValidationStatus       # VALID, INVALID, WARNING, NEEDS_CLARIFICATION
    action: str                    # Brief description of action
    preview: Dict[str, Any]        # Structured preview data
    explanation: str               # Natural language explanation
    suggestion: Optional[str]      # Alternative command suggestion
    semantic_issues: List[str]     # List of detected issues
```

### Tool Pattern

All tools implement the `validation_only` parameter:

```python
class AddTriggeredInstructionTool(Tool):
    async def execute(
        self,
        validation_only: bool = False,
        instruction: str = "",
        trigger: str = "",
        name: Optional[str] = None
    ) -> ToolResult:
        # Validate parameters
        if not instruction or not trigger:
            return ToolResult(status=ToolStatus.ERROR, ...)

        # Build preview data
        trigger_data = {
            "id": trigger_id,
            "instruction": instruction,
            "trigger": trigger,
            "will_execute_on": self._get_trigger_description(trigger),
            "example_scenario": self._get_example_scenario(trigger)
        }

        # VALIDATION MODE: Return preview without saving
        if validation_only:
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=trigger_data,
                message="PREVIEW: This would add a triggered instruction..."
            )

        # EXECUTION MODE: Actually save to memory
        memory_id = self.zylch_memory.store_memory(...)
        return ToolResult(status=ToolStatus.SUCCESS, data={...})
```

## Semantic Validation Patterns

### /trigger vs /memory

**Triggered Instructions (`/trigger`)**
- Event-driven automation
- Executes when specific events occur
- Keywords: when, if, after, on, whenever
- Events: session_start, email_received, sms_received, call_received
- Example: "Greet me when session starts"

**Behavioral Memory (`/memory`)**
- Always-on behavioral rules
- Applies to ALL interactions continuously
- Keywords: always, never, all, prefer, avoid
- Example: "Always use formal tone"

### Common Semantic Issues

```bash
# ❌ WRONG: Always-on behavior in /trigger
/trigger --add "always use formal tone"
→ Semantic issue: No event trigger
→ Suggestion: Use /memory --add instead

# ❌ WRONG: Event-driven behavior in /memory
/memory --add "when email arrives, alert me"
→ Semantic issue: Event trigger detected
→ Suggestion: Use /trigger --add instead

# ✅ CORRECT: Event-driven in /trigger
/trigger --add "greet me when session starts"
→ Has event: session_start

# ✅ CORRECT: Always-on in /memory
/memory --add "never mention competitors"
→ No event, always-on rule
```

### Keyword Detection

**Trigger Keywords (event-driven)**
- when, if, after, before, on, whenever
- arrives, starts, ends, happens, occurs
- received, sent, created, updated

**Memory Keywords (always-on)**
- always, never, all, every (without event context)
- prefer, avoid, use, don't use
- should, must, must not

## Implementation Status

### ✅ Priority 0 (Complete)
- ValidationService created
- Tool.execute() with validation_only parameter
- AddTriggeredInstructionTool validation support
- RemoveTriggeredInstructionTool validation support
- CLI integration (/trigger --add/--remove --check)
- Display method for validation results
- Help text updated
- Italian examples replaced with US-oriented examples

### ⏳ Priority 1 (Pending)
- Extract /memory handlers to proper tools
- Add validation_only to memory tools
- Update /memory command handler with --check support

### ⏳ Priority 2 (Pending)
- Add validation_only to sharing tools (/share, /revoke)
- Add validation_only to archive tools (/archive)

### ⏳ Priority 3 (Optional)
- REST API endpoints for validation
- Tutorial sandbox mode integration
- Validation result caching

## Testing

### Manual Testing

```bash
# Test 1: Valid trigger
/trigger --add --check
> Select: session_start
> Instruction: "greet me at the start of every session"
Expected: ✅ Valid

# Test 2: Invalid trigger (always-on behavior)
/trigger --add --check
> Select: session_start
> Instruction: "always use formal tone"
Expected: ❌ Invalid, suggests /memory

# Test 3: Valid removal preview
/trigger --list  # Get an ID
/trigger --remove trigger_abc123 --check
Expected: ✅ Shows what would be removed
```

### Unit Tests (Future)

```python
# Test ValidationService
async def test_semantic_validation_always_in_trigger():
    validator = CommandValidator(api_key="test")
    result = await validator.validate_command(
        command="/trigger",
        parameters={"action": "add", "instruction": "always use formal tone"}
    )
    assert not result.valid
    assert "always-on" in result.explanation.lower()
    assert result.suggestion is not None

# Test Tool validation_only
async def test_tool_validation_only_mode():
    tool = AddTriggeredInstructionTool(...)
    result = await tool.execute(
        validation_only=True,
        instruction="test",
        trigger="session_start"
    )
    assert result.status == ToolStatus.SUCCESS
    assert result.data["id"].startswith("trigger_")
    # Verify nothing was saved to database
```

## Future Enhancements

1. **REST API Endpoints**
   ```
   POST /api/v1/validate/trigger
   POST /api/v1/validate/memory
   POST /api/v1/validate/share
   ```

2. **Tutorial Sandbox Mode**
   - Interactive tutorial where commands are validated but not executed
   - Safe learning environment

3. **Validation Caching**
   - Cache validation results for common patterns
   - Reduce AI API calls

4. **Batch Validation**
   - Validate multiple commands at once
   - Import/export validation reports

5. **Custom Validation Rules**
   - User-defined semantic patterns
   - Team-specific validation policies
