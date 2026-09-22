from __future__ import annotations

from collections.abc import Iterable

from utils.csv_parser import Recipient
from utils.template import render_template


def build_messages(recipients: Iterable[Recipient], subject: str, body: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for recipient in recipients:
        messages.append(
            {
                "email": recipient.email,
                "name": recipient.name,
                "subject": render_template(subject, recipient.values),
                "body": render_template(body, recipient.values),
            }
        )
    return messages
