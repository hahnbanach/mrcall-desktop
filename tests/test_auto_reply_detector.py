"""Tests for auto-reply detection utilities."""

import pytest
from zylch.utils.auto_reply_detector import (
    detect_auto_reply,
    is_auto_reply_sender,
    detect_vacation_responder,
)


class TestDetectAutoReply:
    """Tests for detect_auto_reply function."""

    def test_auto_submitted_auto_generated(self):
        """Auto-Submitted: auto-generated should be detected."""
        headers = {'Auto-Submitted': 'auto-generated'}
        assert detect_auto_reply(headers) is True

    def test_auto_submitted_auto_replied(self):
        """Auto-Submitted: auto-replied should be detected."""
        headers = {'Auto-Submitted': 'auto-replied'}
        assert detect_auto_reply(headers) is True

    def test_auto_submitted_auto_notified(self):
        """Auto-Submitted: auto-notified should be detected."""
        headers = {'Auto-Submitted': 'auto-notified'}
        assert detect_auto_reply(headers) is True

    def test_auto_submitted_no(self):
        """Auto-Submitted: no should NOT be detected as auto-reply."""
        headers = {'Auto-Submitted': 'no'}
        assert detect_auto_reply(headers) is False

    def test_x_auto_response_suppress_all(self):
        """X-Auto-Response-Suppress: All should be detected."""
        headers = {'X-Auto-Response-Suppress': 'All'}
        assert detect_auto_reply(headers) is True

    def test_x_auto_response_suppress_oof(self):
        """X-Auto-Response-Suppress: OOF should be detected."""
        headers = {'X-Auto-Response-Suppress': 'OOF'}
        assert detect_auto_reply(headers) is True

    def test_precedence_bulk(self):
        """Precedence: bulk should be detected."""
        headers = {'Precedence': 'bulk'}
        assert detect_auto_reply(headers) is True

    def test_precedence_junk(self):
        """Precedence: junk should be detected."""
        headers = {'Precedence': 'junk'}
        assert detect_auto_reply(headers) is True

    def test_precedence_list(self):
        """Precedence: list should be detected."""
        headers = {'Precedence': 'list'}
        assert detect_auto_reply(headers) is True

    def test_precedence_auto_reply(self):
        """Precedence: auto_reply should be detected."""
        headers = {'Precedence': 'auto_reply'}
        assert detect_auto_reply(headers) is True

    def test_precedence_normal(self):
        """Precedence: normal should NOT be detected."""
        headers = {'Precedence': 'normal'}
        assert detect_auto_reply(headers) is False

    def test_x_autoreply_yes(self):
        """X-Autoreply: yes should be detected."""
        headers = {'X-Autoreply': 'yes'}
        assert detect_auto_reply(headers) is True

    def test_x_autoreply_true(self):
        """X-Autoreply: true should be detected."""
        headers = {'X-Autoreply': 'true'}
        assert detect_auto_reply(headers) is True

    def test_x_autorespond_any_value(self):
        """X-Autorespond with any value should be detected."""
        headers = {'X-Autorespond': 'vacation'}
        assert detect_auto_reply(headers) is True

    def test_return_path_empty(self):
        """Return-Path: <> (empty) should be detected as bounce."""
        headers = {'Return-Path': '<>'}
        assert detect_auto_reply(headers) is True

    def test_x_failed_recipients(self):
        """X-Failed-Recipients header should be detected as bounce."""
        headers = {'X-Failed-Recipients': 'user@example.com'}
        assert detect_auto_reply(headers) is True

    def test_content_type_multipart_report(self):
        """Content-Type: multipart/report should be detected."""
        headers = {'Content-Type': 'multipart/report; report-type=delivery-status'}
        assert detect_auto_reply(headers) is True

    def test_content_type_delivery_status(self):
        """Content-Type with delivery-status should be detected."""
        headers = {'Content-Type': 'message/delivery-status'}
        assert detect_auto_reply(headers) is True

    def test_x_ms_exchange_generated(self):
        """X-MS-Exchange-Generated-Message-Source should be detected."""
        headers = {'X-MS-Exchange-Generated-Message-Source': 'Mailbox Rules Agent'}
        assert detect_auto_reply(headers) is True

    def test_case_insensitive_headers(self):
        """Headers should be matched case-insensitively."""
        headers = {'auto-submitted': 'auto-generated'}
        assert detect_auto_reply(headers) is True

        headers = {'AUTO-SUBMITTED': 'auto-generated'}
        assert detect_auto_reply(headers) is True

    def test_from_email_mailer_daemon(self):
        """mailer-daemon@ should be detected as auto-reply."""
        headers = {}
        assert detect_auto_reply(headers, from_email='mailer-daemon@example.com') is True

    def test_from_email_noreply(self):
        """noreply@ should be detected as auto-reply."""
        headers = {}
        assert detect_auto_reply(headers, from_email='noreply@example.com') is True

    def test_from_email_postmaster(self):
        """postmaster@ should be detected as auto-reply."""
        headers = {}
        assert detect_auto_reply(headers, from_email='postmaster@example.com') is True

    def test_normal_email(self):
        """Normal email without auto-reply indicators should NOT be detected."""
        headers = {
            'From': 'john@example.com',
            'To': 'jane@example.com',
            'Subject': 'Hello',
        }
        assert detect_auto_reply(headers, from_email='john@example.com') is False

    def test_empty_headers(self):
        """Empty headers should return False."""
        assert detect_auto_reply({}) is False
        assert detect_auto_reply(None) is False

    def test_gmail_vacation_responder(self):
        """Gmail vacation responder headers should be detected."""
        headers = {
            'Auto-Submitted': 'auto-replied',
            'X-Autoreply': 'yes',
            'Precedence': 'bulk',
        }
        assert detect_auto_reply(headers) is True

    def test_outlook_oof(self):
        """Outlook out-of-office headers should be detected."""
        headers = {
            'X-Auto-Response-Suppress': 'All',
            'X-MS-Exchange-Generated-Message-Source': 'Mailbox Rules Agent',
        }
        assert detect_auto_reply(headers) is True


