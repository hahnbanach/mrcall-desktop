"""Tests for text processing utilities."""

import pytest
from zylch_memory.text_processing import split_sentences


class TestSplitSentences:
    """Tests for split_sentences function."""

    def test_basic_sentence_split(self):
        """Test basic sentence splitting."""
        text = "First sentence. Second sentence. Third sentence."
        result = split_sentences(text)
        assert len(result) == 3
        assert result[0] == "First sentence."
        assert result[1] == "Second sentence."
        assert result[2] == "Third sentence."

    def test_abbreviations_preserved(self):
        """Test that abbreviations don't cause incorrect splits."""
        text = "Dr. Smith works at Inc. Corp. He is great."
        result = split_sentences(text)
        assert len(result) == 2
        assert "Dr." in result[0]
        assert "Inc." in result[0]

    def test_decimal_numbers(self):
        """Test that decimal numbers don't cause splits."""
        text = "The price is 3.14 dollars. That's cheap."
        result = split_sentences(text)
        assert len(result) == 2
        assert "3.14" in result[0]

    def test_ellipsis(self):
        """Test that ellipsis is preserved."""
        text = "Wait... I think so. Yes."
        result = split_sentences(text)
        assert "..." in result[0]

    def test_empty_string(self):
        """Test empty string returns empty list."""
        result = split_sentences("")
        assert result == []

    def test_single_sentence(self):
        """Test single sentence without trailing punctuation."""
        text = "Just one sentence"
        result = split_sentences(text)
        assert len(result) == 1
        assert result[0] == "Just one sentence"

    def test_question_and_exclamation(self):
        """Test splitting on ? and !"""
        text = "Is this working? Yes! It is."
        result = split_sentences(text)
        assert len(result) == 3

    def test_multilingual_abbreviations(self):
        """Test Italian/European abbreviations."""
        text = "Il Dott. Rossi lavora alla S.r.l. Bianchi. È esperto."
        result = split_sentences(text)
        assert len(result) == 2
