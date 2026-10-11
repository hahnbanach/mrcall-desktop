"""Managed financial turns through the existing assistant without command rerouting."""

import time

from zylch.qonto import history
from zylch.llm.budget_pricing import BudgetError
from zylch.services.chat_compaction import compact_if_needed


async def process(
    service, user_message, user_id, canonical_history, session_id, context, approval_callback
):
    from zylch.assistant.turn_context import set_turn_observation

    started = time.time()
    set_turn_observation(user_message)
    history.require_managed()
    history.check_before_disclosure()
    await service._initialize_agent(owner_id=user_id)
    history.check_before_disclosure()
    canonical = await compact_if_needed(canonical_history or [])
    history.check_before_disclosure()
    service.agent.set_history(canonical)
    agent_context = {"user_id": user_id}
    if isinstance(context, dict) and isinstance(context.get("force_model"), str):
        agent_context["force_model"] = context["force_model"]
    try:
        response = await service.agent.process_message(
            user_message, agent_context, approval_callback
        )
    except history.HistoryAuthorizationError:
        raise
    except BudgetError as exc:
        history.check_before_disclosure()
        return {
            "response": str(exc),
            "tool_calls": [],
            "metadata": {"error": "BUDGET_REFUSED"},
            "session_id": session_id,
        }
    except Exception:
        history.check_before_disclosure()
        return {
            "response": "The financial answer could not be completed.",
            "tool_calls": [],
            "metadata": {"error": "FINANCE_ANSWER_FAILED"},
            "session_id": session_id,
        }
    history.check_before_disclosure()
    return {
        "response": response,
        "tool_calls": [],
        "metadata": {
            "execution_time_ms": round((time.time() - started) * 1000, 2),
            "tools_available": len(service.agent._get_tool_schemas()),
            **service._truncation_metadata(),
        },
        "session_id": session_id,
    }
