from typing import Any

FINANCIAL_INTERPRETATION_GUIDANCE = (
    "Use neutral labels when the underlying basis is missing: invoice VAT difference, "
    "gross document difference, and net document difference. For example, "
    "220.00 minus 44.00 is an invoice VAT difference of 176.00, not established "
    "VAT payable or recoverable. Source IDs and Decimal arithmetic do not establish "
    "VAT regime, deductibility, settlement or payment status. Do not label gross "
    "document differences as cash flows or verified bank balances without actual "
    "settlement and bank/reconciliation evidence. Do not label net document "
    "differences as effective profit without accounting basis, completeness and "
    "period-end adjustment evidence. Missing basis requires explicit limitations "
    "and human review; use workflow_ask_user if the requested conclusion depends on it. "
    "A generic tax disclaimer does not justify a definite tax liability label. "
    "Reporting scope and model narrative cannot grant verified tax, bank or profit status."
)


TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
AMOUNT = {
    "type": "string",
    "pattern": r"^-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?$",
    "description": "Decimal string, at most 18 integer digits and 8 fractional digits; never a JSON number or arithmetic expression.",
}


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def calculation_payload() -> dict[str, Any]:
    row = _object(
        {
            "id": {**TEXT, "description": "Unique row identifier in this calculation."},
            "identity": {
                **TEXT,
                "description": "Economic transaction identity; avoid double counting.",
            },
            "amount": AMOUNT,
            "currency": TEXT,
            "period": TEXT,
            "category": {
                **TEXT,
                "description": "Describe the documented amount neutrally, such as invoice VAT amount or invoice net amount. A category label does not establish tax deductibility, payment, balance or effective profit.",
            },
            "source_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "items": TEXT,
                "description": "Authorized uploaded document IDs or successful managed Qonto source IDs, never invoice references invented as source IDs.",
            },
            "treatment": {
                "type": "string",
                "enum": ["observed", "estimate", "scenario", "exclude", "overlap"],
            },
            "reason": {**TEXT, "description": "Required for every treatment other than observed."},
            "related_ids": {
                "type": "array",
                "maxItems": 100,
                "items": TEXT,
                "description": "Other row IDs in this calculation; required and nonempty for overlap; never reference the row itself.",
            },
        },
        ["id", "identity", "amount", "currency", "period", "category", "source_ids", "treatment"],
    )
    row["anyOf"] = [
        {"properties": {"treatment": {"enum": ["observed"]}}},
        {
            "properties": {"treatment": {"enum": ["estimate", "scenario", "exclude"]}},
            "required": ["reason"],
        },
        {
            "properties": {"treatment": {"enum": ["overlap"]}, "related_ids": {"minItems": 1}},
            "required": ["reason", "related_ids"],
        },
    ]
    rows = {"type": "array", "maxItems": 10000, "items": row}
    groups = {
        "type": "array",
        "maxItems": 3,
        "uniqueItems": True,
        "items": {"type": "string", "enum": ["period", "category", "currency"]},
    }
    schema = {
        "type": "object",
        "description": 'Use exactly one supported shape: {"operation":"subtract","left":"1220.00","right":"244.00"}; or {"operation":"sum","rows":[{"id":"r1","identity":"invoice-1","amount":"1000.00","currency":"EUR","period":"2026-Q3","category":"revenue","treatment":"observed","source_ids":["AUTHORIZED_DOCUMENT_ID"]}],"group_by":["period","category"]}. No operands, amounts, net_margin or cash_balance operations. Read supplied documents before calculating. Source IDs authorize provenance, not independent verification of amounts or treatment.',
        "anyOf": [
            _object(
                {
                    "operation": {"type": "string", "enum": ["sum", "group"]},
                    "rows": rows,
                    "group_by": groups,
                    "opening": {"anyOf": [AMOUNT, {"type": "null"}]},
                    "closing": {"anyOf": [AMOUNT, {"type": "null"}]},
                },
                ["operation", "rows"],
            ),
            _object(
                {
                    "operation": {"type": "string", "enum": ["reconcile", "roll_forward"]},
                    "rows": rows,
                    "group_by": groups,
                    "opening": {"anyOf": [AMOUNT, {"type": "null"}]},
                    "closing": {"anyOf": [AMOUNT, {"type": "null"}]},
                },
                ["operation", "rows"],
            ),
            _object(
                {
                    "operation": {"type": "string", "enum": ["variance"]},
                    "current": AMOUNT,
                    "prior": AMOUNT,
                },
                ["operation", "current", "prior"],
            ),
            _object(
                {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "subtract", "multiply", "divide", "ratio"],
                    },
                    "left": AMOUNT,
                    "right": AMOUNT,
                },
                ["operation", "left", "right"],
            ),
        ],
    }
    schema["description"] += " " + FINANCIAL_INTERPRETATION_GUIDANCE
    descriptions = [
        "sum/group: group rows by currency and treatment, optionally period/category. Estimates and scenarios remain separate. Exclude/overlap rows do not contribute to totals; their IDs are retained.",
        "reconcile/roll_forward: one currency, no estimate/scenario rows. Sum observed movements; expected_closing=opening+movements and difference=closing-expected_closing. Missing opening/closing gives incomplete, never an invented balance.",
        "variance: absolute=current-prior; percentage=(current-prior)/abs(prior)*100. A zero prior gives an undefined percentage.",
        "add/subtract/multiply/divide/ratio use left and right decimal strings. subtract=left-right; divide/ratio=left/right. A zero divisor gives amount=null and status=undefined_zero_base. Numeric inputs are not independently source verified.",
    ]
    for branch, description in zip(schema["anyOf"], descriptions):
        branch["description"] = description
    return schema


