#!/usr/bin/env python3
"""Mail per SMTP verschicken – nur stdlib (smtplib).

Nutzt SMTP_HOST, SMTP_USER, SMTP_PASS (aus .env). Optional SMTP_PORT (Default 587
STARTTLS; 465 = SSL) und SMTP_FROM (Default = SMTP_USER).

  send-mail.py --to a@b.de --subject "Betreff" --body "Text"
  send-mail.py --to a@b.de --subject "Report" --body-file mail.txt --attach report.pdf
"""
import sys, os, ssl, smtplib
from email.message import EmailMessage


def die(msg):
    sys.stderr.write("send-mail.py: " + msg + "\n")
    sys.exit(1)


def env(name, default=None, required=False):
    v = os.environ.get(name, "").strip()
    if not v:
        if required:
            die(f"{name} fehlt (in .env setzen)")
        return default
    return v


def arg(flag, required=False, default=None):
    a = sys.argv
    if flag in a:
        i = a.index(flag)
        if i + 1 >= len(a):
            die(f"{flag} braucht einen Wert")
        return a[i + 1]
    if required:
        die(f"{flag} fehlt")
    return default


def main():
    host = env("SMTP_HOST", required=True)
    user = env("SMTP_USER", required=True)
    pw = env("SMTP_PASS", required=True)
    port = int(env("SMTP_PORT", "587"))
    sender = env("SMTP_FROM", user)

    to = arg("--to", required=True)
    subject = arg("--subject", required=True)
    body = arg("--body")
    body_file = arg("--body-file")
    attach = arg("--attach")
    if body_file:
        with open(body_file, encoding="utf-8") as f:
            body = f.read()
    if body is None:
        die("--body oder --body-file angeben")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attach:
        if not os.path.isfile(attach):
            die(f"Anhang nicht gefunden: {attach}")
        import mimetypes
        ctype, _ = mimetypes.guess_type(attach)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        with open(attach, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(attach))

    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
                s.login(user, pw); s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ctx); s.login(user, pw); s.send_message(msg)
    except Exception as e:
        die(f"Versand fehlgeschlagen ({type(e).__name__}): {e}")
    print(f"Mail an {to} gesendet.")


if __name__ == "__main__":
    main()
