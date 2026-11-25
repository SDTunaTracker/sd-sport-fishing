"""Data-health alerts by email and text message.

Problems come from src.completeness.check(). Each problem has a stable key, and
logs/alert_state.json remembers which keys are open, so:

* a new problem sends one alert,
* a problem that is still open sends at most one reminder digest per day,
* a problem that clears sends one "recovered" notice.

Delivery is SMTP email. Texts are off by default. ALERT_SMS_TO can be set to a
carrier's email-to-SMS gateway, but AT&T shut its gateways down in June 2025,
so for AT&T numbers texts would need an SMS API (not implemented).

Configuration lives only in the gitignored .env at the repo root:

    ALERT_EMAIL_TO=you@example.com
    ALERT_SMS_TO=7605551234@vtext.com     # optional; carrier gateway address
    ALERT_SMTP_HOST=smtp.mail.yahoo.com
    ALERT_SMTP_PORT=465                   # 465 = SSL, 587 = STARTTLS
    ALERT_SMTP_USER=sender@example.com
    ALERT_SMTP_PASSWORD=<app password, typed in by the owner>
    ALERT_FROM=sender@example.com         # defaults to ALERT_SMTP_USER

With no SMTP settings (e.g. in GitHub Actions) alerts are logged and skipped.

    .venv\\Scripts\\python.exe -m src.alerts --test     # send a test alert
"""
from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "logs" / "alert_state.json"
DIGEST_EVERY = timedelta(hours=24)
SITE = "thetunatracker.com"


@dataclass
class Config:
    email_to: str | None
    sms_to: str | None
    host: str | None
    port: int
    user: str | None
    password: str | None
    sender: str | None

    @property
    def ready(self) -> bool:
        return bool(self.host and self.user and self.password and (self.email_to or self.sms_to))


def load_config() -> Config:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    g = os.environ.get
    return Config(
        email_to=g("ALERT_EMAIL_TO") or None,
        sms_to=g("ALERT_SMS_TO") or None,
        host=g("ALERT_SMTP_HOST") or None,
        port=int(g("ALERT_SMTP_PORT") or 465),
        user=g("ALERT_SMTP_USER") or None,
        password=g("ALERT_SMTP_PASSWORD") or None,
        sender=g("ALERT_FROM") or g("ALERT_SMTP_USER") or None,
    )


def _send(cfg: Config, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if cfg.port == 465:
        with smtplib.SMTP_SSL(cfg.host, cfg.port, context=ctx, timeout=30) as s:
            s.login(cfg.user, cfg.password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(cfg.user, cfg.password)
            s.send_message(msg)


def deliver(subject: str, body: str, sms: str, cfg: Config | None = None) -> list[str]:
    """Send email (full body) and text (short line). Returns channels that worked."""
    cfg = cfg or load_config()
    if not cfg.ready:
        log.info("alerts not configured; would send: %s", subject)
        return []
    if not cfg.sms_to:
        log.info("SMS alerts off (ALERT_SMS_TO not set); sending email only")
    sent = []
    for chan, to, subj, text in (("email", cfg.email_to, subject, body),
                                 ("sms", cfg.sms_to, "", sms[:300])):
        if not to:
            continue
        try:
            _send(cfg, to, subj, text)
            sent.append(chan)
        except Exception as e:  # noqa: BLE001 — alerting must never crash a run
            log.warning("alert %s delivery failed: %s", chan, e)
    return sent


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"open": {}, "last_digest": None}


def plan(problems, state: dict, now: datetime) -> tuple[list, list[str], bool]:
    """Pure decision step: (new problems, recovered keys, send_digest)."""
    open_ = state.get("open", {})
    cur = {p.key: p for p in problems}
    new = [p for k, p in cur.items() if k not in open_]
    recovered = [k for k in open_ if k not in cur]
    last = state.get("last_digest")
    due = bool(cur) and not new and (
        last is None or now - datetime.fromisoformat(last) >= DIGEST_EVERY)
    return new, recovered, due


def process(problems, *, state_path: Path = STATE_PATH, now: datetime | None = None,
            send=deliver) -> dict:
    """Send whatever this run's problems call for and update alert state."""
    now = now or datetime.now(timezone.utc)
    state = _load_state(state_path)
    new, recovered, digest = plan(problems, state, now)
    open_ = state.setdefault("open", {})
    actions: dict = {"new": [p.key for p in new], "recovered": recovered, "digest": digest}

    if new:
        crit = any(p.severity == "critical" for p in new)
        blocked = any(p.severity == "blocked" for p in new)
        label = ("DATA COLLECTION BROKEN" if crit
                 else "SITE BLOCKING US (CAPTCHA)" if blocked else "data warning")
        lines = [f"- [{p.severity}] {p.detail}" for p in new]
        still = [p for p in problems if p not in new]
        if still:
            lines += ["", "Still open:"] + [f"- {p.detail}" for p in still]
        send(f"[{SITE}] {label}: {len(new)} new problem(s)",
             "\n".join(lines) + "\n\nDetails: logs/completeness.json",
             f"TunaTracker: {new[0].detail}" + (f" (+{len(new) - 1} more)" if len(new) > 1 else ""))
        state["last_digest"] = now.isoformat()
    elif digest:
        send(f"[{SITE}] daily reminder: {len(problems)} open data problem(s)",
             "\n".join(f"- {p.detail}" for p in problems),
             f"TunaTracker: {len(problems)} data problem(s) still open")
        state["last_digest"] = now.isoformat()

    if recovered:
        send(f"[{SITE}] recovered: {len(recovered)} problem(s) cleared",
             "\n".join(f"- {open_[k]['detail']}" for k in recovered),
             f"TunaTracker recovered: {open_[recovered[0]]['detail'][:120]}")
        for k in recovered:
            open_.pop(k, None)

    for p in problems:
        open_.setdefault(p.key, {"since": now.isoformat(), "detail": p.detail})
        open_[p.key]["detail"] = p.detail
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return actions


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    if "--test" in argv:
        cfg = load_config()
        if not cfg.ready:
            print("Not configured: set ALERT_SMTP_HOST/USER/PASSWORD and ALERT_EMAIL_TO or "
                  "ALERT_SMS_TO in .env")
            return 1
        sent = deliver(f"[{SITE}] test alert",
                       "This is a test of the Tuna Tracker data-health alerts.\n"
                       "If you got this, email alerts work.",
                       "TunaTracker test alert: texts work.", cfg)
        print(f"sent via: {', '.join(sent) or 'nothing (see warnings above)'}")
        return 0 if sent else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
