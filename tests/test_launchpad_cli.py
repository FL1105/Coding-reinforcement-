import json
import stat

import pytest

from launchpad.__main__ import main
from launchpad.store import Store


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "launchpad.toml"
    path.write_text(
        f'product_name = "Acme"\nbase_url = "https://acme.test"\n'
        f'postal_address = "1 Main St"\ndb_path = "{tmp_path / "test.db"}"\n'
        "send_delay_seconds = 0\n"
    )
    return path


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "body.txt"
    path.write_text("Join: {{ referral_link }}")
    return path


def _run(config_path, *args):
    return main(["--config", str(config_path), *args])


def _import(config_path, tmp_path, emails):
    contacts = tmp_path / "contacts.csv"
    contacts.write_text("\n".join(["email", *emails]) + "\n")
    assert _run(config_path, "import", str(contacts), "--i-have-consent") == 0


def test_import_requires_consent_flag(config_path, tmp_path, capsys):
    contacts = tmp_path / "contacts.csv"
    contacts.write_text("a@example.com\n")
    assert _run(config_path, "import", str(contacts)) == 1
    assert "--i-have-consent" in capsys.readouterr().err
    assert Store(tmp_path / "test.db").stats()["total"] == 0


def test_import_accepts_csv_with_header_and_plain_lists(config_path, tmp_path, capsys):
    _import(config_path, tmp_path, ["a@example.com", "b@example.com", "bad"])
    assert "Imported 2, skipped 1" in capsys.readouterr().out

    plain = tmp_path / "plain.txt"
    plain.write_text("c@example.com\n")
    assert _run(config_path, "import", str(plain), "--i-have-consent") == 0
    assert Store(tmp_path / "test.db").stats()["total"] == 3


def test_send_defaults_to_dry_run(config_path, tmp_path, template, capsys):
    _import(config_path, tmp_path, ["a@example.com"])
    outbox = tmp_path / "outbox.jsonl"
    args = ["send", "--name", "c1", "--subject", "Hi", "--text", str(template)]
    assert _run(config_path, *args, "--outbox", str(outbox)) == 0
    assert "Dry run: 1 recipient" in capsys.readouterr().out
    assert not outbox.exists()


def test_send_to_outbox_writes_one_private_line_per_subscriber(
    config_path, tmp_path, template, capsys
):
    _import(config_path, tmp_path, ["a@example.com", "b@example.com"])
    outbox = tmp_path / "outbox.jsonl"
    args = ["send", "--name", "c1", "--subject", "Hi", "--text", str(template)]
    assert _run(config_path, *args, "--outbox", str(outbox), "--execute") == 0
    assert "Queued 2, failed 0 of 2" in capsys.readouterr().out

    records = [json.loads(line) for line in outbox.read_text().splitlines()]
    assert [r["to"] for r in records] == ["a@example.com", "b@example.com"]
    first = records[0]
    assert first["subject"] == "Hi"
    assert "https://acme.test/?ref=" in first["text"]
    assert "Unsubscribe: https://acme.test/u/" in first["text"]
    assert "1 Main St" in first["text"]
    assert first["list_unsubscribe"].startswith("<https://acme.test/u/")
    assert first["html"] is None
    assert stat.S_IMODE(outbox.stat().st_mode) == 0o600

    assert _run(config_path, *args, "--outbox", str(outbox), "--execute") == 0
    assert len(outbox.read_text().splitlines()) == 2


def test_send_without_postal_address_fails(tmp_path, template, capsys):
    path = tmp_path / "launchpad.toml"
    path.write_text(f'db_path = "{tmp_path / "x.db"}"\n')
    Store(tmp_path / "x.db").import_confirmed(["a@example.com"])
    args = ["send", "--name", "c1", "--subject", "Hi", "--text", str(template)]
    assert _run(path, *args, "--outbox", str(tmp_path / "o.jsonl"), "--execute") == 1
    assert "postal_address" in capsys.readouterr().err
