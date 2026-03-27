"""MrCall Agent - Unified multi-tool agent for MrCall configuration.

This is a TRUE AGENT with multiple tools that can:
- Configure 9 features (welcome, booking, knowledge base, transfer, etc.)
- Answer questions and explain settings (respond_text)

Architecture (post-refactor):
- Runtime templates replace train-time LLM-generated sub-prompts
- Live StarChat values fetched on every run() call (no stale data)
- Conversation history support for multi-turn context

Inherits from SpecializedAgent for common functionality (init, prompt loading, etc.)
"""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from zylch.agents.base_agent import SpecializedAgent
from zylch.storage.supabase_client import SupabaseStorage
from zylch.agents.trainers import MrCallConfiguratorTrainer


def _build_changes_schema(feature_name: str) -> dict:
    """Build schema for 'changes' property with only valid variable names.

    Uses MrCallConfiguratorTrainer.FEATURES as the single source of truth.

    Args:
        feature_name: Feature key (e.g., 'welcome_inbound', 'booking')

    Returns:
        JSON schema dict with properties for each valid variable
    """
    variables = MrCallConfiguratorTrainer.FEATURES[feature_name]["variables"]
    return {
        "type": "object",
        "properties": {
            var: {"type": "string", "description": f"New value for {var}"}
            for var in variables
        },
        "additionalProperties": False  # Reject unknown variable names
    }

logger = logging.getLogger(__name__)


# Multi-tool schema for the MrCall agent
# Uses _build_changes_schema to constrain variable names to valid options
MRCALL_AGENT_TOOLS = [
    {
        "name": "configure_welcome_inbound",
        "description": "Modify the inbound welcome message / greeting. Use this when user wants to CHANGE, UPDATE, or MODIFY how the assistant answers incoming calls — including making it more formal, informal, adding/removing greetings, etc. You must provide the COMPLETE new prompt text with your modifications.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("welcome_inbound")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_welcome_outbound",
        "description": "Modify the outbound welcome message. Use this when user wants to CHANGE, UPDATE, or MODIFY how the assistant starts outgoing calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("welcome_outbound")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_booking",
        "description": "Modify booking/appointment settings. Use this when user wants to CHANGE, UPDATE, or MODIFY booking behavior. When enabling booking, you MUST set START_BOOKING_PROCESS, BOOKING_HOURS, BOOKING_EVENTS_MINUTES, and ENABLE_GET_CALENDAR_EVENTS together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("booking")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_caller_followup",
        "description": "Modify post-call WhatsApp/SMS messages sent to the caller. Use this when user wants to CHANGE, UPDATE, or MODIFY what message callers receive after the call — including enabling/disabling WhatsApp (MrZappa, WATI, Callbell) or SMS channels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("caller_followup")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_conversation",
        "description": "Modify the conversation flow — what the assistant asks or does after the greeting. Use this when user wants to CHANGE, UPDATE, or MODIFY the questions asked, information collected, or steps followed during the call.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("conversation")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_knowledge_base",
        "description": "Modify the knowledge base Q&A pairs and general behavior instructions. Use this when user wants to ADD, REMOVE, or CHANGE how the assistant answers specific caller questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("knowledge_base")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_notifications_business",
        "description": "Modify notification settings that inform the business owner about calls — email, WhatsApp, SMS, Firebase push. Use this when user wants to CHANGE, UPDATE, or MODIFY how/where call notifications are sent to the business.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("notifications_business")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_runtime_data",
        "description": "Modify external API integrations (PREFETCH/RUNNINGLOOP/FINAL stages). Use this when user wants to CONNECT external systems — CRM lookups before calls, real-time data queries during calls, or webhook/CRM pushes after calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("runtime_data")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "configure_call_transfer",
        "description": "Modify call forwarding/transfer rules. Use this when user wants to CHANGE, UPDATE, ADD, or REMOVE rules for transferring calls to specific phone numbers based on caller intent or business hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "changes": _build_changes_schema("call_transfer")
            },
            "required": ["changes"]
        }
    },
    {
        "name": "respond_text",
        "description": "Answer ANY question about the current configuration: 'how does it greet callers?', 'is booking enabled?', 'what are my settings?', 'does it answer formally?'. Always explain in human-friendly language, never show raw variable names or template syntax.",
        "input_schema": {
            "type": "object",
            "properties": {
                "response": {
                    "type": "string",
                    "description": "Your response text"
                }
            },
            "required": ["response"]
        }
    },
]

