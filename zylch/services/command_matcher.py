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
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple
import re

from zylch.services.command_handlers import COMMAND_PATTERNS

logger = logging.getLogger(__name__)


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

    def __init__(self):
        """Initialize the matcher with lazy-loaded embedding engine."""
        self._embedding_engine = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of the embedding engine."""
        if self._initialized:
            return

        try:
            logger.info("[CommandMatcher] Initializing SemanticCommandMatcher...")
            from zylch.memory import EmbeddingEngine, MemoryConfig
            config = MemoryConfig()
            self._embedding_engine = EmbeddingEngine(config)
            logger.info("[CommandMatcher] EmbeddingEngine created")
            
            self._initialized = True
            logger.info(f"[CommandMatcher] SemanticCommandMatcher initialized with {len(COMMAND_PATTERNS)} patterns")
        except Exception as e:
            logger.error(f"[CommandMatcher] Failed to initialize: {e}", exc_info=True)
            self._initialized = False

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
            user_embedding = self._embedding_engine.embed_text(user_message)
        except Exception as e:
            logger.error(f"[CommandMatcher] Embedding failed: {e}")
            return None

        # 2. Find best match among all patterns
        best_score = -1.0
        best_command = None
        best_template = None

        # Iterate through all commands and their patterns
        for command, templates in COMMAND_PATTERNS.items():
            for template in templates:
                # Remove parameter types for embedding comparison (e.g. "{limit:int}" -> "limit")
                # This makes "show 5 drafts" match better with "show drafts" semantically
                clean_template = re.sub(r'\{([^:}]+)(?::[^}]+)?\}', r'\1', template)
                
                try:
                    template_embedding = self._embedding_engine.embed_text(clean_template)
                    score = self._embedding_engine.cosine_similarity(user_embedding, template_embedding)
                    
                    if score > best_score:
                        best_score = score
                        best_command = command
                        best_template = template
                except Exception:
                    continue

        if not best_command or best_score < self.MIN_CONFIDENCE:
            logger.info(f"[CommandMatcher] No match or low confidence ({best_score:.2f}) for: '{user_message}'")
            return None

        # 3. Extract parameters
        params = self._extract_params(user_message, best_template)

        result = MatchResult(
            command=best_command,
            confidence=best_score,
            matched_template=best_template,
            params=params
        )

        logger.info(f"[CommandMatcher] Raw match: command={result.command}, confidence={result.confidence:.2f}, template='{result.matched_template}'")

        # Format the command with extracted parameters
        command = self._format_command(result, user_message)

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
        var_matches = re.findall(r'\{([^:}]+):([^}]+)\}', template)
        
        for var_name, var_type in var_matches:
            val = None
            if var_type == 'int':
                # Find first number
                match = re.search(r'\b(\d+)\b', user_message)
                if match:
                    val = match.group(1)
            elif var_type == 'email':
                # Find email
                match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_message)
                if match:
                    val = match.group(0)
            elif var_type == 'date':
                # Very basic date extraction - looking for common patterns
                # In a real system this would use dateparser
                match = re.search(r'\b(today|tomorrow|yesterday|\d{4}-\d{2}-\d{2})\b', user_message.lower())
                if match:
                    val = match.group(0)
            elif var_type == 'time':
                match = re.search(r'\b(\d{1,2}:\d{2}(?:\s?[ap]m)?)\b', user_message.lower())
                if match:
                    val = match.group(0)
            elif var_type == 'duration':
                match = re.search(r'\b(\d+\s*(?:minutes?|hours?|days?|mins?|hrs?))\b', user_message.lower())
                if match:
                    val = match.group(0)
            elif var_type == 'text':
                # Hard to extract "rest of text" without alignment
                # For now, if it's a named entity like query/content, take the whole message 
                # minus the known trigger words, or just specific logic in _format_command
                pass
                
            if val:
                params[var_name] = val
                
        return params

    def _format_command(self, result: MatchResult, original_input: str) -> str:
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
            Formatted command string
        """
        command = result.command
        params = result.params
        template = result.matched_template

        # Special handling based on command type
        if command == '/sync':
            return self._format_sync(params)
        elif command == '/memory':
            return self._format_memory(params, template, original_input)
        elif command == '/email':
            return self._format_email(params, template)
        elif command == '/calendar':
            return self._format_calendar(params, template)
        elif command == '/reminder':
            return self._format_reminder(params, template)
        elif command == '/model':
            return self._format_model(params)
        elif command == '/archive':
            return self._format_archive(params, template)
        elif command == '/trigger':
            return self._format_trigger(params, template)
        elif command == '/share':
            return self._format_share(params)
        elif command == '/revoke':
            return self._format_revoke(params)
        elif command == '/tutorial':
            return self._format_tutorial(params)
        elif command == '/connect':
            return self._format_connect(params)
        elif command == '/mrcall':
            return self._format_mrcall(params, template)
        else:
            # Default: just return the command
            return command

    def _format_sync(self, params: Dict[str, Any]) -> str:
        """/sync [--days <n>]"""
        if 'days' in params:
            return f"/sync --days {params['days']}"
        return "/sync"

    def _format_memory(self, params: Dict[str, Any], template: str, original_input: str) -> str:
        """/memory [--search query | --store content | --stats | --list | --reset]"""
        # Determine subcommand from template
        if 'search' in template or 'who is' in template or 'what do you know' in template or 'find in memory' in template:
            # Pass the FULL original message as the search query
            # This way "who is Mario Rossi" becomes "--search who is Mario Rossi"
            return f"/memory --search {original_input}"
        elif 'store' in template or 'remember' in template or 'save to memory' in template:
            content = params.get('content', '')
            return f"/memory --store {content}"
        elif 'stats' in template or 'statistics' in template:
            return "/memory --stats"
        elif 'list' in template or 'show memories' in template:
            limit = params.get('limit', '')
            if limit:
                return f"/memory --list {limit}"
            return "/memory --list"
        elif 'reset' in template or 'clear memory' in template or 'delete all' in template:
            return "/memory --reset"

        # Default to search with original input
        return f"/memory --search {original_input}"

    def _format_email(self, params: Dict[str, Any], template: str) -> str:
        """/email [--list --draft | --create | --send | --delete | --search]"""
        # Drafts - List
        if 'list draft' in template or 'show draft' in template or 'my draft' in template:
            limit = params.get('limit', '')
            if limit:
                return f"/email --list --draft --limit {limit}"
            return "/email --list --draft"

        # Drafts - Create
        if 'create draft' in template or 'draft email' in template or 'compose' in template or 'write email' in template:
            to = params.get('to', '')
            subject = params.get('subject', '')
            parts = ["/email --create"]
            if to:
                parts.append(f"--to {to}")
            if subject:
                parts.append(f"--subject \"{subject}\"")
            return " ".join(parts)

        # Drafts - Send
        if 'send draft' in template or 'send the email' in template or 'send it' in template:
            draft_id = params.get('draft_id', '')
            if draft_id:
                return f"/email send {draft_id}"
            return "/email send"

        # Drafts - Delete
        if 'delete draft' in template or 'discard draft' in template:
            draft_id = params.get('draft_id', '')
            if draft_id:
                return f"/email delete {draft_id}"
            return "/email delete"

        # Search
        if 'search' in template or 'find email' in template or 'emails from' in template or 'emails about' in template:
            query = params.get('query', '')
            sender = params.get('sender', '')
            days = params.get('days', '')
            limit = params.get('limit', '')

            parts = ["/email --search"]
            if query:
                parts.append(f"\"{query}\"")
            if sender:
                parts.append(f"--from {sender}")
            if days:
                parts.append(f"--days {days}")
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        # Default to list drafts
        return "/email --list --draft"

    def _format_calendar(self, params: Dict[str, Any], template: str) -> str:
        """/calendar [--list | --create | --search]"""
        # List
        if 'show calendar' in template or 'my calendar' in template or 'calendar for' in template or 'meetings' in template or 'events' in template or 'what\'s on' in template:
            date = params.get('date', '')
            limit = params.get('limit', '')
            parts = ["/calendar --list"]
            if date:
                parts.append(f"--date {date}")
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        # Create
        if 'create event' in template or 'schedule meeting' in template or 'add event' in template:
            attendee = params.get('attendee', '')
            date = params.get('date', '')
            time = params.get('time', '')
            title = params.get('title', '')
            parts = ["/calendar --create"]
            if title:
                parts.append(f"--title \"{title}\"")
            if attendee:
                parts.append(f"--attendee {attendee}")
            if date:
                parts.append(f"--date {date}")
            if time:
                parts.append(f"--time {time}")
            return " ".join(parts)

        # Search
        if 'search calendar' in template or 'find meeting' in template or 'when is' in template:
            query = params.get('query', '')
            attendee = params.get('attendee', '')
            if query:
                return f"/calendar --search \"{query}\""
            if attendee:
                return f"/calendar --search {attendee}"
            return "/calendar --search"

        return "/calendar --list"

    def _format_reminder(self, params: Dict[str, Any], template: str) -> str:
        """/reminder [--set | --list | --cancel]"""
        # List
        if 'list reminder' in template or 'show reminder' in template:
            return "/reminder --list"

        # Cancel
        if 'cancel reminder' in template:
            reminder_id = params.get('reminder_id', '')
            if reminder_id:
                return f"/reminder --cancel {reminder_id}"
            return "/reminder --cancel"

        # Set (default)
        duration = params.get('duration', '')
        time = params.get('time', '')
        date = params.get('date', '')
        task = params.get('task', '')

        parts = ["/reminder --set"]
        if duration:
            parts.append(f"--in \"{duration}\"")
        if time:
            parts.append(f"--at {time}")
        if date:
            parts.append(f"--on {date}")
        if task:
            parts.append(f"--task \"{task}\"")
        return " ".join(parts)

    def _format_model(self, params: Dict[str, Any]) -> str:
        """/model [haiku|sonnet|opus]"""
        model = params.get('model', '')
        if model:
            return f"/model {model}"
        return "/model"

    def _format_archive(self, params: Dict[str, Any], template: str) -> str:
        """/archive [--stats | --search query]"""
        if 'search' in template or 'find' in template:
            query = params.get('query', '')
            limit = params.get('limit', '')
            parts = ["/archive --search"]
            if query:
                parts.append(f"\"{query}\"")
            if limit:
                parts.append(f"--limit {limit}")
            return " ".join(parts)

        if 'stats' in template or 'statistics' in template:
            return "/archive --stats"

        limit = params.get('limit', '')
        if limit:
            return f"/archive --list --limit {limit}"

        return "/archive --stats"

    def _format_trigger(self, params: Dict[str, Any], template: str) -> str:
        """/trigger [--list | --add | --remove id]"""
        if 'list' in template or 'show' in template:
            return "/trigger --list"
        if 'remove' in template or 'delete' in template:
            trigger_id = params.get('trigger_id', '')
            if trigger_id:
                return f"/trigger --remove {trigger_id}"
            return "/trigger --remove"
        return "/trigger --list"

    def _format_share(self, params: Dict[str, Any]) -> str:
        """/share [email]"""
        email = params.get('email', '')
        name = params.get('name', '')
        if email:
            return f"/share {email}"
        if name:
            return f"/share {name}"
        return "/share"

    def _format_revoke(self, params: Dict[str, Any]) -> str:
        """/revoke [email]"""
        email = params.get('email', '')
        if email:
            return f"/revoke {email}"
        return "/revoke"

    def _format_tutorial(self, params: Dict[str, Any]) -> str:
        """/tutorial [topic]"""
        topic = params.get('topic', '')
        if topic:
            return f"/tutorial {topic}"
        return "/tutorial"

    def _format_connect(self, params: Dict[str, Any]) -> str:
        """/connect [provider]"""
        provider = params.get('provider', '')
        if provider:
            return f"/connect {provider}"
        return "/connect"

    def _format_mrcall(self, params: Dict[str, Any], template: str) -> str:
        """/mrcall variables get [--name <name>]"""
        if 'variable' in template or 'value' in template:
            name = params.get('name', '')
            if name:
                return f"/mrcall variables get --name {name}"
            return "/mrcall variables get"
        return "/mrcall"
