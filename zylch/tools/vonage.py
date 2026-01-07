"""Vonage SMS client for SMS campaigns.

Adapted from mailsender project.
"""

import logging
from typing import Dict, List, Optional

from vonage import Auth, Vonage
from vonage_sms import SmsMessage

logger = logging.getLogger(__name__)


class VonageClient:
    """Client for Vonage SMS API operations."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        from_number: str,
        webhook_url: Optional[str] = None,
    ):
        """Initialize Vonage client.

        Args:
            api_key: Vonage API key
            api_secret: Vonage API secret
            from_number: Default sender number
            webhook_url: Webhook URL for delivery receipts
        """
        if not api_key or not api_secret:
            raise ValueError("Vonage API credentials are required")

        self.api_key = api_key
        self.api_secret = api_secret
        self.from_number = from_number
        self.webhook_url = webhook_url

        self.auth = Auth(api_key=api_key, api_secret=api_secret)
        self.client = Vonage(auth=self.auth)

        logger.info("Initialized Vonage SMS client")

    async def send_sms(
        self,
        recipient: str,
        text: str,
        sender: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> Dict:
        """Send SMS via Vonage.

        Args:
            recipient: Recipient phone number
            text: SMS message text
            sender: Sender name/number (optional)
            campaign_id: Campaign identifier for tracking

        Returns:
            Send result with message ID

        Raises:
            RuntimeError: If send fails
        """
        from_name = sender or self.from_number
        if not from_name:
            raise ValueError("SMS sender is required")

        message = SmsMessage(
            to=recipient,
            from_=from_name,
            text=text
        )

        if campaign_id:
            message.client_ref = campaign_id

        if self.webhook_url:
            message.callback = self.webhook_url

        logger.debug(f"Sending SMS to {recipient}: {text}")

        response = self.client.sms.send(message)
        logger.debug(f"Vonage response: {response.model_dump(exclude_unset=True)}")

        msg = response.messages[0]
        if msg.status != "0":
            raise RuntimeError(f"SMS failed: {msg.error_text}")

        return {
            "status": "sent",
            "recipient": recipient,
            "message_id": msg.message_id,
            "campaign_id": campaign_id,
        }

    async def send_bulk_sms(
        self,
        recipients: List[Dict[str, str]],
        message_template: str,
        campaign_id: Optional[str] = None,
        sender: Optional[str] = None,
    ) -> Dict:
        """Send bulk SMS with personalization.

        Args:
            recipients: List of recipient dicts with phone and variables
            message_template: SMS template (supports {{variable}} syntax)
            campaign_id: Campaign identifier
            sender: Sender name/number

        Returns:
            Bulk send summary
        """
        sent = []
        failed = []

        for recipient_data in recipients:
            phone = recipient_data.get("phone")
            variables = recipient_data.get("variables", {})

            # Apply variable substitution
            personalized_message = self._apply_variables(message_template, variables)

            try:
                result = await self.send_sms(
                    recipient=phone,
                    text=personalized_message,
                    sender=sender,
                    campaign_id=campaign_id,
                )
                sent.append(phone)
                logger.info(f"Sent SMS to {phone}")

            except Exception as e:
                failed.append({"phone": phone, "error": str(e)})
                logger.error(f"Failed to send SMS to {phone}: {e}")

        return {
            "campaign_id": campaign_id,
            "total": len(recipients),
            "sent": len(sent),
            "failed": len(failed),
            "failed_details": failed,
        }

    def _apply_variables(self, template: str, variables: Dict[str, str]) -> str:
        """Apply variable substitution to template.

        Args:
            template: Template string
            variables: Variables dict

        Returns:
            Template with variables applied
        """
        import re

        # Match {{variable_name=default}} or {{variable_name}}
        pattern = r'\{\{([^}=]+)(?:=([^}]+))?\}\}'

        def replace(match):
            var_name = match.group(1).strip()
            default = match.group(2).strip() if match.group(2) else ""
            return variables.get(var_name, default)

        return re.sub(pattern, replace, template)