# Anthropic native web search tool (server-side, uses Brave Search)
# NOT included in MRCALL_AGENT_TOOLS — added separately in _call_anthropic()
# because it uses a different schema format ("type" instead of "name"+"input_schema")
ANTHROPIC_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}


class MrCallAgent(SpecializedAgent):
    """Unified MrCall configuration agent with multiple tools.

    Inherits from SpecializedAgent for common functionality.

    This agent:
    1. Has a trained prompt that combines all feature knowledge
    2. Has multiple tools for different configuration actions
    3. Lets the LLM choose which tool to use based on user intent

    Tools available:
    - configure_welcome_inbound: Update inbound greeting settings
    - configure_welcome_outbound: Update outbound greeting settings
    - configure_booking: Update booking settings
    - respond_text: Answer questions and explain current settings

    Usage:
        agent = MrCallAgent(storage, owner_id, api_key, provider, starchat)
        result = await agent.run("enable booking with 30 minute appointments")
    """

    PROMPT_KEY = 'mrcall'  # Base key - actual key is mrcall_{business_id}
    TOOLS = MRCALL_AGENT_TOOLS

    def __init__(
        self,
        storage: SupabaseStorage,
        owner_id: str,
        api_key: str,
        provider: str = "anthropic",
        starchat_client=None,
    ):
        """Initialize MrCallAgent.

        Args:
            storage: SupabaseStorage instance
            owner_id: Firebase UID
            api_key: LLM API key
            provider: LLM provider (anthropic, openai, mistral)
            starchat_client: StarChat client for API calls
        """
        super().__init__(storage, owner_id, api_key, provider)
        self.starchat = starchat_client

        # Get business_id for dynamic prompt key
        self.business_id = storage.get_mrcall_link(owner_id)

        logger.info(f"MrCallAgent initialized for owner={owner_id}, business={self.business_id}")

    async def _build_runtime_prompt(self) -> str:
        """Build system prompt with LIVE values from StarChat.

        Fetches current business config and variable schema, then fills
        runtime templates with live data. No train step required.

        Returns:
            Complete system prompt string with all feature knowledge + current values

        Raises:
            ValueError: If business not found or StarChat unavailable
        """
        from zylch.agents.mrcall_templates import FEATURE_TEMPLATES, UNIFIED_RUNTIME_TEMPLATE
        from zylch.agents.mrcall_context import (
            build_variables_context,
            build_conversation_variables_context,
            fetch_and_flatten_schema,
        )

        if not self.starchat:
            raise ValueError("StarChat client not available")

        # Single API call: fetch business config with all current variable values
        business = await self.starchat.get_business_config(self.business_id)
        if not business:
            raise ValueError(f"Business not found: {self.business_id}")
        logger.debug(
            f"[MrCallAgent] Fetched business config: "
            f"template={business.get('template')}, "
            f"vars_count={len(business.get('variables', {}))}"
        )

        # Single API call: fetch variable schema (types, descriptions, defaults)
        schema = await fetch_and_flatten_schema(self.starchat, business)
        self._cached_schema = schema  # Cache for _process_configure() validation
        logger.debug(f"[MrCallAgent] Fetched variable schema: {len(schema)} variables")

        # Build conversation variables context once (shared across features)
        conv_vars_ctx = await build_conversation_variables_context(
            self.starchat, self.business_id, business=business
        )

        # Fill each feature template with live values
        feature_sections = []
        for feature_name, template in FEATURE_TEMPLATES.items():
            variables = MrCallConfiguratorTrainer.FEATURES.get(
                feature_name, {}
            ).get("variables", [])

            vars_ctx = await build_variables_context(
                self.starchat,
                self.business_id,
                variables,
                business=business,
                schema=schema,
            )

            filled = template.format(
                variables_context=vars_ctx,
                conversation_variables_context=conv_vars_ctx,
            )
            display_name = MrCallConfiguratorTrainer.FEATURES.get(
                feature_name, {}
            ).get("display_name", feature_name)
            feature_sections.append(
                f"### {feature_name.upper()}\n**{display_name}**\n\n{filled}"
            )

        # Extract business identity for prompt
        business_name = (
            business.get("nickname")
            or business.get("name")
            or business.get("companyName")
            or "Unknown Business"
        )
        business_language = business.get("languageCountry", "unknown")

        # Combine into unified prompt
        system_prompt = UNIFIED_RUNTIME_TEMPLATE.format(
            business_name=business_name,
            business_id=self.business_id,
            business_language=business_language,
            feature_sections="\n\n".join(feature_sections),
        )

        # Inject config memory (past configuration decisions)
        from zylch.agents.mrcall_memory import load_config_memory
        config_memory = load_config_memory(self.owner_id, self.business_id)
        if config_memory:
            system_prompt += (
                "\n\n## PREVIOUS CONFIGURATION DECISIONS\n\n"
                "The following changes were made in previous sessions. "
                "Use this context to understand the business's setup:\n\n"
                f"{config_memory}\n"
            )
            logger.info(
                f"[MrCallAgent] Injected config memory: {len(config_memory)} chars"
            )

        logger.info(
            f"[MrCallAgent] Built runtime prompt: {len(system_prompt)} chars, "
            f"{len(feature_sections)} features"
        )
        return system_prompt

    async def _gather_context(self, instructions: str, **kwargs) -> str:
        """Override - MrCall uses _build_runtime_prompt() instead."""
        return ""

    async def run(
        self,
        instructions: str,
        dry_run: bool = False,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Execute agent with given instructions and live StarChat values.

        Builds a runtime prompt with LIVE variable values (no train step needed)
        and supports multi-turn conversation history.

        Args:
            instructions: What the user wants to do
            dry_run: If True, validate and summarize changes but don't apply
            conversation_history: Previous messages for multi-turn context
            attachments: File attachments [{name, media_type, data (base64)}]

        Returns:
            Dict with tool_used, tool_input, result, error
        """
        if not self.business_id:
            return {
                'error': 'No MrCall assistant linked. Run `/mrcall list` then `/mrcall link N` first.'
            }

        # Build system prompt with LIVE StarChat values
        try:
            system_prompt = await self._build_runtime_prompt()
        except ValueError as e:
            logger.error(f"[MrCallAgent] Failed to build runtime prompt: {e}")
            return {'error': str(e)}

        # Build messages list with conversation history
        messages: List[Dict[str, str]] = []

        if conversation_history:
            # Include recent history (last 10 messages to control prompt size)
            recent = conversation_history[-10:]
            messages.extend(recent)
            logger.debug(
                f"[MrCallAgent] Including {len(recent)} messages from conversation history"
            )

        # Current user instruction — with attachments as Anthropic native content blocks
        if attachments:
            content_blocks = []
            for att in attachments:
                media_type = att.get("media_type", "")
                if media_type.startswith("image/"):
                    # Image: Anthropic native format
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": att["data"],
                        }
                    })
                elif media_type == "application/pdf":
                    # PDF: Anthropic native format (supported since 2025)
                    content_blocks.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": att["data"],
                        }
                    })
                else:
                    # Text/CSV/other: decode and include as text
                    import base64
                    try:
                        decoded = base64.b64decode(att["data"]).decode("utf-8", errors="replace")
                        content_blocks.append({
                            "type": "text",
                            "text": f"[Attached file: {att.get('name', 'file')}]\n{decoded}"
                        })
                    except Exception:
                        content_blocks.append({
                            "type": "text",
                            "text": f"[Attached file: {att.get('name', 'file')}] (could not decode)"
                        })

            # Add user text last
            if instructions.strip():
                content_blocks.append({"type": "text", "text": instructions})

            messages.append({"role": "user", "content": content_blocks})
            logger.info(
                f"[MrCallAgent] User message with {len(attachments)} attachments, "
                f"{len(content_blocks)} content blocks"
            )
        else:
            messages.append({"role": "user", "content": instructions})

        logger.debug(f"[MrCallAgent] System prompt: {len(system_prompt)} chars")
        logger.info(
            f"[MrCallAgent] Calling LLM with {len(self.TOOLS)} tools, "
            f"{len(messages)} messages"
        )

        # Call Anthropic API directly (not via aisuite) to support:
        # - Native web_search_20250305 server tool
        # - Native PDF/image content blocks
        # MrCall always uses Anthropic, so no provider abstraction needed.
        try:
            response = await self._call_anthropic(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=4096,
            )
            logger.info(f"[MrCallAgent] LLM response: stop_reason={response.stop_reason}")
            for i, block in enumerate(response.content):
                if hasattr(block, 'name'):
                    logger.info(f"[MrCallAgent] Block {i}: tool_use name={block.name}")
                    logger.debug(f"[MrCallAgent] Block {i}: tool_input={block.input}")
                elif hasattr(block, 'text'):
                    logger.debug(f"[MrCallAgent] Block {i}: text={block.text}")
        except Exception as e:
            logger.error(f"[MrCallAgent] LLM call failed: {e}", exc_info=True)
            return {'error': f'LLM call failed: {str(e)}'}

        result = await self._handle_tool_response(response, dry_run=dry_run)
        return result

    async def run_stream(
        self,
        instructions: str,
        dry_run: bool = False,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream agent response as SSE-compatible events.

        Same as run() but yields incremental chunks.

        Yields:
            Dicts: text_delta, tool_result, metadata, error, done
        """
        import anthropic
        import asyncio
        import queue
        import threading

        if not self.business_id:
            yield {"type": "error", "message": "No MrCall assistant linked."}
            return

        try:
            system_prompt = await self._build_runtime_prompt()
        except ValueError as e:
            yield {"type": "error", "message": str(e)}
            return

        # Build messages (same logic as run())
        messages: List[Dict[str, Any]] = []
        if conversation_history:
            messages.extend(conversation_history[-10:])

        if attachments:
            content_blocks = []
            for att in attachments:
                media_type = att.get("media_type", "")
                if media_type.startswith("image/"):
                    content_blocks.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": att["data"]}
                    })
                elif media_type == "application/pdf":
                    content_blocks.append({
                        "type": "document",
                        "source": {"type": "base64", "media_type": "application/pdf", "data": att["data"]}
                    })
                else:
                    import base64
                    try:
                        decoded = base64.b64decode(att["data"]).decode("utf-8", errors="replace")
                        content_blocks.append({"type": "text", "text": f"[Attached file: {att.get('name', 'file')}]\n{decoded}"})
                    except Exception:
                        content_blocks.append({"type": "text", "text": f"[Attached file: {att.get('name', 'file')}] (could not decode)"})
            if instructions.strip():
                content_blocks.append({"type": "text", "text": instructions})
            messages.append({"role": "user", "content": content_blocks})
        else:
            messages.append({"role": "user", "content": instructions})

        # Build Anthropic client + tools
        # Always use system-level Anthropic key (not user's BYOK or Scaleway key)
        from zylch.config import settings as app_settings
        api_key = app_settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured — required for MrCall agent")
        # Always use Anthropic model (not the aisuite provider model which could be gpt-4.1)
        model = app_settings.anthropic_model
        client = anthropic.Anthropic(api_key=api_key)

        tools = []
        for tool in self.TOOLS:
            tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            })
        tools.append(ANTHROPIC_WEB_SEARCH_TOOL)

        from zylch.agents.mrcall_error_handler import (
            is_retryable, humanize_error, log_error, parse_error_details,
            MAX_RETRIES, BACKOFF_BASE, FINAL_FALLBACK_MESSAGE,
        )

        logger.info(f"[MrCallAgent.stream] Starting: model={model}, messages={len(messages)}")

        # Stream from Anthropic in a worker thread with retry
        chunk_queue: queue.Queue = queue.Queue()
        error_holder: List[Exception] = []
        final_holder: list = [None]
        retry_count_holder: list = [0]

        def _stream_worker():
            try:
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        with client.messages.stream(
                            model=model,
                            max_tokens=4096,
                            system=system_prompt,
                            messages=messages,
                            tools=tools,
                        ) as stream:
                            for event in stream:
                                chunk_queue.put(event)
                            final_holder[0] = stream.get_final_message()
                        return  # Success — exit retry loop
                    except Exception as e:
                        retry_count_holder[0] = attempt + 1
                        if attempt < MAX_RETRIES and is_retryable(e):
                            wait = BACKOFF_BASE * (2 ** attempt)
                            logger.warning(
                                f"[MrCallAgent.stream] Retryable error (attempt {attempt + 1}/{MAX_RETRIES}), "
                                f"waiting {wait}s: {e}"
                            )
                            import time
                            time.sleep(wait)
                            continue
                        else:
                            error_holder.append(e)
                            break
            finally:
                # ALWAYS signal the consumer to stop — without this,
                # the while-True loop waits forever and the spinner never stops
                chunk_queue.put(None)

        thread = threading.Thread(target=_stream_worker, daemon=True)
        thread.start()

        text_started = False
        current_tool_name = None
        respond_text_json = ""  # Accumulate JSON for respond_text tool
        respond_text_streaming = False  # True once we're past the JSON prefix
        try:
            while True:
                try:
                    event = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: chunk_queue.get(timeout=0.1)
                    )
                except queue.Empty:
                    continue

                if event is None:
                    break

                event_type = getattr(event, 'type', '')

                # Track which tool is being called
                if event_type == 'content_block_start':
                    cb = getattr(event, 'content_block', None)
                    if cb and hasattr(cb, 'name'):
                        current_tool_name = cb.name
                        logger.debug(f"[stream] Tool started: {current_tool_name}")

                elif event_type == 'content_block_delta':
                    delta = getattr(event, 'delta', None)
                    if not delta:
                        continue

                    # Direct text delta (non-tool response or web search result)
                    if hasattr(delta, 'text'):
                        text_started = True
                        yield {"type": "text_delta", "text": delta.text}

                    # Tool input JSON delta — stream respond_text incrementally
                    # The LLM builds JSON like {"response": "text here..."}.
                    # partial_json chunks are raw JSON fragments with escapes
                    # (\" for ", \\n for \n, etc). We decode them on the fly.
                    elif hasattr(delta, 'partial_json') and current_tool_name == 'respond_text':
                        chunk = delta.partial_json
                        respond_text_json += chunk

                        if not respond_text_streaming:
                            # Wait for the opening of the response value
                            # Format: {"response": "...text..."}
                            marker = '"response": "'
                            pos = respond_text_json.find(marker)
                            if pos >= 0:
                                respond_text_streaming = True
                                # Emit any text after the marker in this chunk
                                after = respond_text_json[pos + len(marker):]
                                if after:
                                    decoded = after.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                                    if decoded:
                                        text_started = True
                                        yield {"type": "text_delta", "text": decoded}
                        else:
                            # Decode JSON string escapes in the chunk
                            decoded = chunk.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')
                            text_started = True
                            yield {"type": "text_delta", "text": decoded}

                elif event_type == 'content_block_stop':
                    # For respond_text, the accumulated JSON may have trailing "}
                    # Parse the complete JSON and verify we got the right text
                    if respond_text_streaming and respond_text_json:
                        try:
                            import json as json_mod
                            parsed = json_mod.loads(respond_text_json)
                            # The properly decoded text — replaces any streaming artifacts
                            proper_text = parsed.get('response', '')
                            if proper_text:
                                # Emit a "replace" event so frontend uses the clean version
                                yield {"type": "text_replace", "text": proper_text}
                        except Exception:
                            pass  # Streaming chunks were good enough
                        respond_text_json = ""
                        respond_text_streaming = False
                    current_tool_name = None

            if error_holder:
                err = error_holder[0]
                retries = retry_count_holder[0]
                logger.error(
                    f"[MrCallAgent.stream] Failed after {retries} attempts: {err}"
                )

                # Log error to database
                await log_error(
                    error=err,
                    owner_id=self.owner_id,
                    business_id=self.business_id,
                    session_id=getattr(self, '_session_id', None),
                    context={"model": model, "retries": retries},
                )

                # Generate user-friendly message via Haiku
                if retries >= MAX_RETRIES:
                    # All retries exhausted — show final fallback with support email
                    user_msg = FINAL_FALLBACK_MESSAGE
                else:
                    user_msg = await humanize_error(err, api_key)

                yield {"type": "text_delta", "text": user_msg}
                yield {"type": "done"}
                return

            thread.join(timeout=5)
            final_message = final_holder[0]

            # Process tool calls from final message (configure_* tools need post-processing)
            if final_message and final_message.stop_reason == "tool_use":
                for block in final_message.content:
                    if hasattr(block, 'input'):
                        if block.name.startswith('configure_'):
                            feature = block.name.replace('configure_', '')
                            result = await self._process_configure(
                                block.input, feature, dry_run=dry_run
                            )
                            yield {"type": "tool_result", "tool_used": block.name, "result": result}
                        # respond_text already streamed above — skip
                        break
            elif not text_started and final_message:
                # Fallback: no text was streamed, extract from final message
                for block in final_message.content:
                    if hasattr(block, 'text') and block.text:
                        yield {"type": "text_delta", "text": block.text}

        except Exception as e:
            logger.error(f"[MrCallAgent.stream] Failed: {e}", exc_info=True)
            yield {"type": "error", "message": f"Stream failed: {str(e)}"}
            return

        yield {"type": "done"}

    async def _call_anthropic(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ):
        """Call Anthropic API directly with native web search + configure tools.

        Uses anthropic SDK directly (not aisuite) to support:
        - web_search_20250305 server tool (Brave Search, handled by Anthropic)
        - Native PDF/image content blocks
        - Proper multi-turn with server tool results

        Returns:
            Anthropic Message response (native SDK object)
        """
        import anthropic
        import asyncio

        # Always use system-level Anthropic key (not user's BYOK or Scaleway key)
        from zylch.config import settings as app_settings
        api_key = app_settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured — required for MrCall agent")
        # self.llm.model may be "anthropic:claude-sonnet-..." or just "claude-sonnet-..."
        # Always use Anthropic model (not the aisuite provider model which could be gpt-4.1)
        model = app_settings.anthropic_model

        client = anthropic.Anthropic(api_key=api_key)

        # Build tools: our configure/respond tools + Anthropic's native web search
        tools = []
        for tool in self.TOOLS:
            tools.append({
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            })
        # Add native web search (server-side, no DuckDuckGo scraping)
        tools.append(ANTHROPIC_WEB_SEARCH_TOOL)

        logger.info(
            f"[MrCallAgent] Calling Anthropic directly: model={model}, "
            f"tools={len(tools)} ({len(self.TOOLS)} custom + 1 web_search), "
            f"messages={len(messages)}"
        )

        # Anthropic SDK is synchronous — run in executor
        def _call():
            return client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

        response = await asyncio.get_event_loop().run_in_executor(None, _call)
        return response

    async def _handle_tool_response(self, response, dry_run: bool = False) -> Dict[str, Any]:
        """Handle the LLM's tool response.

        Args:
            response: LLMResponse from create_message
            dry_run: If True, don't apply configure changes to StarChat

        Returns:
            Dict with tool_used, tool_input, and processed result
        """
        logger.info(f"[MrCallAgent] _handle_tool_response: stop_reason={response.stop_reason}")

        result = {
            'tool_used': None,
            'tool_input': {},
            'result': None,
            'error': None
        }

        if response.stop_reason == "tool_use":
            for block in response.content:
                if hasattr(block, 'input'):  # ToolUseBlock
                    result['tool_used'] = block.name
                    result['tool_input'] = block.input
                    logger.info(f"[MrCallAgent] Processing tool: {block.name}")
                    logger.debug(f"[MrCallAgent] Tool input: {block.input}")

                    # Process based on tool
                    if block.name.startswith('configure_'):
                        feature = block.name.replace('configure_', '')
                        logger.info(f"[MrCallAgent] Calling _process_configure for {feature}")
                        result['result'] = await self._process_configure(
                            block.input, feature, dry_run=dry_run
                        )
                    elif block.name == 'respond_text':
                        logger.info("[MrCallAgent] respond_text tool used")
                        result['result'] = {
                            'response': block.input.get('response', '')
                        }
                    else:
                        logger.warning(f"[MrCallAgent] Unknown tool: {block.name}")
                    break
        else:
            # No custom tool called — extract all text blocks.
            # With native web search, Anthropic may return:
            #   [web_search_tool_use, web_search_tool_result, text]
            # We collect all text blocks into the response.
            logger.info("[MrCallAgent] No custom tool_use, extracting text response")
            text_parts = []
            for block in response.content:
                if hasattr(block, 'text') and block.text:
                    text_parts.append(block.text)
            if text_parts:
                result['tool_used'] = 'respond_text'
                result['result'] = {'response': "\n\n".join(text_parts)}
                logger.debug(
                    f"[MrCallAgent] Text response from {len(text_parts)} blocks, "
                    f"total {sum(len(t) for t in text_parts)} chars"
                )

        logger.info(f"[MrCallAgent] _handle_tool_response result: tool_used={result['tool_used']}, has_result={result['result'] is not None}, error={result.get('error')}")
        return result

    async def _process_configure(
        self,
        tool_input: Dict[str, Any],
        feature: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Process configure_* tool by updating variables via StarChat.

        Args:
            tool_input: Tool input with 'changes' dict
            feature: Feature name for validation
            dry_run: If True, validate and summarize but don't call StarChat

        Returns:
            Dict with success status and updated variables
        """
        logger.info(f"[MrCallAgent] _process_configure: feature={feature}, dry_run={dry_run}, tool_input={tool_input}")

        changes = tool_input.get('changes', {})
        logger.info(f"[MrCallAgent] Changes to apply: {list(changes.keys())}")

        if not changes:
            logger.warning("[MrCallAgent] No changes specified in tool_input")
            return {'success': False, 'error': 'No changes specified'}

        if not dry_run and not self.starchat:
            logger.error("[MrCallAgent] StarChat client not available")
            return {'success': False, 'error': 'StarChat client not available'}

        # Validate variables belong to this feature
        valid_vars = set(MrCallConfiguratorTrainer.FEATURES.get(feature, {}).get('variables', []))
        logger.debug(f"[MrCallAgent] Valid variables for {feature}: {valid_vars}")

        invalid_vars = [v for v in changes.keys() if v not in valid_vars]
        if invalid_vars:
            logger.warning(f"[MrCallAgent] Invalid variables: {invalid_vars}")
            return {
                'success': False,
                'error': f'Invalid variables for {feature}: {invalid_vars}'
            }

        # Dry run: validate + return pending changes without calling StarChat
        if dry_run:
            from zylch.agents.mrcall_variable_validator import validate_variable_value
            schema = getattr(self, '_cached_schema', {})

            pending = []
            validation_errors = []
            for var, val in changes.items():
                valid, error_msg = validate_variable_value(var, val, schema)
                if not valid:
                    validation_errors.append(f"{var}: {error_msg}")
                else:
                    pending.append({"variable_name": var, "new_value": val, "feature": feature})

            if validation_errors:
                logger.warning(f"[MrCallAgent] dry_run validation errors: {validation_errors}")
                return {
                    'success': False,
                    'error': "Invalid values:\n" + "\n".join(validation_errors),
                    'dry_run': True,
                }

            logger.info(f"[MrCallAgent] dry_run: {len(pending)} pending changes for {feature}")
            final_result = {
                'success': True,
                'dry_run': True,
                'pending_changes': pending,
                'feature': feature
            }
            # Still generate human-friendly summary
            final_result['response_text'] = await self._summarize_changes(feature, changes)
            return final_result

        # Update each variable via StarChat
        updated = []
        errors = []

        # Validate values against schema types before writing
        from zylch.agents.mrcall_variable_validator import validate_variable_value
        schema = getattr(self, '_cached_schema', {})

        for var_name, new_value in changes.items():
            logger.info(f"[MrCallAgent] Updating {var_name} to: {new_value[:100]}{'...' if len(new_value) > 100 else ''}")

            # Type validation — reject invalid values before they reach StarChat
            valid, error_msg = validate_variable_value(var_name, new_value, schema)
            if not valid:
                logger.warning(f"[MrCallAgent] Validation failed for {var_name}: {error_msg}")
                errors.append(f"{var_name}: {error_msg}")
                continue

            try:
                result = await self.starchat.update_business_variable(
                    self.business_id,
                    var_name,
                    new_value
                )
                logger.info(f"[MrCallAgent] update_business_variable result for {var_name}: {result.get('result', {}).get('variables', {}).get(var_name, 'variable not found')}")
                if result is not None:
                    updated.append(f"{var_name}={new_value}")
                    logger.info(f"[MrCallAgent] Successfully updated {var_name}")
                else:
                    errors.append(f"Failed to update {var_name}")
                    logger.warning(f"[MrCallAgent] update_business_variable returned None for {var_name}")
            except Exception as e:
                errors.append(f"{var_name}: {str(e)}")
                logger.error(f"[MrCallAgent] Error updating {var_name}: {e}", exc_info=True)

        final_result = {
            'success': len(errors) == 0,
            'updated': updated,
            'errors': errors if errors else None,
            'feature': feature
        }
        logger.info(f"[MrCallAgent] _process_configure final result: {final_result}")

        # Generate human-friendly summary via a second LLM call
        if final_result['success'] and updated:
            summary = await self._summarize_changes(feature, changes)
            final_result['response_text'] = summary

            # Persist configuration decision as entity memory
            from zylch.agents.mrcall_memory import save_config_memory
            save_config_memory(self.owner_id, self.business_id, feature, summary)

        return final_result

    async def _summarize_changes(
        self, feature: str, changes: Dict[str, str]
    ) -> str:
        """Generate a human-friendly summary of configuration changes.

        Makes a lightweight LLM call to translate raw variable changes
        into a message the user can understand.

        Args:
            feature: Feature name (e.g. 'welcome_inbound')
            changes: Dict of variable_name -> new_value

        Returns:
            Human-readable summary string
        """
        feature_display = feature.replace('_', ' ').title()

        # Build a concise description of what changed
        changes_desc = "\n".join(
            f"- {var_name}: {value}" for var_name, value in changes.items()
        )

        prompt = f"""You just updated the "{feature_display}" configuration for a MrCall AI phone assistant.

The following variables were changed:
{changes_desc}

Write a SHORT, friendly confirmation message (2-4 sentences max) for the business owner explaining what was changed in plain language. Do NOT show variable names or technical details. Just explain the effect on how their assistant will behave.

Examples of good responses:
- "Done! Your assistant will now greet callers with a more formal tone, introducing itself as the reception of Mario's Restaurant."
- "Got it! Booking is now enabled with 30-minute appointment slots, available Monday through Friday from 9 AM to 5 PM."
- "Updated! After each call, callers will receive a WhatsApp message thanking them and providing your business address."

Write ONLY the confirmation message, nothing else."""

        try:
            response = await self.llm.create_message(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            for block in response.content:
                if hasattr(block, 'text'):
                    logger.info(f"[MrCallAgent] Summary generated: {block.text}")
                    return block.text
        except Exception as e:
            logger.warning(f"[MrCallAgent] Summary generation failed: {e}")

        # Fallback: simple confirmation
        return f"{feature_display} updated successfully."

    # _process_get_config removed — raw variable dumps are not user-friendly.
    # Users who need raw values use StarChat directly.
    # "how does it greet callers?" etc. goes through respond_text.
