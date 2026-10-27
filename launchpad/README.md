# launchpad

A waitlist landing page with a built-in referral system, plus a tool to email
your subscribers. Standard library only: no packages to install.

## How the growth loop works

1. A visitor joins on the landing page and confirms their email (double opt-in).
2. They land on a page with their personal link (`/?ref=CODE`), share buttons
   and progress toward your reward tiers.
3. You send a campaign. Every email carries *that person's* referral link, so
   each send turns your list into a sharing channel.
4. A referral only counts once the friend confirms their email.

## Quick start

```bash
cp launchpad/launchpad.example.toml launchpad.toml   # edit product, rewards, URL
python -m launchpad serve                            # http://localhost:8000
```

Without SMTP settings, emails are printed to the terminal instead of sent, so
you can try the whole flow locally.

To send real email, set these environment variables (use any SMTP provider:
Postmark, SendGrid, Amazon SES, Mailgun, ...):

```bash
export LAUNCHPAD_SMTP_HOST=smtp.example.com
export LAUNCHPAD_SMTP_PORT=587          # 465 with LAUNCHPAD_SMTP_SSL=1
export LAUNCHPAD_SMTP_USER=...
export LAUNCHPAD_SMTP_PASSWORD=...
```

## Commands

```bash
python -m launchpad serve                  # run the site
python -m launchpad stats                  # signups, confirmations, top referrers

# Email everyone who confirmed. Dry run unless --execute is given.
python -m launchpad send --name launch-1 --subject "We're live" \
    --text launchpad/examples/announcement.txt \
    --html launchpad/examples/announcement.html
python -m launchpad send --name launch-1 --subject "We're live" \
    --text launchpad/examples/announcement.txt --execute

# Add people who already agreed to hear from you (customers, etc.)
python -m launchpad import contacts.csv --i-have-consent
```

Template variables: `{{ product_name }}`, `{{ referral_link }}`,
`{{ referral_count }}`, `{{ unsubscribe_link }}`, `{{ postal_address }}`.
Every email also gets an unsubscribe link, your postal address and
`List-Unsubscribe` headers added automatically.

A campaign `--name` is remembered: re-running the same name skips people who
already got it, so an interrupted send can be resumed safely.

## Send only to people who opted in

Mass-emailing people who never agreed to hear from you (bought or scraped
lists) breaks CAN-SPAM, GDPR and similar laws, gets your domain blocked, and
produces no useful referrals. This tool only emails people who confirmed
through the page, or whom you explicitly import as having consented.
`send --execute` refuses to run until `postal_address` is set in the config.

## Before going live

- Host it behind HTTPS and set `base_url` to the public `https://` address.
- Set `trust_proxy = true` only when behind a proxy you control.
- On your sending domain, set up SPF, DKIM and DMARC, or mail goes to spam.
- Start with small batches (`--limit 50`) and watch bounces and complaints.
- Back up `launchpad.db` (it is your subscriber list).

## Abuse protection included

Confirmation emails are rate limited per address and per IP, a hidden
honeypot field blocks simple bots, `+tag` and Gmail-dot aliases cannot refer
themselves, and referrals count only after the referred person confirms.
