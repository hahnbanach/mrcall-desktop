"""MrCall Context Builders — Fetch live variable values from StarChat.

Standalone functions extracted from MrCallConfiguratorTrainer for use at runtime.
These build the {variables_context} and {conversation_variables_context} placeholders
used in mrcall_templates.py runtime templates.

Called by MrCallAgent._build_runtime_prompt() on every /agent mrcall run invocation.
"""

import json as json_module
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def build_variables_context(
    starchat,
    business_id: str,
    variable_names: List[str],
    business: Optional[Dict[str, Any]] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> str:
    """Build variables context from StarChat metadata + live values.

    Fetches variable schema (type, description, default) and current values,
    then formats them for injection into runtime templates.

    Args:
        starchat: StarChat client instance
        business_id: MrCall business ID
        variable_names: List of variable names to include
        business: Pre-fetched business config (avoids redundant API call)
        schema: Pre-fetched flattened variable schema (avoids redundant API call)

    Returns:
        Formatted string with metadata for each variable
    """
    logger.debug(
        f"[mrcall_context] build_variables_context("
        f"business_id={business_id}, vars={variable_names})"
    )

    if business is None:
        business = await starchat.get_business_config(business_id)
    if not business:
        raise ValueError(f"Business not found: {business_id}")

    current_values = business.get("variables", {})

    if schema is None:
        schema = await fetch_and_flatten_schema(starchat, business)

    lines = []
    for var_name in variable_names:
        var_schema = schema.get(var_name, {})

        human_name = var_schema.get("humanName", "")
        desc = var_schema.get("description", "")
        default = var_schema.get("defaultValue", "")
        var_type = var_schema.get("type", "unknown")
        current = current_values.get(var_name, "Not set")
        modifiable = var_schema.get("modifiable", True)
        visible = var_schema.get("visible", True)
        admin = var_schema.get("admin", False)

        depends_on_raw = var_schema.get("depends_on", [])
        depends_on = []
        if isinstance(depends_on_raw, list):
            for dep_item in depends_on_raw:
                if isinstance(dep_item, list) and dep_item:
                    depends_on.append(dep_item[0])
                elif isinstance(dep_item, str):
                    depends_on.append(dep_item)

        var_context = f"""
**{var_name}**
- Type: {var_type}
- Human Name: {human_name}
- Description: {desc}
- Default: {default}
- Current Value: {current}"""

        if depends_on:
            var_context += f"\n- Depends On: {', '.join(depends_on)}"
        if not modifiable:
            var_context += "\n- Modifiable: No (locked by subscription plan)"
        if not visible:
            var_context += "\n- Visible: No"
        if admin:
            var_context += "\n- Admin: Yes"

        lines.append(var_context)

    return "\n".join(lines)


async def build_conversation_variables_context(
    starchat,
    business_id: str,
    business: Optional[Dict[str, Any]] = None,
) -> str:
    """Build conversation variables context (runtime %%var%% variables).

    Parses ASSISTANT_TOOL_VARIABLE_EXTRACTION from business config to list
    variables available during phone calls.

    Args:
        starchat: StarChat client instance
        business_id: MrCall business ID
        business: Pre-fetched business config (avoids redundant API call)

    Returns:
        Formatted string with available conversation variables
    """
    if business is None:
        business = await starchat.get_business_config(business_id)
    if not business:
        raise ValueError(f"Business not found: {business_id}")

    current_values = business.get("variables", {})

    # Parse ASSISTANT_TOOL_VARIABLE_EXTRACTION
    raw_extraction = current_values.get("ASSISTANT_TOOL_VARIABLE_EXTRACTION", "[]")
    try:
        extraction_vars = json_module.loads(raw_extraction)
    except (json_module.JSONDecodeError, TypeError):
        extraction_vars = []

    lines = [
        "### Caller-Extracted Variables",
        "These are extracted from conversation and saved to contact record:",
        "",
    ]

    # Always-present defaults
    defaults = [
        ("FIRST_NAME", "Caller's first name", "required", "forget"),
        ("FAMILY_NAME", "Caller's family name", "not_required", "forget"),
        ("CALL_REASON", "Reason for calling", "not_required", "forget"),
    ]

    # Merge defaults with custom extraction vars
    seen_names: set = set()
    all_vars: list = []
    for var in extraction_vars:
        if isinstance(var, list) and len(var) >= 2:
            name = var[0]
            desc = var[1]
            required = var[2] if len(var) > 2 else "not_required"
            persist = var[3] if len(var) > 3 else "forget"
            all_vars.append((name, desc, required, persist))
            seen_names.add(name)

    for name, desc, required, persist in defaults:
        if name not in seen_names:
            all_vars.append((name, desc, required, persist))

    for name, desc, required, persist in all_vars:
        req_label = "required" if required == "required" else "optional"
        persist_label = "persists" if persist != "forget" else "per-call"
        lines.append(f"- `%%{name}%%` — {desc} ({req_label}, {persist_label})")

    lines.extend([
        "",
        "### Date/Time & Business Status",
        "- `%%HUMANIZED_TODAY%%` — Today's date in natural language",
        "- `%%HUMANIZED_NOW%%` — Current time in natural language",
        "- `%%public:BUSINESS_OPEN%%` — 'true' if within business hours",
        "- `%%public:OPENING_HOURS_TEXT%%` — Business hours as text",
        "",
        "### Caller Info",
        "- `%%HB_FROM_NUMBER%%` — Caller's phone number",
        "- `%%RECURRENT_CONTACT%%` — 'true' if caller has called before",
        "- `%%OUTBOUND_CALL%%` — 'true' if this is an outbound call",
    ])

    return "\n".join(lines)


async def fetch_and_flatten_schema(
    starchat,
    business: Dict[str, Any],
) -> Dict[str, Any]:
    """Fetch variable schema from StarChat and flatten to {name: data} dict.

    Args:
        starchat: StarChat client instance
        business: Business config (needs template + languageCountry)

    Returns:
        Flattened dict mapping variable name to variable metadata
    """
    template = business.get("template", "businesspro")
    raw_lang = business.get("languageCountry", "")
    biz_lang = raw_lang.replace("_", "-") if raw_lang else ""
    biz_lang_short = biz_lang[:2] if biz_lang else ""

    raw_schema = await starchat.get_variable_schema(
        template_name=template,
        language=biz_lang or "en-US",
        nested=True,
        language_descriptions=biz_lang_short or "en",
    )
    return flatten_schema(raw_schema)


def flatten_schema(raw_schema) -> Dict[str, Any]:
    """Flatten StarChat variable schema from nested collections to flat dict.

    Args:
        raw_schema: Raw schema from starchat.get_variable_schema()

    Returns:
        Dict mapping variable name to variable data
    """
    schema: Dict[str, Any] = {}
    if isinstance(raw_schema, list):
        for collection in raw_schema:
            if not isinstance(collection, dict):
                continue
            for item in collection.get("variables", []):
                vars_to_process = item if isinstance(item, list) else [item]
                for var in vars_to_process:
                    if isinstance(var, dict):
                        name = var.get("name")
                        if name:
                            schema[name] = var
    elif isinstance(raw_schema, dict):
        schema = raw_schema
    return schema
