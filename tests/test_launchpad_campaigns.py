import smtplib

import pytest

from launchpad.campaigns import compose, render, send_campaign
from launchpad.config import Config
from launchpad.store import Store

CONFIG = Config(
    product_name="Acme <Notes>",
    base_url="https://acme.test",
    postal_address="1 Main St, Springfield",
    send_delay_seconds=0,
)


class FakeMailer:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, message):
        if message["To"] in self.fail_for:
            raise smtplib.SMTPException("boom")
        self.sent.append(message)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "test.db")
    store.import_confirmed(["a@example.com", "b@example.com", "c@example.com"])
    return store


def _run(store, mailer, **kwargs):
    kwargs.setdefault("execute", True)
    return send_campaign(
        store,
        kwargs.pop("config", CONFIG),
        mailer,
        kwargs.pop("name", "launch"),
        "Hello",
        kwargs.pop("text", "Join: {{ referral_link }}"),
        sleep=lambda seconds: None,
        **kwargs,
    )


def test_render_substitutes_and_rejects_unknown_variables():
    assert render("Hi {{name}} and {{ name }}", {"name": "x"}) == "Hi x and x"
    with pytest.raises(ValueError, match="unknown variable: nope"):
        render("{{ nope }}", {})


def test_render_escapes_html_values():
    assert render("{{ v }}", {"v": "<b>"}, html=True) == "&lt;b&gt;"


def test_compose_adds_personal_link_unsubscribe_and_address(store):
    subscriber = store.recipients("x")[0]
    message = compose(
        CONFIG,
        subscriber,
        "Hi",
        "Link: {{ referral_link }}",
        "<p>{{ product_name }}</p>",
    )
    text = message.get_body(("plain",)).get_content()
    html = message.get_body(("html",)).get_content()

    assert f"https://acme.test/?ref={subscriber.code}" in text
    assert f"https://acme.test/u/{subscriber.unsubscribe_token}" in text
    assert "1 Main St, Springfield" in text
    assert "Acme &lt;Notes&gt;" in html
    assert message["List-Unsubscribe"] == (
        f"<https://acme.test/u/{subscriber.unsubscribe_token}>"
    )
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_dry_run_sends_nothing(store):
    mailer = FakeMailer()
    report = _run(store, mailer, execute=False)
    assert (report.recipients, report.sent, report.executed) == (3, 0, False)
    assert mailer.sent == []
    assert len(store.recipients("launch")) == 3


def test_execute_sends_once_per_person(store):
    mailer = FakeMailer()
    assert _run(store, mailer).sent == 3
    assert _run(store, mailer).sent == 0
    assert len(mailer.sent) == 3


def test_limit(store):
    mailer = FakeMailer()
    assert _run(store, mailer, limit=2).sent == 2
    assert _run(store, mailer).sent == 1


def test_failures_are_retried_on_the_next_run(store):
    mailer = FakeMailer(fail_for={"b@example.com"})
    report = _run(store, mailer)
    assert (report.sent, report.failed) == (2, 1)

    mailer.fail_for.clear()
    assert _run(store, mailer).sent == 1


def test_aborts_after_consecutive_failures(tmp_path):
    store = Store(tmp_path / "many.db")
    emails = [f"user{n}@example.com" for n in range(10)]
    store.import_confirmed(emails)
    report = _run(store, FakeMailer(fail_for=emails))
    assert (report.sent, report.failed) == (0, 5)


def test_execute_requires_postal_address(store):
    config = Config(base_url="https://acme.test", postal_address=" ")
    with pytest.raises(ValueError, match="postal_address"):
        _run(store, FakeMailer(), config=config)
    assert _run(store, FakeMailer(), config=config, execute=False).recipients == 3


def test_bad_template_fails_before_anything_sends(store):
    mailer = FakeMailer()
    with pytest.raises(ValueError, match="unknown variable"):
        _run(store, mailer, text="{{ typo }}")
    assert mailer.sent == []
