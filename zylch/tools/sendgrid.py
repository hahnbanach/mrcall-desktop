"""SendGrid client for mass email campaigns.

Adapted from mailsender project.
"""

import logging
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridClient:
    """Client for SendGrid API mass email operations."""

    def __init__(
        self,
        api_key: str,
        default_from_email: str = "noreply@example.com",
        default_from_name: Optional[str] = None,
    ):
        """Initialize SendGrid client.

        Args:
            api_key: SendGrid API key
            default_from_email: Default sender email
            default_from_name: Default sender name
        """
        self.api_key = api_key
        self.default_from_email = default_from_email
        self.default_from_name = default_from_name

        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info("Initialized SendGrid client")

    async def send_email(
        self,
        recipient: str,
        subject: str,
        body: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        body_type: str = "text/html",
        variables: Optional[Dict] = None,
        sandbox_mode: bool = False,
        campaign_id: Optional[str] = None,
    ) -> Dict:
        """Send email via SendGrid.

        Args:
            recipient: Recipient email
            subject: Email subject
            body: Email body
            from_email: Sender email (optional)
            from_name: Sender name (optional)
            body_type: Content type (text/html or text/plain)
            variables: Custom variables for tracking
            sandbox_mode: Enable sandbox mode (testing)
            campaign_id: Campaign identifier

        Returns:
            SendGrid API response

        Raises:
            httpx.HTTPStatusError: If request fails
        """
        personalization = {"to": [{"email": recipient}]}

        if variables:
            personalization["custom_args"] = variables

        if campaign_id:
            if "custom_args" not in personalization:
                personalization["custom_args"] = {}
            personalization["custom_args"]["campaign_id"] = campaign_id

        payload = {
            "personalizations": [personalization],
            "from": {
                "email": from_email or self.default_from_email,
            },
            "subject": subject,
            "tracking_settings": {
                "open_tracking": {"enable": True},
                "click_tracking": {"enable": True},
                "subscription_tracking": {"enable": True}
            },
            "content": [{"type": body_type, "value": body}],
        }

        if from_name or self.default_from_name:
            payload["from"]["name"] = from_name or self.default_from_name

        if sandbox_mode:
            payload["mail_settings"] = {"sandbox_mode": {"enable": True}}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Sending email to {recipient}: {subject}")

        response = await self.client.post(
            SENDGRID_API_URL,
            json=payload,
            headers=headers
        )

        logger.debug(f"SendGrid response {response.status_code}: {response.text}")
        response.raise_for_status()

        return {"status": "sent", "recipient": recipient, "campaign_id": campaign_id}

    async def send_batch_emails(
        self,
        recipients: List[Dict[str, str]],
        subject: str,
        body_template: str,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None,
        campaign_id: Optional[str] = None,
    ) -> Dict:
        """Send batch emails with personalization.

        Args:
            recipients: List of recipient dicts with email and variables
            subject: Email subject (supports {{variable}} syntax)
            body_template: Email body template (supports {{variable}} syntax)
            from_email: Sender email
            from_name: Sender name
            campaign_id: Campaign identifier

        Returns:
            Batch send summary
        """
        sent = []
        failed = []

        for recipient_data in recipients:
            email = recipient_data.get("email")
            variables = recipient_data.get("variables", {})

            # Apply variable substitution
            personalized_subject = self._apply_variables(subject, variables)
            personalized_body = self._apply_variables(body_template, variables)

            try:
                await self.send_email(
                    recipient=email,
                    subject=personalized_subject,
                    body=personalized_body,
                    from_email=from_email,
                    from_name=from_name,
                    variables=variables,
                    campaign_id=campaign_id,
                )
                sent.append(email)
                logger.info(f"Sent to {email}")

            except Exception as e:
                failed.append({"email": email, "error": str(e)})
                logger.error(f"Failed to send to {email}: {e}")

        return {
            "campaign_id": campaign_id,
            "total": len(recipients),
            "sent": len(sent),
            "failed": len(failed),
            "failed_details": failed,
        }

    def _apply_variables(self, template: str, variables: Dict[str, str]) -> str:
        """Apply variable substitution to template.

        Supports {{variable_name=default}} syntax.

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

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
