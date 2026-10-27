import re
import smtplib
import threading
import time
import traceback
from dataclasses import dataclass, field
from functools import cache
from html import escape
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote, urlsplit

from .mailer import confirmation_message
from .store import parse_email

_WEB_DIR = Path(__file__).parent / "web"
_STATIC = {
    "style.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
}
_MAX_BODY = 8 * 1024
_SIGNUPS_PER_HOUR = 10
_REF_COOKIE = "lp_ref"
_REF_COOKIE_AGE = 30 * 24 * 3600
_SECURITY_HEADERS = [
    (
        "Content-Security-Policy",
        "default-src 'self'; frame-ancestors 'none'; form-action 'self'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
]


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/html; charset=utf-8"
    headers: list = field(default_factory=list)


class App:
    def __init__(self, config, store, mailer, background=True, clock=time.monotonic):
        self._config = config
        self._store = store
        self._mailer = mailer
        self._background = background
        self._clock = clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._secure = config.base_url.startswith("https://")

    def handle(self, method, target, headers, body=b"", client_ip="") -> Response:
        parts = urlsplit(target)
        path = parts.path
        query = parse_qs(parts.query)
        try:
            if method in ("GET", "HEAD"):
                return self._get(path, query, headers)
            if method == "POST":
                return self._post(path, headers, body, client_ip)
        except Exception:  # noqa: BLE001 - last-resort handler for a request
            traceback.print_exc()
            return self._message(
                500, "Something went wrong", "Please try again in a moment."
            )
        return self._message(405, "Not allowed", "That request isn't supported.")

    def _get(self, path, query, headers) -> Response:
        if path == "/":
            return self._landing(query, headers)
        if path == "/healthz":
            return Response(body=b"ok", content_type="text/plain")
        if match := re.fullmatch(r"/static/([\w.]+)", path):
            return self._static(match.group(1))
        if match := re.fullmatch(r"/confirm/([\w-]+)", path):
            return self._confirm(match.group(1))
        if match := re.fullmatch(r"/welcome/([\w-]+)", path):
            return self._welcome(match.group(1))
        if match := re.fullmatch(r"/u/([\w-]+)", path):
            return self._unsubscribe_page(match.group(1))
        return self._not_found()

    def _post(self, path, headers, body, client_ip) -> Response:
        if len(body) > _MAX_BODY:
            return self._message(413, "Too large", "That request was too big.")
        if path == "/signup":
            return self._signup(headers, body, client_ip)
        if match := re.fullmatch(r"/u/([\w-]+)", path):
            return self._unsubscribe(match.group(1))
        return self._not_found()

    def _landing(self, query, headers, notice="", email="", status=200) -> Response:
        ref = self._valid_ref((query.get("ref") or [""])[0])
        cookie_ref = self._cookie(headers, _REF_COOKIE)
        extra = []
        if ref:
            extra.append(("Set-Cookie", self._ref_cookie(ref)))
        else:
            ref = self._valid_ref(cookie_ref)
        if not notice and ref:
            notice = (
                '<p class="notice">A friend invited you. '
                "Join to get early access together.</p>"
            )
        config = self._config
        page = self._page(
            config.product_name,
            "index.html",
            description=escape(config.description or config.tagline),
            lede=(
                f'<p class="lede">{escape(config.description)}</p>'
                if config.description
                else ""
            ),
            product_name=escape(config.product_name),
            tagline=escape(config.tagline),
            notice=notice,
            ref=escape(ref),
            email=escape(email),
            benefits=self._benefits(),
            rewards=self._rewards(0),
        )
        return Response(status, page, headers=extra)

    def _signup(self, headers, body, client_ip) -> Response:
        if not headers.get("Content-Type", "").startswith(
            "application/x-www-form-urlencoded"
        ):
            return self._message(415, "Unsupported", "Please use the signup form.")
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)

        if _field(form, "leave_blank"):
            return self._check_inbox()
        if not self._allow(client_ip):
            return self._message(
                429, "Slow down", "Too many signups from your network. Try later."
            )
        email = _field(form, "email")
        try:
            parse_email(email)
        except ValueError:
            notice = '<p class="notice error">Please enter a valid email address.</p>'
            return self._landing({}, headers, notice, email, status=400)

        ref = _field(form, "ref") or self._cookie(headers, _REF_COOKIE)
        result = self._store.signup(email, ref_code=ref)
        if result.send_confirmation:
            self._deliver(confirmation_message(self._config, result.subscriber))
        return self._check_inbox()

    def _check_inbox(self) -> Response:
        return self._message(
            200,
            "Check your inbox",
            "We sent you a link to confirm your email. "
            "It can take a minute, and it may land in spam.",
        )

    def _confirm(self, token) -> Response:
        subscriber = self._store.confirm(token)
        if subscriber is None:
            return self._message(
                404, "Link expired", "That confirmation link isn't valid anymore."
            )
        return Response(
            303, headers=[("Location", f"/welcome/{subscriber.code}")], body=b""
        )

    def _welcome(self, code) -> Response:
        subscriber = self._store.by_code(code.upper())
        if subscriber is None or not subscriber.confirmed or subscriber.unsubscribed:
            return self._not_found()
        config = self._config
        link = f"{config.base_url}/?ref={subscriber.code}"
        share = f"I just joined the waitlist for {config.product_name}. Join me: {link}"
        count = subscriber.referrals
        page = self._page(
            f"You're in | {config.product_name}",
            "welcome.html",
            description=escape(config.tagline),
            link=escape(link),
            count=count,
            count_label="referral" if count == 1 else "referrals",
            progress=self._progress(count),
            mailto=escape(
                f"mailto:?subject={quote('Join me on ' + config.product_name)}"
                f"&body={quote(share)}"
            ),
            twitter=escape(f"https://twitter.com/intent/tweet?text={quote(share)}"),
            whatsapp=escape(f"https://wa.me/?text={quote(share)}"),
            rewards=self._rewards(count),
        )
        return Response(body=page)

    def _unsubscribe_page(self, token) -> Response:
        return self._message(
            200,
            "Unsubscribe",
            "Click below to stop receiving emails from us.",
            extra=(
                f'<form method="post" action="/u/{escape(token)}">'
                '<button type="submit">Unsubscribe me</button></form>'
            ),
        )

    def _unsubscribe(self, token) -> Response:
        self._store.unsubscribe(token)
        return self._message(
            200, "You're unsubscribed", "You won't receive any more emails from us."
        )

    def _static(self, name) -> Response:
        content_type = _STATIC.get(name)
        if content_type is None:
            return self._not_found()
        return Response(
            body=(_WEB_DIR / name).read_bytes(),
            content_type=content_type,
            headers=[("Cache-Control", "public, max-age=3600")],
        )

    def _not_found(self) -> Response:
        return self._message(404, "Not found", "We couldn't find that page.")

    def _message(self, status, heading, message, extra="") -> Response:
        config = self._config
        page = self._page(
            f"{heading} | {config.product_name}",
            "message.html",
            description=escape(config.tagline),
            heading=escape(heading),
            message=escape(message),
            extra=extra,
        )
        return Response(status, page)

    def _page(self, title, template, description, **values) -> bytes:
        body = _template(template).substitute(**values)
        config = self._config
        footer = escape(config.product_name)
        if config.postal_address:
            footer += f" &middot; {escape(config.postal_address)}"
        return (
            _template("layout.html")
            .substitute(
                title=escape(title),
                description=description,
                body=body,
                footer=footer,
            )
            .encode()
        )

    def _benefits(self) -> str:
        if not self._config.benefits:
            return ""
        items = "".join(f"<li>{escape(item)}</li>" for item in self._config.benefits)
        return f'<section><h2>Why join</h2><ul class="benefits">{items}</ul></section>'

    def _rewards(self, count) -> str:
        rewards = self._config.rewards
        if not rewards:
            return ""
        items = "".join(
            f'<li class="{"unlocked" if count >= reward.referrals else ""}">'
            f"{reward.referrals} {'referral' if reward.referrals == 1 else 'referrals'}"
            f": {escape(reward.label)}</li>"
            for reward in rewards
        )
        return f'<section><h2>Rewards</h2><ul class="rewards">{items}</ul></section>'

    def _progress(self, count) -> str:
        upcoming = next((r for r in self._config.rewards if r.referrals > count), None)
        if upcoming is None:
            return ""
        return (
            f"<p>Next reward: <strong>{escape(upcoming.label)}</strong> at "
            f"{upcoming.referrals} referrals.</p>"
            f'<progress max="{upcoming.referrals}" value="{count}"></progress>'
        )

    def _valid_ref(self, code) -> str:
        code = (code or "").strip().upper()
        if re.fullmatch(r"[A-Z0-9]{4,16}", code) and self._store.code_exists(code):
            return code
        return ""

    def _ref_cookie(self, code) -> str:
        cookie = f"{_REF_COOKIE}={code}; Max-Age={_REF_COOKIE_AGE}; Path=/"
        cookie += "; HttpOnly; SameSite=Lax"
        return cookie + ("; Secure" if self._secure else "")

    def _cookie(self, headers, name) -> str:
        jar = SimpleCookie()
        try:
            jar.load(headers.get("Cookie", ""))
        except CookieError:
            return ""
        morsel = jar.get(name)
        return morsel.value if morsel else ""

    def _allow(self, client_ip) -> bool:
        now = self._clock()
        with self._lock:
            if len(self._hits) > 10_000:
                self._hits = {
                    ip: times
                    for ip, times in self._hits.items()
                    if times and now - times[-1] < 3600
                }
            recent = [t for t in self._hits.get(client_ip, []) if now - t < 3600]
            if len(recent) >= _SIGNUPS_PER_HOUR:
                self._hits[client_ip] = recent
                return False
            recent.append(now)
            self._hits[client_ip] = recent
            return True

    def _deliver(self, message) -> None:
        if self._background:
            threading.Thread(target=self._send, args=(message,), daemon=True).start()
        else:
            self._send(message)

    def _send(self, message) -> None:
        try:
            self._mailer.send(message)
        except (smtplib.SMTPException, OSError) as error:
            print(f"confirmation email failed: {type(error).__name__}")


def _field(form, name) -> str:
    return (form.get(name) or [""])[0]


@cache
def _template(name) -> Template:
    return Template((_WEB_DIR / name).read_text())


_TOKEN_PATH = re.compile(r"/(confirm|u|welcome)/\S+")


def make_server(config, app) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = _MAX_BODY + 1
            if length > _MAX_BODY:
                response = Response(
                    413, b"Request too large", content_type="text/plain"
                )
                self.close_connection = True
            else:
                body = self.rfile.read(length) if length else b""
                response = app.handle(
                    method, self.path, self.headers, body, self._client_ip()
                )
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for name, value in _SECURITY_HEADERS:
                if not any(h[0].lower() == name.lower() for h in response.headers):
                    self.send_header(name, value)
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(response.body)

        def _client_ip(self):
            if config.trust_proxy:
                forwarded = self.headers.get("X-Forwarded-For", "")
                if forwarded:
                    return forwarded.split(",")[-1].strip()
            return self.client_address[0]

        def log_message(self, format, *args):
            line = _TOKEN_PATH.sub(r"/\1/<redacted>", format % args)
            print(f"{self.address_string()} {line}")

    return ThreadingHTTPServer((config.host, config.port), Handler)