class TestIsAutoReplySender:
    """Tests for is_auto_reply_sender function."""

    def test_mailer_daemon(self):
        assert is_auto_reply_sender('MAILER-DAEMON@example.com') is True
        assert is_auto_reply_sender('mailer-daemon@mx.example.com') is True

    def test_postmaster(self):
        assert is_auto_reply_sender('postmaster@example.com') is True

    def test_noreply_variations(self):
        assert is_auto_reply_sender('noreply@example.com') is True
        assert is_auto_reply_sender('no-reply@example.com') is True
        assert is_auto_reply_sender('no_reply@example.com') is True
        assert is_auto_reply_sender('donotreply@example.com') is True
        assert is_auto_reply_sender('do-not-reply@example.com') is True

    def test_autoreply_variations(self):
        assert is_auto_reply_sender('auto-reply@example.com') is True
        assert is_auto_reply_sender('autoreply@example.com') is True
        assert is_auto_reply_sender('auto_reply@example.com') is True

    def test_bounce(self):
        assert is_auto_reply_sender('bounce@example.com') is True
        assert is_auto_reply_sender('bounces@notifications.example.com') is True

    def test_normal_email(self):
        assert is_auto_reply_sender('john.doe@example.com') is False
        assert is_auto_reply_sender('support@company.com') is False
        assert is_auto_reply_sender('info@business.com') is False

    def test_empty_email(self):
        assert is_auto_reply_sender('') is False
        assert is_auto_reply_sender(None) is False


class TestDetectVacationResponder:
    """Tests for detect_vacation_responder function."""

    def test_out_of_office_english(self):
        assert detect_vacation_responder('Out of Office', 'I am out of the office') is True
        assert detect_vacation_responder('RE: Meeting', 'I am currently out of office') is True

    def test_automatic_reply(self):
        assert detect_vacation_responder('Automatic reply: RE: Your message', '') is True

    def test_vacation_message(self):
        assert detect_vacation_responder('', 'I will be on vacation until Monday') is True

    def test_italian_oof(self):
        assert detect_vacation_responder('Fuori Ufficio', 'Sono in ferie') is True

    def test_german_oof(self):
        assert detect_vacation_responder('Abwesenheitsnotiz', '') is True

    def test_french_oof(self):
        assert detect_vacation_responder('Absence du bureau', '') is True

    def test_spanish_oof(self):
        assert detect_vacation_responder('Fuera de la oficina', '') is True

    def test_normal_email(self):
        assert detect_vacation_responder('Meeting tomorrow', 'Let us meet at 3pm') is False

    def test_empty_content(self):
        assert detect_vacation_responder('', '') is False
        assert detect_vacation_responder(None, None) is False


class TestRealWorldScenarios:
    """Test real-world auto-reply scenarios."""

    def test_gmail_vacation_responder(self):
        """Gmail vacation responder example."""
        headers = {
            'Auto-Submitted': 'auto-replied',
            'X-Autoreply': 'yes',
            'Precedence': 'bulk',
            'From': 'john@gmail.com',
        }
        assert detect_auto_reply(headers) is True

    def test_outlook_oof_reply(self):
        """Microsoft Outlook Out of Office reply."""
        headers = {
            'X-Auto-Response-Suppress': 'All',
            'X-MS-Exchange-Generated-Message-Source': 'Mailbox Rules Agent',
            'Auto-Submitted': 'auto-replied',
        }
        assert detect_auto_reply(headers) is True

    def test_mailer_daemon_bounce(self):
        """Mailer-daemon bounce message."""
        headers = {
            'Return-Path': '<>',
            'Content-Type': 'multipart/report; report-type=delivery-status',
            'Auto-Submitted': 'auto-generated',
        }
        assert detect_auto_reply(headers, from_email='MAILER-DAEMON@mx.example.com') is True

    def test_mailing_list_autoresponse(self):
        """Mailing list auto-response."""
        headers = {
            'Precedence': 'list',
            'List-Unsubscribe': '<mailto:unsubscribe@list.example.com>',
        }
        assert detect_auto_reply(headers) is True

    def test_delivery_failure_notification(self):
        """Delivery failure notification."""
        headers = {
            'X-Failed-Recipients': 'invalid@example.com',
            'Content-Type': 'multipart/report',
            'Return-Path': '<>',
        }
        assert detect_auto_reply(headers) is True

    def test_normal_business_email(self):
        """Normal business email should not be flagged."""
        headers = {
            'From': 'colleague@company.com',
            'To': 'me@company.com',
            'Subject': 'Q4 Budget Review',
            'Content-Type': 'text/plain',
        }
        assert detect_auto_reply(headers, from_email='colleague@company.com') is False

    def test_newsletter_bulk_precedence(self):
        """Newsletter with bulk precedence should be detected."""
        headers = {
            'Precedence': 'bulk',
            'From': 'news@company.com',
        }
        assert detect_auto_reply(headers) is True