def financial_scope() -> dict[str, Any]:
    descriptions = {
        "period_from": "Reporting period start, preferably YYYY-MM-DD.",
        "period_to": "Reporting period end/cutoff, preferably YYYY-MM-DD.",
        "currency": "Reporting currency, for example EUR; do not silently combine currencies.",
        "entity": "Entity whose accounts are being reconstructed; ask the user when unknown.",
        "framework": "Reporting basis, for example approximate management accounts; never imply audited or statutory completeness. This descriptive field cannot establish tax liability, verified bank balance or effective profit.",
    }
    return _object(
        {
            key: {"type": "string", "maxLength": 200, "description": value}
            for key, value in descriptions.items()
        },
        [],
    )


def deadline_payload() -> dict[str, Any]:
    day = {
        "type": "string",
        "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
        "description": "An explicit ISO calendar date YYYY-MM-DD; do not invent the triggering date.",
    }
    return _object(
        {
            "trigger": day,
            "days": {"type": "integer", "minimum": 1, "maximum": 36600},
            "include_trigger": {"type": "boolean"},
            "excluded_intervals": {
                "type": "array",
                "maxItems": 100,
                "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": day},
            },
            "expiry_holidays": {"type": "array", "maxItems": 100, "items": day},
            "expiry_weekdays": {
                "type": "array",
                "maxItems": 7,
                "items": {"type": "integer", "minimum": 0, "maximum": 6},
                "description": "Excluded expiry weekdays: Monday=0 through Sunday=6.",
            },
        },
        ["trigger", "days"],
    )


def legal_facts() -> dict[str, Any]:
    return {
        "description": "Case facts from supplied evidence only. Do not put remembered legal background, statutory dates, acts or requirements into facts. Unknown case facts stay unresolved.",
        "type": "array",
        "maxItems": 100,
        "items": _object(
            {
                "id": {"type": "string", "maxLength": 100},
                "status": {"type": "string", "enum": ["resolved", "unresolved"]},
                "description": {"type": "string", "maxLength": 2000},
                "material": {
                    "type": "boolean",
                    "description": "Unresolved material facts prevent operative grounds; never assert resolved without evidence.",
                },
            },
            ["id", "status"],
        ),
    }


def legal_citations() -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": 100,
        "items": _object(
            {
                "source_id": {
                    "type": "string",
                    "description": "Actual retained legal source ID from workflow_legal_fetch.",
                },
                "passage_id": {
                    "type": "string",
                    "maxLength": 240,
                    "description": "Strongly preferred: exact engine-derived passage_id from workflow_legal_passage for this source_id. Copy the ID unchanged and omit quote; the server supplies the original quotation. This does not verify applicability, interpretation or facts.",
                },
                "quote": {
                    "type": "string",
                    "description": "Legacy exact source quotation: at least ten non-whitespace characters, no [...] omissions or paraphrase. Prefer passage_id and omit quote. If both are provided, quote must equal the complete source-exact passage character for character.",
                },
                "version_date": {
                    "type": "string",
                    "description": "Exact source metadata.version_date; unverified temporal applicability stays unresolved.",
                },
                "fact_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant fact IDs from facts; only resolved facts support operative grounds.",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Stay within this retrieved exact passage. No ancillary acts, statutory periods, dates or legal requirements from memory, including conditional examples. Concrete proposals use placeholders for unknown case facts.",
                },
                "proposition": {
                    "type": "string",
                    "description": "Only a proposition supported by this exact retrieved passage and pinpoint. Do not introduce remembered acts, periods, dates or separate legal requirements.",
                },
                "adverse": {"type": "boolean"},
            },
            [],
        ),
    }
