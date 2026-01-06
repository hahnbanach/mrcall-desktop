# MrCall Feature Configuration Reference

## Step 1: Create Meta-Prompt

Add to `zylch/agents/mrcall_configurator_trainer.py`:

```python
BOOKING_META_PROMPT = """You are analyzing the booking configuration for a MrCall AI phone assistant.

Your task: Given the current value of BOOKING_PROMPT, generate a
self-contained sub-prompt that another LLM can use to both UNDERSTAND and MODIFY the configuration.

## UNDERSTANDING THE PROMPT STRUCTURE

[Explain variable format specific to this feature]

Common variable sources:
- `%%crm.contact.variables.X%%` - Data from caller's contact record
- `%%HB_FROM_NUMBER%%` - Caller's phone number
- `%%public:X%%` - Public/shared values

## YOUR OUTPUT FORMAT

Generate a sub-prompt with these exact sections:

### SECTION 1: AVAILABLE VARIABLES
Create a markdown table with columns: Variable | Reference | Description | Default

### SECTION 2: CURRENT BEHAVIOR
Describe what the assistant DOES in plain language.

### SECTION 3: WHAT CAN BE CHANGED
List modifications users can request with examples.

### SECTION 4: WHAT CANNOT BE CHANGED (via this feature)
List system constraints.

### SECTION 5: CURRENT PROMPT VALUE
Include the FULL raw prompt. Add note about preserving %%...%% variables.

---

## CURRENT CONFIGURATION TO ANALYZE:

{current_value}

---

OUTPUT ONLY THE SUB-PROMPT TEXT. No explanations."""
```

---

## Step 2: Add to FEATURES Dict

In `mrcall_configurator_trainer.py`:

```python
FEATURES = {
    "welcome_message": {
        "variables": ["OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"],
        "description": "How the assistant answers the phone",
        "meta_prompt": WELCOME_MESSAGE_META_PROMPT,
    },
    # NEW FEATURE:
    "booking": {
        "variables": ["BOOKING_PROMPT"],
        "description": "Appointment booking behavior",
        "meta_prompt": BOOKING_META_PROMPT,
    },
}
```

---

## Step 3: Add FEATURE_TO_VARIABLE Mapping

In `command_handlers.py` (inside `handle_mrcall`, ~line 792):

```python
# Feature to variable mapping
FEATURE_TO_VARIABLE = {
    "welcome_message": "OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT",
    "booking": "BOOKING_PROMPT",  # NEW
}
SUPPORTED_FEATURES = list(FEATURE_TO_VARIABLE.keys())
```

---

## Step 4: Add VARIABLE_TO_FEATURE Mapping

In `config_tools.py` (~line 24):

```python
VARIABLE_TO_FEATURE = {
    "OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT": "welcome_message",
    "BOOKING_PROMPT": "booking",  # NEW
}
```

---

## Step 5: Update Help Text

In `command_handlers.py`, update TWO places:

### A. Inline help_text (inside handle_mrcall)

```python
**Features:** welcome_message, booking
```

### B. COMMAND_REGISTRY (bottom of file, ~line 2200)

```python
**Features:** welcome_message (greeting), booking (appointments)
```

---

## Meta-Prompt Requirements

1. Must use `{current_value}` placeholder (Python str.format)
2. Must have exactly 5 sections (SECTION 1-5)
3. SECTION 1 must be a markdown table with 4 columns
4. SECTION 5 must include full raw prompt in code block
5. End with "OUTPUT ONLY THE SUB-PROMPT TEXT"

---

## Testing New Feature

```bash
# 1. Train the feature (generates sub-prompt)
/mrcall train booking

# 2. Show the generated context
/mrcall show booking

# 3. Test configuration
/mrcall config booking "require email confirmation"

# 4. Verify the change
/mrcall show booking
```

---

## Mapping Architecture

```
Feature Name ←→ MrCall Variable Name

"welcome_message" ←→ "OSCAR_INBOUND_WELCOME_MESSAGE_PROMPT"
"booking"         ←→ "BOOKING_PROMPT"
```

**Two mapping dictionaries must be kept in sync:**
- `FEATURE_TO_VARIABLE` in `command_handlers.py` (feature → variable)
- `VARIABLE_TO_FEATURE` in `config_tools.py` (variable → feature)

---

## Example: Full Workflow for Adding "booking" Feature

1. **Discover the variable:**
   ```
   /mrcall variables --name BOOKING
   ```

2. **Read current value to understand structure:**
   ```
   /mrcall variables get --name BOOKING_PROMPT
   ```

3. **Create meta-prompt** based on the variable structure

4. **Add to all 3 files** (trainer, command_handlers, config_tools)

5. **Update help text** in both locations

6. **Test the feature** with train/show/config commands
