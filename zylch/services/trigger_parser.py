"""
Trigger Parser for Typed Parameter Extraction

This module provides HYBRID matching of natural language to command triggers,
combining keyword overlap (FTS-style) with semantic similarity - the same
pattern used for memory blob search.

Hybrid score = alpha * keyword_overlap + (1-alpha) * semantic_similarity

Supported parameter types:
    int      - integers (e.g., "12", "5", "100")
    email    - email addresses (e.g., "mario@example.com")
    text     - free text, greedy (e.g., "the project update")
    date     - date expressions (e.g., "tomorrow", "next monday", "March 5")
    time     - time expressions (e.g., "3pm", "15:30", "noon")
    duration - duration expressions (e.g., "30 minutes", "2 hours")
    model    - AI model names (e.g., "haiku", "sonnet", "opus")

Usage:
    parser = TriggerParser(embedding_engine)
    result = parser.match("show me the last 12 drafts")
    # result = MatchResult(command='/email', params={'limit': 12}, confidence=0.92)
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of a trigger match."""
    command: str
    params: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    matched_template: str = ""


@dataclass
class ParsedTemplate:
    """A parsed trigger template with extracted slot information."""
    original: str           # "show the last {limit:int} drafts"
    stripped: str           # "show the last drafts"
    slots: List[Dict]       # [{"name": "limit", "type": "int", "position": 14}]


