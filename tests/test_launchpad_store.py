from datetime import UTC, datetime, timedelta

import pytest

from launchpad.store import RESEND_AFTER, Store, mask_email, parse_email

T0 = datetime(2025, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


def _joined(store, email, ref=None, now=T0):
    subscriber = store.signup(email, ref_code=ref, now=now).subscriber
    return store.confirm(subscriber.confirm_token, now=now)


def test_parse_email_canonicalizes():
    assert parse_email("  Jane.Doe+news@Gmail.com ") == (
        "jane.doe+news@gmail.com",
        "janedoe@gmail.com",
    )
    assert parse_email("a.b+x@example.com")[1] == "a.b@example.com"


@pytest.mark.parametrize(
    "raw", ["", "nope", "a@b", "a b@c.com", "x@y.com\nBcc: z", None]
)
def test_parse_email_rejects_garbage(raw):
    with pytest.raises(ValueError):
        parse_email(raw)


def test_mask_email():
    assert mask_email("jane@example.com") == "j***@example.com"


def test_signup_creates_pending_subscriber(store):
    result = store.signup("a@example.com", now=T0)
    assert result.send_confirmation
    assert not result.subscriber.confirmed
    assert len(result.subscriber.code) == 8


def test_repeat_signup_is_throttled(store):
    store.signup("a@example.com", now=T0)
    soon = store.signup("a@example.com", now=T0 + timedelta(minutes=1))
    later = store.signup("a@example.com", now=T0 + RESEND_AFTER)
    assert not soon.send_confirmation
    assert later.send_confirmation


def test_confirmed_signup_never_resends(store):
    _joined(store, "a@example.com")
    again = store.signup("a@example.com", now=T0 + timedelta(days=1))
    assert not again.send_confirmation
    assert again.subscriber.confirmed


def test_referrals_count_only_after_confirmation(store):
    referrer = _joined(store, "a@example.com")
    pending = store.signup("b@example.com", ref_code=referrer.code, now=T0).subscriber
    assert store.by_code(referrer.code).referrals == 0

    store.confirm(pending.confirm_token)
    assert store.by_code(referrer.code).referrals == 1


def test_referral_code_is_case_insensitive_and_unknown_codes_are_ignored(store):
    referrer = _joined(store, "a@example.com")
    _joined(store, "b@example.com", ref=referrer.code.lower())
    _joined(store, "c@example.com", ref="NOSUCHCODE")
    assert store.by_code(referrer.code).referrals == 1
    assert store.stats()["referred"] == 1


def test_alias_cannot_refer_itself(store):
    referrer = _joined(store, "a@example.com")
    again = store.signup("a+second@example.com", ref_code=referrer.code, now=T0)
    assert again.subscriber.id == referrer.id
    assert store.by_code(referrer.code).referrals == 0


def test_confirm_unknown_token(store):
    assert store.confirm("nope") is None


def test_unsubscribe_then_resignup_requires_new_confirmation(store):
    joined = _joined(store, "a@example.com")
    assert store.unsubscribe(joined.unsubscribe_token)
    assert store.confirm(joined.confirm_token) is None

    again = store.signup("a@example.com", now=T0 + timedelta(days=1))
    assert again.send_confirmation
    assert not again.subscriber.confirmed
    assert again.subscriber.confirm_token != joined.confirm_token


def test_unsubscribe_unknown_token(store):
    assert not store.unsubscribe("nope")


def test_recipients_are_confirmed_active_and_unsent(store):
    sent = _joined(store, "sent@example.com")
    _joined(store, "ok@example.com")
    gone = _joined(store, "gone@example.com")
    store.signup("pending@example.com", now=T0)
    store.unsubscribe(gone.unsubscribe_token)
    store.mark_sent("launch", sent.id)

    assert [s.email for s in store.recipients("launch")] == ["ok@example.com"]
    assert len(store.recipients("other-campaign")) == 2


def test_import_confirmed_skips_duplicates_and_invalid(store):
    _joined(store, "a@example.com")
    added, skipped = store.import_confirmed(
        ["b@example.com", "A@example.com", "bad", "b+dup@example.com"]
    )
    assert (added, skipped) == (1, 3)
    assert {s.email for s in store.recipients("x")} == {
        "a@example.com",
        "b@example.com",
    }


def test_stats_masks_top_referrers(store):
    referrer = _joined(store, "jane@example.com")
    _joined(store, "b@example.com", ref=referrer.code)
    _joined(store, "c@example.com", ref=referrer.code)
    stats = store.stats()
    assert stats["total"] == 3
    assert stats["confirmed"] == 3
    assert stats["top_referrers"] == [("j***@example.com", 2)]
