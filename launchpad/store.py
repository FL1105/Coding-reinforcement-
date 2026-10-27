import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

RESEND_AFTER = timedelta(minutes=10)

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$"
)
_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    canonical TEXT NOT NULL UNIQUE,
    code TEXT NOT NULL UNIQUE,
    referred_by INTEGER REFERENCES subscribers(id),
    confirm_token TEXT NOT NULL UNIQUE,
    unsubscribe_token TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirm_sent_at TEXT,
    confirmed_at TEXT,
    unsubscribed_at TEXT
);
CREATE TABLE IF NOT EXISTS sends (
    campaign TEXT NOT NULL,
    subscriber_id INTEGER NOT NULL REFERENCES subscribers(id),
    sent_at TEXT NOT NULL,
    PRIMARY KEY (campaign, subscriber_id)
);
"""


@dataclass(frozen=True)
class Subscriber:
    id: int
    email: str
    code: str
    confirm_token: str
    unsubscribe_token: str
    confirmed: bool
    unsubscribed: bool
    referrals: int = 0


@dataclass(frozen=True)
class SignupResult:
    subscriber: Subscriber
    send_confirmation: bool


def parse_email(raw: str) -> tuple[str, str]:
    """Return (email, canonical); canonical drops +tags and gmail dots."""
    email = (raw or "").strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise ValueError("invalid email address")
    local, domain = email.rsplit("@", 1)
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    if not local:
        raise ValueError("invalid email address")
    return email, f"{local}@{domain}"


def mask_email(email: str) -> str:
    local, domain = email.rsplit("@", 1)
    return f"{local[0]}***@{domain}"


class Store:
    def __init__(self, path):
        self._path = str(path)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def signup(
        self, raw_email: str, ref_code=None, source="signup", now=None
    ) -> SignupResult:
        email, canonical = parse_email(raw_email)
        now = now or _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE canonical = ?", (canonical,)
            ).fetchone()
            if row is None:
                referrer = self._referrer_id(conn, ref_code)
                conn.execute(
                    "INSERT INTO subscribers (email, canonical, code, referred_by,"
                    " confirm_token, unsubscribe_token, source, created_at,"
                    " confirm_sent_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        email,
                        canonical,
                        self._new_code(conn),
                        referrer,
                        secrets.token_urlsafe(24),
                        secrets.token_urlsafe(24),
                        source,
                        _stamp(now),
                        _stamp(now),
                    ),
                )
                return SignupResult(self._by(conn, "canonical", canonical), True)

            if row["unsubscribed_at"] is not None:
                conn.execute(
                    "UPDATE subscribers SET unsubscribed_at = NULL,"
                    " confirmed_at = NULL, confirm_token = ?,"
                    " unsubscribe_token = ?, confirm_sent_at = NULL WHERE id = ?",
                    (secrets.token_urlsafe(24), secrets.token_urlsafe(24), row["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM subscribers WHERE id = ?", (row["id"],)
                ).fetchone()

            resend = row["confirmed_at"] is None and _resend_due(
                row["confirm_sent_at"], now
            )
            if resend:
                conn.execute(
                    "UPDATE subscribers SET confirm_sent_at = ? WHERE id = ?",
                    (_stamp(now), row["id"]),
                )
            return SignupResult(self._by(conn, "id", row["id"]), resend)

    def confirm(self, token: str, now=None) -> Subscriber | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM subscribers WHERE confirm_token = ?"
                " AND unsubscribed_at IS NULL",
                (token,),
            ).fetchone()
            if row is None:
                return None
            if row["confirmed_at"] is None:
                conn.execute(
                    "UPDATE subscribers SET confirmed_at = ? WHERE id = ?",
                    (_stamp(now or _now()), row["id"]),
                )
            return self._by(conn, "id", row["id"])

    def unsubscribe(self, token: str, now=None) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE subscribers SET unsubscribed_at = COALESCE(unsubscribed_at, ?)"
                " WHERE unsubscribe_token = ?",
                (_stamp(now or _now()), token),
            )
            return cursor.rowcount == 1

    def by_code(self, code: str) -> Subscriber | None:
        with self._connect() as conn:
            return self._by(conn, "code", code)

    def code_exists(self, code: str) -> bool:
        return self.by_code(code) is not None

    def import_confirmed(self, emails, now=None) -> tuple[int, int]:
        """Add already-consented contacts as confirmed. Returns (added, skipped)."""
        now = now or _now()
        added = skipped = 0
        with self._connect() as conn:
            for raw in emails:
                try:
                    email, canonical = parse_email(raw)
                except ValueError:
                    skipped += 1
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM subscribers WHERE canonical = ?", (canonical,)
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                conn.execute(
                    "INSERT INTO subscribers (email, canonical, code, confirm_token,"
                    " unsubscribe_token, source, created_at, confirmed_at)"
                    " VALUES (?, ?, ?, ?, ?, 'import', ?, ?)",
                    (
                        email,
                        canonical,
                        self._new_code(conn),
                        secrets.token_urlsafe(24),
                        secrets.token_urlsafe(24),
                        _stamp(now),
                        _stamp(now),
                    ),
                )
                added += 1
        return added, skipped

    def recipients(self, campaign: str) -> list[Subscriber]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM subscribers WHERE confirmed_at IS NOT NULL"
                " AND unsubscribed_at IS NULL AND id NOT IN"
                " (SELECT subscriber_id FROM sends WHERE campaign = ?)"
                " ORDER BY id",
                (campaign,),
            ).fetchall()
            return [self._by(conn, "id", row["id"]) for row in rows]

    def mark_sent(self, campaign: str, subscriber_id: int, now=None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sends (campaign, subscriber_id, sent_at)"
                " VALUES (?, ?, ?)",
                (campaign, subscriber_id, _stamp(now or _now())),
            )

    def stats(self, top=5) -> dict:
        with self._connect() as conn:
            counts = conn.execute(
                "SELECT COUNT(*) AS total,"
                " COUNT(confirmed_at) AS confirmed,"
                " COUNT(unsubscribed_at) AS unsubscribed,"
                " COALESCE(SUM(referred_by IS NOT NULL AND confirmed_at IS NOT NULL),"
                " 0) AS referred FROM subscribers"
            ).fetchone()
            leaders = conn.execute(
                "SELECT s.email, COUNT(r.id) AS referrals FROM subscribers s"
                " JOIN subscribers r ON r.referred_by = s.id"
                " AND r.confirmed_at IS NOT NULL"
                " GROUP BY s.id ORDER BY referrals DESC, s.id LIMIT ?",
                (top,),
            ).fetchall()
        return {
            "total": counts["total"],
            "confirmed": counts["confirmed"],
            "unsubscribed": counts["unsubscribed"],
            "referred": counts["referred"],
            "top_referrers": [
                (mask_email(row["email"]), row["referrals"]) for row in leaders
            ],
        }

    def _referrer_id(self, conn, code):
        if not code:
            return None
        row = conn.execute(
            "SELECT id FROM subscribers WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
        return row["id"] if row else None

    def _new_code(self, conn) -> str:
        while True:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
            if not conn.execute(
                "SELECT 1 FROM subscribers WHERE code = ?", (code,)
            ).fetchone():
                return code

    def _by(self, conn, column, value) -> Subscriber | None:
        row = conn.execute(
            f"SELECT * FROM subscribers WHERE {column} = ?", (value,)
        ).fetchone()
        if row is None:
            return None
        referrals = conn.execute(
            "SELECT COUNT(*) FROM subscribers"
            " WHERE referred_by = ? AND confirmed_at IS NOT NULL",
            (row["id"],),
        ).fetchone()[0]
        return Subscriber(
            id=row["id"],
            email=row["email"],
            code=row["code"],
            confirm_token=row["confirm_token"],
            unsubscribe_token=row["unsubscribe_token"],
            confirmed=row["confirmed_at"] is not None,
            unsubscribed=row["unsubscribed_at"] is not None,
            referrals=referrals,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _resend_due(sent_at, now) -> bool:
    if sent_at is None:
        return True
    return now - datetime.fromisoformat(sent_at) >= RESEND_AFTER
