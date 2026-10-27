import http.client
import re
import threading

import pytest

from launchpad.config import Config, Reward, load_config
from launchpad.mailer import ConsoleMailer
from launchpad.store import Store
from launchpad.web import App, make_server

FORM = {"Content-Type": "application/x-www-form-urlencoded"}


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)

    def links(self, kind):
        body = self.sent[-1].get_body(("plain",)).get_content()
        return re.findall(rf"https://acme\.test/{kind}/(\S+)", body)


def _config(**overrides):
    values = {
        "product_name": "Acme Notes",
        "tagline": "Notes that organise themselves.",
        "description": "Early access.",
        "benefits": ("Early access",),
        "rewards": (Reward(1, "Skip the queue"), Reward(3, "One month free")),
        "base_url": "https://acme.test",
        "postal_address": "1 Main St",
    }
    return Config(**{**values, **overrides})


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def app(store, mailer):
    return App(_config(), store, mailer, background=False)


def _signup(app, email, ref="", headers=None):
    body = f"email={email.replace('+', '%2B')}&ref={ref}".encode()
    return app.handle("POST", "/signup", {**FORM, **(headers or {})}, body, "1.1.1.1")


def _join(app, mailer, email, ref=""):
    assert _signup(app, email, ref).status == 200
    token = mailer.links("confirm")[0]
    response = app.handle("GET", f"/confirm/{token}", {})
    assert response.status == 303
    return dict(response.headers)["Location"].removeprefix("/welcome/")


def test_landing_page_renders_content(app):
    response = app.handle("GET", "/", {})
    page = response.body.decode()
    assert response.status == 200
    assert "Acme Notes" in page
    assert "Notes that organise themselves." in page
    assert "Skip the queue" in page
    assert 'action="/signup"' in page


def test_landing_page_escapes_config_text(tmp_path, mailer):
    config = _config(product_name="<script>alert(1)</script>")
    page = App(config, Store(tmp_path / "x.db"), mailer).handle("GET", "/", {})
    assert b"<script>alert(1)" not in page.body
    assert b"&lt;script&gt;" in page.body


def test_signup_sends_confirmation_link(app, mailer):
    response = _signup(app, "a@example.com")
    assert response.status == 200
    assert b"Check your inbox" in response.body
    assert len(mailer.sent) == 1
    assert mailer.sent[0]["To"] == "a@example.com"
    assert mailer.sent[0]["List-Unsubscribe"] is None


def test_repeat_signup_looks_identical_but_does_not_resend(app, mailer):
    first = _signup(app, "a@example.com")
    second = _signup(app, "a@example.com")
    assert first.body == second.body
    assert len(mailer.sent) == 1


def test_invalid_email_is_rejected_and_nothing_sent(app, mailer):
    response = _signup(app, "not-an-email")
    assert response.status == 400
    assert b"valid email" in response.body
    assert mailer.sent == []


def test_signup_requires_form_encoding(app):
    response = app.handle("POST", "/signup", {}, b"email=a@example.com", "1.1.1.1")
    assert response.status == 415


def test_honeypot_looks_successful_but_sends_nothing(app, mailer):
    body = b"email=bot@example.com&leave_blank=http%3A%2F%2Fspam"
    response = app.handle("POST", "/signup", FORM, body, "1.1.1.1")
    assert response.status == 200
    assert mailer.sent == []


def test_signups_are_rate_limited_per_ip(app):
    for number in range(10):
        assert _signup(app, f"user{number}@example.com").status == 200
    assert _signup(app, "one-more@example.com").status == 429
    other = app.handle(
        "POST", "/signup", FORM, b"email=elsewhere@example.com", "2.2.2.2"
    )
    assert other.status == 200


def test_oversized_body_is_rejected(app):
    response = app.handle("POST", "/signup", FORM, b"x" * 9000, "1.1.1.1")
    assert response.status == 413


