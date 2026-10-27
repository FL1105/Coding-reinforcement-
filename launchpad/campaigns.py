import re
import smtplib
import time
from dataclasses import dataclass
from html import escape

from .mailer import build_message

_VARIABLE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_MAX_CONSECUTIVE_FAILURES = 5


@dataclass(frozen=True)
class CampaignReport:
    recipients: int
    sent: int
    failed: int
    executed: bool


def referral_link(config, subscriber) -> str:
    return f"{config.base_url}/?ref={subscriber.code}"


def unsubscribe_link(config, subscriber) -> str:
    return f"{config.base_url}/u/{subscriber.unsubscribe_token}"


def render(template: str, values: dict, html: bool = False) -> str:
    def substitute(match):
        name = match.group(1)
        if name not in values:
            raise ValueError(f"unknown variable: {name}")
        value = str(values[name])
        return escape(value) if html else value

    return _VARIABLE.sub(substitute, template)


def variables(config, subscriber) -> dict:
    return {
        "product_name": config.product_name,
        "referral_link": referral_link(config, subscriber),
        "referral_count": subscriber.referrals,
        "unsubscribe_link": unsubscribe_link(config, subscriber),
        "postal_address": config.postal_address,
    }


def compose(config, subscriber, subject, text_template, html_template=None):
    values = variables(config, subscriber)
    text = render(text_template, values)
    text += (
        "\n\n--\n"
        f"You're receiving this because you signed up for {config.product_name}.\n"
        f"Unsubscribe: {values['unsubscribe_link']}\n"
        f"{config.postal_address}\n"
    )
    html = None
    if html_template:
        html = render(html_template, values, html=True)
        html += (
            '<p style="font-size:12px;color:#666">'
            f"You're receiving this because you signed up for "
            f"{escape(config.product_name)}. "
            f'<a href="{escape(values["unsubscribe_link"])}">Unsubscribe</a><br>'
            f"{escape(config.postal_address)}</p>"
        )
    return build_message(
        config,
        subscriber.email,
        subject,
        text,
        html,
        unsubscribe_url=values["unsubscribe_link"],
    )


def send_campaign(
    store,
    config,
    mailer,
    name: str,
    subject: str,
    text_template: str,
    html_template=None,
    execute: bool = False,
    limit=None,
    sleep=time.sleep,
) -> CampaignReport:
    if execute and not config.postal_address.strip():
        raise ValueError(
            "postal_address is required in the config before sending "
            "(CAN-SPAM and similar laws require a physical address)"
        )

    recipients = store.recipients(name)
    if limit is not None:
        recipients = recipients[:limit]

    # Render every message up front so a bad template fails before anything sends.
    messages = [
        (subscriber, compose(config, subscriber, subject, text_template, html_template))
        for subscriber in recipients
    ]
    if not execute:
        return CampaignReport(len(messages), 0, 0, executed=False)

    sent = failed = streak = 0
    for index, (subscriber, message) in enumerate(messages):
        if index:
            sleep(config.send_delay_seconds)
        try:
            mailer.send(message)
        except (smtplib.SMTPException, OSError):
            failed += 1
            streak += 1
            if streak >= _MAX_CONSECUTIVE_FAILURES:
                break
            continue
        streak = 0
        store.mark_sent(name, subscriber.id)
        sent += 1
    return CampaignReport(len(messages), sent, failed, executed=True)
