import json
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid


class ConsoleMailer:
    """Prints messages instead of sending them; used until SMTP is configured."""

    def send(self, message: EmailMessage) -> None:
        print(f"--- email to {message['To']} ---")
        print(f"Subject: {message['Subject']}")
        print(message.get_body(("plain",)).get_content())

    def close(self) -> None:
        pass


class OutboxMailer:
    """Appends each message to a JSON-lines file for a connector or tool to send."""

    def __init__(self, path):
        self._path = path

    def send(self, message: EmailMessage) -> None:
        html = message.get_body(("html",))
        record = {
            "to": message["To"],
            "from": message["From"],
            "subject": message["Subject"],
            "text": message.get_body(("plain",)).get_content(),
            "html": html.get_content() if html else None,
            "list_unsubscribe": message["List-Unsubscribe"],
        }
        # The file holds subscriber emails and unsubscribe tokens: owner-only.
        fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(json.dumps(record) + "\n")

    def close(self) -> None:
        pass


class SmtpMailer:
    def __init__(self, settings):
        self._settings = settings
        self._connection = None

    def send(self, message: EmailMessage) -> None:
        try:
            self._connect().send_message(message)
        except smtplib.SMTPServerDisconnected:
            self._connection = None
            self._connect().send_message(message)

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.quit()
            except smtplib.SMTPException:
                pass
            self._connection = None

    def _connect(self):
        if self._connection is not None:
            return self._connection
        settings = self._settings
        if settings.use_ssl:
            connection = smtplib.SMTP_SSL(settings.host, settings.port, timeout=30)
        else:
            connection = smtplib.SMTP(settings.host, settings.port, timeout=30)
            connection.starttls()
        if settings.user:
            connection.login(settings.user, settings.password)
        self._connection = connection
        return connection


def make_mailer(config):
    return SmtpMailer(config.smtp) if config.smtp else ConsoleMailer()


def build_message(
    config, to: str, subject: str, text: str, html=None, unsubscribe_url=None
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((config.from_name, config.from_email))
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=config.from_email.rsplit("@", 1)[-1])
    if unsubscribe_url:
        message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def confirmation_message(config, subscriber) -> EmailMessage:
    link = f"{config.base_url}/confirm/{subscriber.confirm_token}"
    text = (
        f"Thanks for your interest in {config.product_name}!\n\n"
        f"Confirm your email to get your personal referral link:\n{link}\n\n"
        "If you didn't sign up, ignore this email and nothing will happen.\n"
    )
    return build_message(
        config,
        subscriber.email,
        f"Confirm your email for {config.product_name}",
        text,
    )
