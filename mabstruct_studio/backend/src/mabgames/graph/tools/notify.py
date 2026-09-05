"""Telegram push, for telling the studio lead a build is ready.

The notebook's version discarded the send result and always told the agent
"Notification sent", which made the agent's own report of notification status
unreliable by construction. This one reports what actually happened.
"""

import logging

import requests
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def make_push_notification_tool(bot_token: str | None, chat_id: str | None):
    @tool
    def send_push_notification(text: str) -> str:
        """Send a short push notification to the studio lead's phone."""
        if not bot_token or not chat_id:
            return "Notification skipped: no Telegram token or chat id configured."
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={"chat_id": chat_id, "text": text},
                timeout=30,
            )
        except Exception as exc:
            logger.warning("telegram send failed: %s", exc)
            return f"Notification failed: {type(exc).__name__}: {exc}"
        if response.status_code != 200:
            return f"Notification failed: HTTP {response.status_code}"
        return "Notification sent"

    return send_push_notification
