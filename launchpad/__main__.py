import argparse
import csv
import os
import sys
from pathlib import Path

from .campaigns import send_campaign
from .config import load_config
from .mailer import make_mailer
from .store import Store
from .web import App, make_server


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="launchpad", description=__doc__)
    parser.add_argument(
        "--config",
        default=os.environ.get("LAUNCHPAD_CONFIG"),
        help="path to a TOML config (default: $LAUNCHPAD_CONFIG or ./launchpad.toml)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the landing page")
    serve.set_defaults(run=_serve)

    send = commands.add_parser("send", help="email confirmed subscribers")
    send.add_argument("--name", required=True, help="campaign id; never sent twice")
    send.add_argument("--subject", required=True)
    send.add_argument("--text", required=True, help="plain-text body template file")
    send.add_argument("--html", help="optional HTML body template file")
    send.add_argument("--limit", type=int, help="send to at most this many people")
    send.add_argument(
        "--execute", action="store_true", help="actually send (default is a dry run)"
    )
    send.set_defaults(run=_send)

    load = commands.add_parser("import", help="add contacts who already opted in")
    load.add_argument("file", help="one email per line, or a CSV with an email column")
    load.add_argument(
        "--i-have-consent",
        action="store_true",
        help="confirm these people agreed to receive email from you",
    )
    load.set_defaults(run=_import)

    stats = commands.add_parser("stats", help="show signup and referral numbers")
    stats.set_defaults(run=_stats)
    return parser


def _load(args):
    path = args.config
    if path is None and Path("launchpad.toml").exists():
        path = "launchpad.toml"
    config = load_config(path)
    return config, Store(config.db_path)


def _serve(args) -> int:
    config, store = _load(args)
    mailer = make_mailer(config)
    if config.smtp is None:
        print("SMTP is not configured: emails will be printed here, not sent.")
    server = make_server(config, App(config, store, mailer))
    print(f"Serving {config.product_name} at http://{config.host}:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        mailer.close()
    return 0


def _send(args) -> int:
    config, store = _load(args)
    text = Path(args.text).read_text()
    html = Path(args.html).read_text() if args.html else None
    mailer = make_mailer(config)
    try:
        report = send_campaign(
            store,
            config,
            mailer,
            args.name,
            args.subject,
            text,
            html,
            execute=args.execute,
            limit=args.limit,
        )
    finally:
        mailer.close()
    if not report.executed:
        print(f"Dry run: {report.recipients} recipient(s) would get this email.")
        print("Add --execute to send it.")
        return 0
    print(f"Sent {report.sent}, failed {report.failed} of {report.recipients}.")
    return 0 if report.failed == 0 else 1


def _import(args) -> int:
    if not args.i_have_consent:
        raise ValueError(
            "only import people who agreed to hear from you; "
            "pass --i-have-consent to confirm"
        )
    _, store = _load(args)
    added, skipped = store.import_confirmed(_read_emails(args.file))
    print(f"Imported {added}, skipped {skipped} (duplicates or invalid).")
    return 0


def _read_emails(path) -> list[str]:
    with Path(path).open(newline="") as handle:
        rows = list(csv.reader(handle))
    if rows and "email" in [cell.strip().lower() for cell in rows[0]]:
        column = [cell.strip().lower() for cell in rows[0]].index("email")
        return [row[column] for row in rows[1:] if len(row) > column]
    return [row[0] for row in rows if row]


def _stats(args) -> int:
    _, store = _load(args)
    stats = store.stats()
    print(f"Signups: {stats['total']}")
    print(f"Confirmed: {stats['confirmed']}")
    print(f"Unsubscribed: {stats['unsubscribed']}")
    print(f"Joined through a referral: {stats['referred']}")
    for email, count in stats["top_referrers"]:
        print(f"  {email}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