class TriggerParser:
    """
    Semantic trigger parser with typed parameter extraction.

    Uses embeddings to match user input to trigger templates,
    then extracts typed parameters from the input.
    """

    # Regex pattern to find {param:type} slots
    SLOT_PATTERN = re.compile(r'\{(\w+):(\w+)\}')

    # Type extractors - each returns (value, consumed_text) or None
    TYPE_EXTRACTORS = {
        'int': '_extract_int',
        'email': '_extract_email',
        'text': '_extract_text',
        'date': '_extract_date',
        'time': '_extract_time',
        'duration': '_extract_duration',
        'model': '_extract_model',
    }

    # Minimum confidence threshold for a match
    MIN_CONFIDENCE = 0.65

    # Default alpha for hybrid scoring
    # alpha=0.3 means 70% keyword weight, 30% semantic weight
    # Higher keyword weight helps when user input closely matches trigger patterns
    DEFAULT_ALPHA = 0.3

    def __init__(self, embedding_engine, triggers: Dict[str, List[str]], alpha: float = None):
        """
        Initialize the trigger parser.

        Args:
            embedding_engine: Engine with encode() method for semantic matching
            triggers: Dict mapping commands to list of trigger templates
            alpha: FTS/keyword weight (0-1). Default 0.5 for balanced hybrid.
        """
        self.embedding_engine = embedding_engine
        self.triggers = triggers
        self.alpha = alpha if alpha is not None else self.DEFAULT_ALPHA
        self._parsed_templates: Dict[str, List[ParsedTemplate]] = {}
        self._template_embeddings: Dict[str, List[Tuple[str, Any]]] = {}
        self._template_keywords: Dict[str, List[Tuple[str, set]]] = {}  # For keyword matching
        self._initialized = False

    def initialize(self):
        """Parse templates, compute embeddings, and extract keywords. Call once before matching."""
        if self._initialized:
            return

        logger.info(f"Initializing trigger parser (alpha={self.alpha})...")

        # Parse all templates
        for command, templates in self.triggers.items():
            self._parsed_templates[command] = []
            self._template_embeddings[command] = []
            self._template_keywords[command] = []

            for template in templates:
                parsed = self._parse_template(template)
                self._parsed_templates[command].append(parsed)

                # Compute embedding for stripped template
                embedding = self.embedding_engine.encode(parsed.stripped)
                self._template_embeddings[command].append((template, embedding))

                # Extract keywords for FTS-style matching
                keywords = self._extract_keywords(parsed.stripped)
                self._template_keywords[command].append((template, keywords))

        self._initialized = True
        total = sum(len(t) for t in self._parsed_templates.values())
        logger.info(f"Trigger parser initialized with {total} templates (hybrid mode)")

    def _extract_keywords(self, text: str) -> set:
        """Extract keywords from text for FTS-style matching.

        Removes common stop words and normalizes to lowercase.
        """
        # Common stop words to ignore
        stop_words = {
            'a', 'an', 'the', 'to', 'for', 'of', 'in', 'on', 'at', 'by',
            'and', 'or', 'is', 'are', 'was', 'were', 'be', 'been',
            'my', 'me', 'i', 'you', 'your', 'it', 'this', 'that',
            'with', 'from', 'as', 'what', 'how', 'when', 'where',
            'show', 'get', 'list', 'give', 'tell', 'find',  # Common command verbs
        }

        # Tokenize and filter
        words = re.findall(r'\b[a-z]+\b', text.lower())
        keywords = {w for w in words if w not in stop_words and len(w) > 1}

        return keywords

    def _parse_template(self, template: str) -> ParsedTemplate:
        """Parse a template string to extract slot information."""
        slots = []
        stripped = template

        # Find all slots
        for match in self.SLOT_PATTERN.finditer(template):
            slot_name = match.group(1)
            slot_type = match.group(2)
            slots.append({
                'name': slot_name,
                'type': slot_type,
                'start': match.start(),
                'end': match.end(),
                'pattern': match.group(0),
            })

        # Remove slots from template for embedding
        stripped = self.SLOT_PATTERN.sub('', template)
        # Clean up extra spaces
        stripped = re.sub(r'\s+', ' ', stripped).strip()

        return ParsedTemplate(
            original=template,
            stripped=stripped,
            slots=slots,
        )

    def match(self, user_input: str) -> Optional[MatchResult]:
        """
        Match user input against all triggers using HYBRID scoring.

        Hybrid score = alpha * keyword_overlap + (1-alpha) * semantic_similarity

        Args:
            user_input: The natural language input from user

        Returns:
            MatchResult if a match is found above threshold, None otherwise
        """
        if not self._initialized:
            self.initialize()

        user_input = user_input.strip()
        if not user_input:
            return None

        logger.info(f"[TriggerParser] Matching input: '{user_input}' (alpha={self.alpha})")

        # Compute embedding for user input
        input_embedding = self.embedding_engine.encode(user_input)

        # Extract keywords from user input
        input_keywords = self._extract_keywords(user_input)

        best_match: Optional[MatchResult] = None
        best_score = 0.0
        top_candidates = []  # Track top 5 for debugging

        # Search all commands
        for command, template_embeddings in self._template_embeddings.items():
            template_keywords_list = self._template_keywords[command]

            for i, (template, template_embedding) in enumerate(template_embeddings):
                # Get template keywords
                _, template_keywords = template_keywords_list[i]

                # Compute keyword overlap (FTS-style)
                keyword_score = self._keyword_overlap(input_keywords, template_keywords)

                # Compute semantic similarity
                semantic_score = self._cosine_similarity(input_embedding, template_embedding)

                # Hybrid score
                hybrid_score = self.alpha * keyword_score + (1 - self.alpha) * semantic_score

                # Track top candidates for debugging
                if len(top_candidates) < 5 or hybrid_score > top_candidates[-1][0]:
                    top_candidates.append((hybrid_score, keyword_score, semantic_score, command, template))
                    top_candidates.sort(reverse=True, key=lambda x: x[0])
                    top_candidates = top_candidates[:5]

                if hybrid_score > best_score and hybrid_score >= self.MIN_CONFIDENCE:
                    best_score = hybrid_score

                    # Find the parsed template
                    parsed = next(
                        p for p in self._parsed_templates[command]
                        if p.original == template
                    )

                    # Extract parameters
                    params = self._extract_params(user_input, parsed)

                    best_match = MatchResult(
                        command=command,
                        params=params,
                        confidence=hybrid_score,
                        matched_template=template,
                    )

        # Log top candidates for debugging - use INFO so it actually shows
        logger.info(f"[TriggerParser] Top 5 candidates for '{user_input}':")
        for hybrid, kw, sem, cmd, tmpl in top_candidates:
            logger.info(f"  {hybrid:.3f} (kw={kw:.2f}, sem={sem:.2f}) {cmd}: '{tmpl}'")

        if best_match:
            logger.info(
                f"[TriggerParser] MATCH: '{user_input}' → '{best_match.matched_template}' "
                f"(command={best_match.command}, confidence={best_match.confidence:.2f}, "
                f"params={best_match.params})"
            )
        else:
            logger.info(f"[TriggerParser] No match above threshold {self.MIN_CONFIDENCE} for '{user_input}'")

        return best_match

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math

        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def _keyword_overlap(self, input_keywords: set, template_keywords: set) -> float:
        """Compute keyword overlap score (FTS-style matching).

        Uses Jaccard-like similarity but weighted towards template coverage:
        - If user says "sync", and template is "sync", score = 1.0
        - If user says "sync my emails", and template is "sync", score still high
        - If user says "calendar", and template is "sync", score = 0.0

        Formula: intersection / template_keywords (how much of template is covered)
        With bonus for exact match.
        """
        if not template_keywords:
            return 0.0

        intersection = input_keywords & template_keywords

        if not intersection:
            return 0.0

        # Base score: what fraction of template keywords are in input
        coverage = len(intersection) / len(template_keywords)

        # Bonus for exact/near-exact match (input ≈ template)
        if input_keywords == template_keywords:
            return 1.0

        # Slight penalty if input has many extra keywords (less focused)
        extra_keywords = len(input_keywords - template_keywords)
        if extra_keywords > 0:
            penalty = min(0.1, extra_keywords * 0.02)  # Max 10% penalty
            coverage = max(0, coverage - penalty)

        return coverage

    def _extract_params(self, user_input: str, parsed: ParsedTemplate) -> Dict[str, Any]:
        """
        Extract typed parameters from user input based on template slots.

        Uses type-specific extractors to find values in the input.
        """
        params = {}

        if not parsed.slots:
            return params

        # For each slot, try to extract a value of that type
        for slot in parsed.slots:
            slot_name = slot['name']
            slot_type = slot['type']

            extractor_method = self.TYPE_EXTRACTORS.get(slot_type)
            if not extractor_method:
                logger.warning(f"Unknown slot type: {slot_type}")
                continue

            extractor = getattr(self, extractor_method)
            value = extractor(user_input, parsed, slot)

            if value is not None:
                params[slot_name] = value

        return params

    # --- Type Extractors ---

    def _extract_int(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[int]:
        """Extract an integer from user input."""
        # Find all numbers in the input
        numbers = re.findall(r'\b(\d+)\b', user_input)

        if not numbers:
            return None

        # If multiple numbers, try to pick the right one based on context
        # For now, just return the first one
        # TODO: Use position hints from template to disambiguate
        return int(numbers[0])

    def _extract_email(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """Extract an email address from user input."""
        # Standard email regex
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        matches = re.findall(email_pattern, user_input)

        return matches[0] if matches else None

    def _extract_text(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """
        Extract free text from user input.

        This is greedy - it captures remaining text after removing
        the template's fixed parts.
        """
        # Remove the fixed parts of the template from the input
        # to find what remains as the "text" value

        # Split template into parts before and after the slot
        template = parsed.original
        slot_pattern = slot['pattern']

        parts = template.split(slot_pattern)
        before = parts[0].strip() if parts[0] else ""
        after = parts[1].strip() if len(parts) > 1 and parts[1] else ""

        # Try to find the text between these parts in user input
        text = user_input.lower()

        # Remove the "before" part
        if before:
            # Find where the before text ends (approximately)
            before_words = before.lower().split()
            for word in before_words:
                idx = text.find(word)
                if idx != -1:
                    text = text[idx + len(word):]

        # Remove the "after" part
        if after:
            after_words = after.lower().split()
            for word in reversed(after_words):
                idx = text.rfind(word)
                if idx != -1:
                    text = text[:idx]

        text = text.strip()

        # Return original case from user input if possible
        if text:
            # Find this text in original input
            lower_input = user_input.lower()
            idx = lower_input.find(text)
            if idx != -1:
                return user_input[idx:idx + len(text)].strip()

        return text if text else None

    def _extract_date(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """
        Extract a date expression from user input.

        Returns the date string as-is for further parsing by the command handler.
        Common patterns: "tomorrow", "next monday", "March 5", "2024-03-15"
        """
        # Date keywords and patterns
        date_patterns = [
            r'\b(today)\b',
            r'\b(tomorrow)\b',
            r'\b(yesterday)\b',
            r'\b(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b',
            r'\b(this\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b',
            r'\b((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b',
            r'\b(next\s+week)\b',
            r'\b(this\s+week)\b',
            r'\b(\d{4}-\d{2}-\d{2})\b',  # ISO format
            r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b',  # US format
            r'\b(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{4})?)\b',
            r'\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:\s+\d{4})?)\b',
        ]

        lower_input = user_input.lower()

        for pattern in date_patterns:
            match = re.search(pattern, lower_input, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_time(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """
        Extract a time expression from user input.

        Returns the time string as-is for further parsing.
        Common patterns: "3pm", "15:30", "noon", "3:30 pm"
        """
        time_patterns = [
            r'\b(\d{1,2}:\d{2}\s*(?:am|pm)?)\b',  # 3:30 pm, 15:30
            r'\b(\d{1,2}\s*(?:am|pm))\b',  # 3pm, 3 pm
            r'\b(noon)\b',
            r'\b(midnight)\b',
            r'\b(morning)\b',
            r'\b(afternoon)\b',
            r'\b(evening)\b',
        ]

        lower_input = user_input.lower()

        for pattern in time_patterns:
            match = re.search(pattern, lower_input, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_duration(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """
        Extract a duration expression from user input.

        Returns the duration string as-is for further parsing.
        Common patterns: "30 minutes", "2 hours", "1 day"
        """
        duration_patterns = [
            r'\b(\d+\s*(?:minute|minutes|min|mins))\b',
            r'\b(\d+\s*(?:hour|hours|hr|hrs))\b',
            r'\b(\d+\s*(?:day|days))\b',
            r'\b(\d+\s*(?:week|weeks))\b',
            r'\b(half\s+(?:an?\s+)?hour)\b',
            r'\b(an?\s+hour)\b',
        ]

        lower_input = user_input.lower()

        for pattern in duration_patterns:
            match = re.search(pattern, lower_input, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_model(self, user_input: str, parsed: ParsedTemplate, slot: Dict) -> Optional[str]:
        """
        Extract an AI model name from user input.

        Known models: haiku, sonnet, opus
        """
        model_patterns = [
            r'\b(haiku)\b',
            r'\b(sonnet)\b',
            r'\b(opus)\b',
        ]

        lower_input = user_input.lower()

        for pattern in model_patterns:
            match = re.search(pattern, lower_input, re.IGNORECASE)
            if match:
                return match.group(1).lower()

        return None


# --- Utility functions ---

def parse_date_expression(date_str: str) -> Optional[datetime]:
    """
    Parse a date expression into a datetime object.

    Handles: "today", "tomorrow", "next monday", "March 5", "2024-03-15", etc.
    """
    if not date_str:
        return None

    date_str = date_str.lower().strip()
    now = datetime.now()

    # Relative dates
    if date_str == 'today':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == 'tomorrow':
        return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == 'yesterday':
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Day of week
    days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for i, day in enumerate(days):
        if day in date_str:
            current_day = now.weekday()
            target_day = i

            if 'next' in date_str:
                days_ahead = (target_day - current_day + 7) % 7
                if days_ahead == 0:
                    days_ahead = 7
            else:
                days_ahead = (target_day - current_day + 7) % 7
                if days_ahead == 0:
                    days_ahead = 7

            return (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

    # Try parsing standard formats
    formats = [
        '%Y-%m-%d',
        '%m/%d/%Y',
        '%m/%d/%y',
        '%d/%m/%Y',
        '%d/%m/%y',
        '%B %d',
        '%B %d %Y',
        '%b %d',
        '%b %d %Y',
        '%d %B',
        '%d %B %Y',
        '%d %b',
        '%d %b %Y',
    ]

    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If year not specified, use current year
            if parsed.year == 1900:
                parsed = parsed.replace(year=now.year)
            return parsed
        except ValueError:
            continue

    return None


def parse_duration_expression(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration expression into a timedelta object.

    Handles: "30 minutes", "2 hours", "1 day", "half an hour", etc.
    """
    if not duration_str:
        return None

    duration_str = duration_str.lower().strip()

    # Special cases
    if 'half' in duration_str and 'hour' in duration_str:
        return timedelta(minutes=30)
    if duration_str in ('an hour', 'a hour'):
        return timedelta(hours=1)

    # Extract number and unit
    match = re.match(r'(\d+)\s*(\w+)', duration_str)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()

    if unit in ('minute', 'minutes', 'min', 'mins'):
        return timedelta(minutes=amount)
    elif unit in ('hour', 'hours', 'hr', 'hrs'):
        return timedelta(hours=amount)
    elif unit in ('day', 'days'):
        return timedelta(days=amount)
    elif unit in ('week', 'weeks'):
        return timedelta(weeks=amount)

    return None
