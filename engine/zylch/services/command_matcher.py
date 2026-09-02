"""
Semantic Command Matcher

Matches natural language to slash commands with parameter extraction.
Uses the TriggerParser for semantic matching and typed parameter extraction.

Example:
    "sync the last 12 days" → "/sync 12"
    "who is Mario Rossi" → "/memory --search Mario Rossi"
    "show me 5 drafts" → "/email --list --draft --limit 5"
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import re

import numpy as np

from zylch.services.command_handlers import COMMAND_PATTERNS

logger = logging.getLogger(__name__)


def _clean_template(template: str) -> str:
    """Strip parameter types for embedding ("{limit:int}" -> "limit").

    Comparing "show 5 drafts" against "show drafts" matches better than
    against "show {limit:int} drafts".
    """
    return re.sub(r"\{([^:}]+)(?::[^}]+)?\}", r"\1", template)


@dataclass
class TemplateIndex:
    """The encoded command templates, computed once per process.

    `commands` and `templates` are parallel to the rows of `matrix`,
    which holds L2-normalized embeddings so a match is one dot product
    against the user's (also normalized) message embedding.
    """

    commands: List[str]
    templates: List[str]
    matrix: "np.ndarray"


@dataclass
class MatchResult:
    """Result of a semantic match."""

    command: str
    confidence: float
    matched_template: str
    params: Dict[str, Any]


class SemanticCommandMatcher:
    """
    Matches natural language input to slash commands.

    Uses semantic embeddings to find the best matching command pattern,
    then extracts typed parameters and formats the final command string.
    """

    # Minimum confidence for a match
    MIN_CONFIDENCE = 0.70

    # The encoded templates are constant for the life of the process, so
    # they are cached on the class: a matcher instance built per chat
    # turn still pays the encoding once, keyed by embedding model.
    _template_index: Dict[tuple, TemplateIndex] = {}
    _template_index_lock = threading.Lock()

    def __init__(self):
        """Initialize the matcher with lazy-loaded embedding engine."""
        self._embedding_engine = None
        self._initialized = False
        self._index: Optional[TemplateIndex] = None

    def _ensure_initialized(self):
        """Lazy initialization of the embedding engine and template index."""
        if self._initialized:
            return

        try:
            logger.info("[CommandMatcher] Initializing SemanticCommandMatcher...")
            from zylch.memory import MemoryConfig, engine_cache_key, get_shared_engine

            config = MemoryConfig()
            self._embedding_engine = get_shared_engine(config)
            logger.info("[CommandMatcher] EmbeddingEngine ready (shared)")

            self._index = self._ensure_template_index(
                engine_cache_key(config), self._embedding_engine
            )

            self._initialized = True
            logger.info(
                f"[CommandMatcher] SemanticCommandMatcher initialized with {len(COMMAND_PATTERNS)} patterns"
            )
        except Exception as e:
            logger.error(f"[CommandMatcher] Failed to initialize: {e}", exc_info=True)
            self._initialized = False

    @classmethod
    def _ensure_template_index(cls, cache_key: tuple, engine) -> TemplateIndex:
        """Encode every command template once, in a single batch.

        Encoding the 200-odd templates one at a time on every `match()`
        was the bulk of a chat turn's preamble. They never change, so
        they are encoded once per process and reused.

        Args:
            cache_key: The engine identity the vectors belong to — the
                same key `memory.get_shared_engine` caches under, so the
                templates can never outlive the engine that produced
                them.
            engine: The embedding engine to encode with.

        Returns:
            The cached `TemplateIndex` for that engine.
        """
        with cls._template_index_lock:
            index = cls._template_index.get(cache_key)
            if index is not None:
                return index

            commands: List[str] = []
            templates: List[str] = []
            cleaned: List[str] = []
            for command, command_templates in COMMAND_PATTERNS.items():
                for template in command_templates:
                    commands.append(command)
                    templates.append(template)
                    cleaned.append(_clean_template(template))

            matrix = np.asarray(engine.encode(cleaned), dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix = matrix / norms

            index = TemplateIndex(commands=commands, templates=templates, matrix=matrix)
            cls._template_index[cache_key] = index
            logger.info(
                f"[CommandMatcher] encoded {len(templates)} templates "
                f"(engine={cache_key}, one batch)"
            )
            return index

    @classmethod
    def reset_template_index(cls) -> None:
        """Drop the encoded templates. For tests only."""
        with cls._template_index_lock:
            cls._template_index.clear()

    def _best_template(self, user_embedding) -> Tuple[float, Optional[str], Optional[str]]:
        """Score the user's embedding against every template.

        Args:
            user_embedding: Embedding of the user's message.

        Returns:
            ``(score, command, template)`` for the best row, or
            ``(-1.0, None, None)`` when there is no index to score
            against.
        """
        index = self._index
        if index is None or not index.templates:
            return (-1.0, None, None)

        vector = np.asarray(user_embedding, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        if norm == 0:
            return (-1.0, None, None)

        scores = index.matrix @ (vector / norm)
        best = int(np.argmax(scores))
        return (float(scores[best]), index.commands[best], index.templates[best])

    def match(self, user_message: str) -> Optional[str]:
        """
        Match user message to a slash command.

        Args:
            user_message: Natural language input from user

        Returns:
            Formatted command string (e.g., "/sync 12") or None if no match
        """
        self._ensure_initialized()

        if not self._embedding_engine:
            logger.warning("[CommandMatcher] Engine not initialized, returning None")
            return None

        # 1. Embed user message
        try:
            user_embedding = self._embedding_engine.encode(user_message)
        except Exception as e:
            logger.error(f"[CommandMatcher] Embedding failed: {e}")
            return None

        # 2. Find best match among all patterns (one dot product against
        #    the pre-encoded template matrix)
        try:
            best_score, best_command, best_template = self._best_template(user_embedding)
        except Exception as e:
            logger.error(f"[CommandMatcher] Scoring failed: {e}", exc_info=True)
            return None

        if not best_command or best_score < self.MIN_CONFIDENCE:
            logger.info(
                f"[CommandMatcher] No match or low confidence ({best_score:.2f}) for: '{user_message}'"
            )
            return None

        # 3. Extract parameters
        params = self._extract_params(user_message, best_template)

        result = MatchResult(
            command=best_command,
            confidence=best_score,
            matched_template=best_template,
            params=params,
        )

        logger.info(
            f"[CommandMatcher] Raw match: command={result.command}, confidence={result.confidence:.2f}, template='{result.matched_template}'"
        )

        # Format the command with extracted parameters. A formatter returns
        # None when it cannot express the message faithfully as a slash
        # command; a rewrite that means something else is worse than none.
        command = self._format_command(result, user_message)
        if not command:
            logger.info(
                f"[CommandMatcher] Declining rewrite of '{user_message}' "
                f"(template='{best_template}'): parameters could not be recovered"
            )
            return None

        logger.info(
            f"Semantic match: '{user_message}' → '{command}' "
            f"(confidence={result.confidence:.2f}, template='{result.matched_template}')"
        )

        return command

    def _extract_params(self, user_message: str, template: str) -> Dict[str, Any]:
        """
        Extract parameters from user message based on template variables.
        Simple heuristic extraction since we don't have a rigid parser.

        Supported types in template: {name:type}
        - int: Extract numbers
        - email: Extract emails
        - date: Extract date-like strings (simplified)
        - text: Catch-all
        """
        params = {}

        # Find all typed variables in template: {param:type}
        var_matches = re.findall(r"\{([^:}]+):([^}]+)\}", template)

        for var_name, var_type in var_matches:
            val = None
            if var_type == "int":
                # Find first number
                match = re.search(r"\b(\d+)\b", user_message)
                if match:
                    val = match.group(1)
            elif var_type == "email":
                # Find email
                match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", user_message)
                if match:
                    val = match.group(0)
            elif var_type == "date":
                # Very basic date extraction - looking for common patterns
                # In a real system this would use dateparser
                match = re.search(
                    r"\b(today|tomorrow|yesterday|\d{4}-\d{2}-\d{2})\b", user_message.lower()
                )
                if match:
                    val = match.group(0)
            elif var_type == "time":
                match = re.search(r"\b(\d{1,2}:\d{2}(?:\s?[ap]m)?)\b", user_message.lower())
                if match:
                    val = match.group(0)
            elif var_type == "duration":
                match = re.search(
                    r"\b(\d+\s*(?:minutes?|hours?|days?|mins?|hrs?))\b", user_message.lower()
                )
                if match:
                    val = match.group(0)
            elif var_type == "text":
                # Hard to extract "rest of text" without alignment
                # For now, if it's a named entity like query/content, take the whole message
                # minus the known trigger words, or just specific logic in _format_command
                pass

            if val:
                params[var_name] = val

        return params

    def _format_command(self, result: MatchResult, original_input: str) -> Optional[str]:
        """
        Format a MatchResult into a command string.

        Handles different command patterns:
        - /sync {days} → "/sync 12"
        - /memory --search {query} → "/memory --search Mario Rossi"
        - /email --list --draft --limit {limit} → "/email --list --draft --limit 5"

        Args:
            result: The match result with command and params
            original_input: The original user input (for --search full message)

        Returns:
            Formatted command string, or None when the message cannot be
            expressed as a slash command without changing what it asks for
        """
        command = result.command
        params = result.params
        template = result.matched_template

        # Special handling based on command type
        if command == "/sync":
            return self._format_sync(params)
        elif command == "/memory":
            return self._format_memory(params, template, original_input)
        elif command == "/email":
            return self._format_email(params, template)
        elif command == "/calendar":
            return self._format_calendar(params, template)
        elif command == "/model":
            return self._format_model(params)
        elif command == "/archive":
            return self._format_archive(params, template)
        elif command == "/share":
            return self._format_share(params)
        elif command == "/revoke":
            return self._format_revoke(params)
        elif command == "/tutorial":
            return self._format_tutorial(params)
        elif command == "/connect":
            return self._format_connect(params)
        else:
            # Default: just return the command
            return command

    def _format_sync(self, params: Dict[str, Any]) -> str:
        """/sync [--days <n>]"""
        if "days" in params:
            return f"/sync --days {params['days']}"
        return "/sync"

    def _format_memory(self, params: Dict[str, Any], template: str, original_input: str) -> str:
        """/memory [search query | store content | stats | list | reset]"""
        # Determine subcommand from template
        if (
            "search" in template
            or "who is" in template
            or "what do you know" in template
            or "find in memory" in template
        ):
            # Pass the FULL original message as the search query
            return f"/memory search {original_input}"
        elif "store" in template or "remember" in template or "save to memory" in template:
            content = params.get("content", "")
            return f"/memory store {content}"
        elif "stats" in template or "statistics" in template:
            return "/memory stats"
        elif "list" in template or "show memories" in template:
            limit = params.get("limit", "")
            if limit:
                return f"/memory list {limit}"
            return "/memory list"
        elif "reset" in template or "clear memory" in template or "delete all" in template:
            return "/memory reset"

        # Default to search with original input
        return f"/memory search {original_input}"

    def _format_email(self, params: Dict[str, Any], template: str) -> Optional[str]:
        """/email [list --draft | create | send | delete | search]"""
        # Drafts - List
        if "list draft" in template or "show draft" in template or "my draft" in template:
            limit = params.get("limit", "")
            if limit:
                return f"/email list --draft --limit {limit}"
            return "/email list --draft"

        # Drafts - Create
        if (
            "create draft" in template
            or "draft email" in template
            or "compose" in template
            or "write email" in template
        ):
            to = params.get("to", "")
            subject = params.get("subject", "")
            parts = ["/email create"]
            if to:
                parts.append(f"--to {to}")
            if subject:
                parts.append(f'--subject "{subject}"')
            return " ".join(parts)

        # Drafts - Send
        # NOTE: "send it" is intentionally NOT matched here. It's a confirmation
        # phrase that must be interpreted by the LLM via the send_draft tool
        # (see chat_service.py:211). Only a phrase carrying an explicit draft
        # id rewrites to /email send.
        if "send draft" in template or "send the email" in template:
            draft_id = params.get("draft_id", "")
            if draft_id:
                return f"/email send {draft_id}"
            # `_extract_params` cannot pull a {draft_id:text} out of free text,
            # so an id the user DID spell out is lost here. Rewriting to a bare
            # `/email send` would silently turn "send that draft" into "send
            # whichever draft the handler picks" — and the slash-command path
            # skips the tool-approval gate the LLM path goes through. Decline
            # the rewrite instead: the message reaches the LLM, which reads the
            # id from the full text and calls the gated `send_draft`.
            return None

        # Drafts - Delete
        if "delete draft" in template or "discard draft" in template:
            draft_id = params.get("draft_id", "")
            if draft_id:
                return f"/email delete {draft_id}"
            return "/email delete"

        # Search
        if (
            "search" in template
            or "find email" in template
            or "emails from" in template
            or "emails about" in template
        ):
            query = params.get("query", "")
            sender = params.get("sender", "")
            days = params.get("days", "")
            limit = params.get("limit", "")

            parts = ["/email search"]
            if query:
                parts.append(f'"{query}"')
            if sender:
                parts.append(f"--from {sender}")
            if days:
                parts.append(f"--days {days}")
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        # Default to list drafts
        return "/email list --draft"

    def _format_calendar(self, params: Dict[str, Any], template: str) -> str:
        """/calendar [list | create | search]"""
        # List
        if (
            "show calendar" in template
            or "my calendar" in template
            or "calendar for" in template
            or "meetings" in template
            or "events" in template
            or "what's on" in template
        ):
            date = params.get("date", "")
            limit = params.get("limit", "")
            parts = ["/calendar list"]
            if date:
                parts.append(f"--date {date}")
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        # Create
        if "create event" in template or "schedule meeting" in template or "add event" in template:
            attendee = params.get("attendee", "")
            date = params.get("date", "")
            time = params.get("time", "")
            title = params.get("title", "")
            parts = ["/calendar create"]
            if title:
                parts.append(f'--title "{title}"')
            if attendee:
                parts.append(f"--attendee {attendee}")
            if date:
                parts.append(f"--date {date}")
            if time:
                parts.append(f"--time {time}")
            return " ".join(parts)

        # Search
        if "search calendar" in template or "find meeting" in template or "when is" in template:
            query = params.get("query", "")
            attendee = params.get("attendee", "")
            if query:
                return f'/calendar search "{query}"'
            if attendee:
                return f"/calendar search {attendee}"
            return "/calendar search"

        return "/calendar list"

    def _format_model(self, params: Dict[str, Any]) -> str:
        """/model"""
        model = params.get("model", "")
        if model:
            return f"/model {model}"
        return "/model"

    def _format_archive(self, params: Dict[str, Any], template: str) -> str:
        """/archive [stats | search query | list]"""
        if "search" in template or "find" in template:
            query = params.get("query", "")
            limit = params.get("limit", "")
            parts = ["/archive search"]
            if query:
                parts.append(f'"{query}"')
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        if "stats" in template or "statistics" in template:
            return "/archive stats"

        limit = params.get("limit", "")
        if limit:
            return f"/archive list --limit {limit}"

        return "/archive stats"

    def _format_share(self, params: Dict[str, Any]) -> str:
        """/share [email]"""
        email = params.get("email", "")
        name = params.get("name", "")
        if email:
            return f"/share {email}"
        if name:
            return f"/share {name}"
        return "/share"

    def _format_revoke(self, params: Dict[str, Any]) -> str:
        """/revoke [email]"""
        email = params.get("email", "")
        if email:
            return f"/revoke {email}"
        return "/revoke"

    def _format_tutorial(self, params: Dict[str, Any]) -> str:
        """/tutorial [topic]"""
        topic = params.get("topic", "")
        if topic:
            return f"/tutorial {topic}"
        return "/tutorial"

    def _format_connect(self, params: Dict[str, Any]) -> str:
        """/connect [provider]"""
        provider = params.get("provider", "")
        if provider:
            return f"/connect {provider}"
        return "/connect"