def test_full_referral_flow(app, mailer):
    code_a = _join(app, mailer, "a@example.com")

    landing = app.handle("GET", f"/?ref={code_a}", {})
    assert f'name="ref" value="{code_a}"' in landing.body.decode()
    cookie = dict(landing.headers)["Set-Cookie"]
    assert cookie.startswith(f"lp_ref={code_a}")
    assert "HttpOnly" in cookie and "Secure" in cookie

    # The cookie alone is enough when the form's hidden field is empty.
    _signup(app, "b@example.com", headers={"Cookie": f"lp_ref={code_a}"})
    pending = app.handle("GET", f"/welcome/{code_a}", {})
    assert b"<strong>0</strong>" in pending.body

    token = mailer.links("confirm")[0]
    code_b = app.handle("GET", f"/confirm/{token}", {}).headers[0][1].split("/")[-1]
    welcome = app.handle("GET", f"/welcome/{code_a}", {}).body.decode()
    assert "<strong>1</strong> confirmed referral" in welcome
    assert 'class="unlocked"' in welcome
    assert "One month free" in welcome
    assert f"https://acme.test/?ref={code_a}" in welcome
    assert code_b != code_a


def test_unknown_ref_sets_no_cookie(app):
    response = app.handle("GET", "/?ref=NOSUCHCODE", {})
    assert response.headers == []


def test_bad_confirm_link(app):
    assert app.handle("GET", "/confirm/nope", {}).status == 404


def test_welcome_hidden_until_confirmed(app, store):
    pending = store.signup("a@example.com").subscriber
    assert app.handle("GET", f"/welcome/{pending.code}", {}).status == 404


def test_unsubscribe_needs_a_post(app, store, mailer):
    _join(app, mailer, "a@example.com")
    subscriber = store.signup("a@example.com").subscriber
    path = f"/u/{subscriber.unsubscribe_token}"

    page = app.handle("GET", path, {})
    assert b"Unsubscribe me" in page.body
    assert store.recipients("c")

    done = app.handle("POST", path, {}, b"List-Unsubscribe=One-Click", "1.1.1.1")
    assert done.status == 200
    assert not store.recipients("c")
    assert app.handle("GET", f"/welcome/{subscriber.code}", {}).status == 404


def test_unsubscribe_unknown_token_does_not_leak(app):
    assert app.handle("POST", "/u/whatever", {}, b"", "1.1.1.1").status == 200


def test_static_files_are_whitelisted(app):
    assert app.handle("GET", "/static/style.css", {}).content_type.startswith(
        "text/css"
    )
    assert app.handle("GET", "/static/app.js", {}).status == 200
    assert app.handle("GET", "/static/..", {}).status == 404
    assert app.handle("GET", "/static/secret.txt", {}).status == 404


def test_unknown_routes_and_methods(app):
    assert app.handle("GET", "/admin", {}).status == 404
    assert app.handle("DELETE", "/", {}).status == 405


def test_real_server_serves_pages_with_security_headers(tmp_path):
    config = _config(host="127.0.0.1", port=0)
    store = Store(tmp_path / "live.db")
    server = make_server(config, App(config, store, ConsoleMailer(), background=False))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy")
        assert b"Acme Notes" in response.read()

        connection.request("HEAD", "/healthz")
        head = connection.getresponse()
        assert head.status == 200
        assert head.read() == b""
    finally:
        server.shutdown()
        server.server_close()


def test_load_config_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("LAUNCHPAD_SMTP_HOST", raising=False)
    path = tmp_path / "launchpad.toml"
    path.write_text(
        'product_name = "Acme"\nbase_url = "https://acme.test/"\n'
        '[[rewards]]\nreferrals = 5\nlabel = "B"\n'
        '[[rewards]]\nreferrals = 1\nlabel = "A"\n'
    )
    config = load_config(path)
    assert config.base_url == "https://acme.test"
    assert [r.label for r in config.rewards] == ["A", "B"]
    assert config.smtp is None


def test_load_config_smtp_comes_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LAUNCHPAD_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("LAUNCHPAD_SMTP_SSL", "1")
    config = load_config(None)
    assert (config.smtp.host, config.smtp.port, config.smtp.use_ssl) == (
        "smtp.test",
        465,
        True,
    )


def test_load_config_rejects_unknown_keys(tmp_path):
    path = tmp_path / "launchpad.toml"
    path.write_text("colour = 'red'\n")
    with pytest.raises(ValueError, match="unknown config key"):
        load_config(path)


def test_example_config_loads():
    from pathlib import Path

    example = Path(__file__).parents[1] / "launchpad" / "launchpad.example.toml"
    config = load_config(example)
    assert config.product_name == "Acme Notes"
    assert len(config.rewards) == 3
