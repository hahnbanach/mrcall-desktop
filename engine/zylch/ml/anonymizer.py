"""
PII Anonymization for Training Data Collection

Uses Microsoft Presidio + spaCy for entity detection when available,
falls back to regex patterns otherwise.
"""

import hashlib
import json
import re
import logging
from typing import Dict, Tuple, List, Any

logger = logging.getLogger(__name__)


class TriageAnonymizer:
    """
    Anonymize email content for training data collection.

    Detects and replaces PII with placeholder tokens like:
    - <EMAIL_1>, <EMAIL_2>, ...
    - <PERSON_1>, <PERSON_2>, ...
    - <PHONE_1>, <PHONE_2>, ...

    The entity map allows reconstruction if needed (stored separately).
    """

    def __init__(self, language: str = "en"):
        """
        Initialize the anonymizer.

        Args:
            language: Language code for NLP models (default: "en")
        """
        self.language = language
        self.use_presidio = False
        self._init_analyzers()

    def _init_analyzers(self):
        """Initialize Presidio or fallback to regex."""
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine

            self.analyzer = AnalyzerEngine()
            self.anonymizer = AnonymizerEngine()
            self.use_presidio = True
            logger.info("Using Presidio for PII detection")
        except ImportError:
            logger.info("Presidio not available, using regex patterns for PII detection")
            self.use_presidio = False
            self._init_regex_patterns()

    def _init_regex_patterns(self):
        """Fallback regex patterns for common PII."""
        self.patterns = {
            "EMAIL": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE),
            "PHONE": re.compile(r"(?:\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
            "URL": re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE),
            "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
            "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
            "SSN": re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"),
            # Date patterns (to preserve context but anonymize specific dates)
            "DATE": re.compile(
                r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})\b"
            ),
        }

    def anonymize(self, text: str) -> Tuple[str, Dict[str, List[str]]]:
        """
        Anonymize text and return (anonymized_text, entity_map).

        The entity_map contains original values grouped by entity type,
        allowing reconstruction if needed.

        Args:
            text: Original text to anonymize

        Returns:
            Tuple of (anonymized_text, entity_map)
        """
        if not text:
            return "", {}

        if self.use_presidio:
            return self._anonymize_with_presidio(text)
        else:
            return self._anonymize_with_regex(text)

    def _anonymize_with_presidio(self, text: str) -> Tuple[str, Dict[str, List[str]]]:
        """Use Presidio for comprehensive PII detection."""

        # Analyze for PII
        results = self.analyzer.analyze(
            text=text,
            language=self.language,
            entities=[
                "EMAIL_ADDRESS",
                "PHONE_NUMBER",
                "PERSON",
                "LOCATION",
                "DATE_TIME",
                "ORGANIZATION",
                "CREDIT_CARD",
                "IBAN_CODE",
                "IP_ADDRESS",
                "URL",
            ],
        )

        # Build entity map and track replacements
        entity_map: Dict[str, List[str]] = {}
        entity_counters: Dict[str, int] = {}

        # Sort results by start position (reversed for safe replacement)
        results = sorted(results, key=lambda x: x.start, reverse=True)

        anonymized_text = text
        for result in results:
            entity_type = result.entity_type
            original_value = text[result.start : result.end]

            # Track original values
            if entity_type not in entity_map:
                entity_map[entity_type] = []
            if original_value not in entity_map[entity_type]:
                entity_map[entity_type].append(original_value)

            # Generate placeholder
            if entity_type not in entity_counters:
                entity_counters[entity_type] = 0
            entity_counters[entity_type] += 1
            placeholder = f"<{entity_type}_{entity_counters[entity_type]}>"

            # Replace in text
            anonymized_text = (
                anonymized_text[: result.start] + placeholder + anonymized_text[result.end :]
            )

        return anonymized_text, entity_map

    def _anonymize_with_regex(self, text: str) -> Tuple[str, Dict[str, List[str]]]:
        """Use regex patterns for PII detection (fallback)."""
        entity_map: Dict[str, List[str]] = {}
        entity_counters: Dict[str, int] = {}
        anonymized_text = text

        for entity_type, pattern in self.patterns.items():
            matches = list(pattern.finditer(anonymized_text))
            # Process in reverse order to maintain positions
            for match in reversed(matches):
                original_value = match.group()

                # Track original values
                if entity_type not in entity_map:
                    entity_map[entity_type] = []
                if original_value not in entity_map[entity_type]:
                    entity_map[entity_type].append(original_value)

                # Generate placeholder
                if entity_type not in entity_counters:
                    entity_counters[entity_type] = 0
                entity_counters[entity_type] += 1
                placeholder = f"<{entity_type}_{entity_counters[entity_type]}>"

                # Replace in text
                anonymized_text = (
                    anonymized_text[: match.start()] + placeholder + anonymized_text[match.end() :]
                )

        return anonymized_text, entity_map

    def anonymize_email_thread(self, thread: dict) -> dict:
        """
        Anonymize entire email thread for training.

        Args:
            thread: Thread dict with messages

        Returns:
            Anonymized thread with entity_map
        """
        all_entities: Dict[str, List[str]] = {}

        def merge_entities(entity_map: Dict[str, List[str]]):
            """Merge new entities into all_entities."""
            for entity_type, values in entity_map.items():
                if entity_type not in all_entities:
                    all_entities[entity_type] = []
                for value in values:
                    if value not in all_entities[entity_type]:
                        all_entities[entity_type].append(value)

        # Anonymize thread-level fields
        anonymized_thread = {}

        if "subject" in thread:
            anon_subject, entities = self.anonymize(thread["subject"])
            anonymized_thread["subject"] = anon_subject
            merge_entities(entities)

        # Anonymize messages
        if "messages" in thread:
            anonymized_messages = []
            for msg in thread["messages"]:
                anon_msg = {}

                # Anonymize body
                if "body" in msg:
                    anon_body, entities = self.anonymize(msg["body"])
                    anon_msg["body"] = anon_body
                    merge_entities(entities)

                # Anonymize from/to (keep structure but anonymize values)
                if "from" in msg:
                    anon_from, entities = self.anonymize(msg["from"])
                    anon_msg["from"] = anon_from
                    merge_entities(entities)

                if "to" in msg:
                    anon_to, entities = self.anonymize(msg["to"])
                    anon_msg["to"] = anon_to
                    merge_entities(entities)

                # Copy non-PII fields
                for key in ["date", "labels", "is_auto_reply"]:
                    if key in msg:
                        anon_msg[key] = msg[key]

                anonymized_messages.append(anon_msg)

            anonymized_thread["messages"] = anonymized_messages

        # Copy non-PII thread metadata
        for key in ["thread_id", "message_count", "has_attachments"]:
            if key in thread:
                anonymized_thread[key] = thread[key]

        anonymized_thread["_entity_map"] = all_entities

        return anonymized_thread


def create_sample_hash(anonymized_content: Any) -> str:
    """
    Create SHA256 hash for deduplication.

    Args:
        anonymized_content: Anonymized content (dict or string)

    Returns:
        SHA256 hex digest
    """
    if isinstance(anonymized_content, dict):
        # Remove entity map before hashing (only hash actual content)
        content_copy = {k: v for k, v in anonymized_content.items() if k != "_entity_map"}
        content_str = json.dumps(content_copy, sort_keys=True)
    else:
        content_str = str(anonymized_content)

    return hashlib.sha256(content_str.encode()).hexdigest()
