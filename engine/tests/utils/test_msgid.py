"""Threading ids are `msg-id` tokens, and the send path must enforce that.

The bug these guard: the model typed `&lt;id@host&gt;` into `create_draft`,
nothing between the tool call and the SMTP socket looked at it, and four
replies went out in 2026-09 with a `References` header no client could parse —
which also made the local sent mirror miss its parent, so those conversations
read as unanswered from then on.
"""

from zylch.utils.msgid import clean_message_id, clean_references


class TestCleanMessageId:
    def test_html_escaped_brackets_are_repaired(self):
        assert (
            clean_message_id("&lt;CANntf1J=x+y@mail.gmail.com&gt;")
            == "<CANntf1J=x+y@mail.gmail.com>"
        )

    def test_valid_id_is_returned_unchanged(self):
        assert clean_message_id("<178977262527.916.13@mrcall.ai>") == (
            "<178977262527.916.13@mrcall.ai>"
        )

    def test_bare_id_gains_its_brackets(self):
        assert clean_message_id("abc@example.com") == "<abc@example.com>"

    def test_folded_header_whitespace_is_collapsed(self):
        assert clean_message_id("<abc@\r\n example.com>") is None
        assert clean_message_id("  <abc@example.com>\r\n ") == "<abc@example.com>"

    def test_unrepairable_values_are_dropped_not_passed_through(self):
        for bad in ("rubbish", "<no-at-sign>", "", None, 42, "<a@b> <c@d>"):
            assert clean_message_id(bad) is None


class TestCleanReferences:
    def test_string_chain_keeps_its_shape(self):
        assert clean_references("&lt;a@x&gt; &lt;b@y&gt;") == "<a@x> <b@y>"

    def test_list_chain_keeps_its_shape(self):
        assert clean_references(["&lt;a@x&gt;", "<b@y>"]) == ["<a@x>", "<b@y>"]

    def test_one_bad_entry_does_not_cost_the_chain(self):
        assert clean_references(["&lt;a@x&gt;", "junk", "<b@y>"]) == ["<a@x>", "<b@y>"]

    def test_none_stays_none(self):
        assert clean_references(None) is None

    def test_nothing_salvageable_yields_an_empty_result(self):
        assert clean_references("junk") is None
        assert clean_references(["junk"]) == []
