import getpass
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage


DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_USER = "msghoush@gmail.com"
DEFAULT_SMTP_FROM = "msghoush@gmail.com"
DEFAULT_ADMIN_EMAIL = "msghoush@gmail.com"


def _env_value(name: str, default: str = "") -> str:
    return str(os.environ.get(name) or default).strip()


def _get_password() -> str:
    password = str(os.environ.get("SMTP_PASS") or "").strip()
    if password:
        return password
    return getpass.getpass("Gmail App Password: ").strip()


def main():
    smtp_host = _env_value("SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(_env_value("SMTP_PORT", str(DEFAULT_SMTP_PORT)))
    smtp_user = _env_value("SMTP_USER", DEFAULT_SMTP_USER)
    smtp_from = _env_value("SMTP_FROM", DEFAULT_SMTP_FROM)
    admin_email = _env_value("TIS_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL)
    smtp_pass = _get_password()

    print("Gmail SMTP diagnostic")
    print(f"host={smtp_host} port={smtp_port}")
    print(f"user={smtp_user} from={smtp_from} to={admin_email}")
    print(f"pass={'SET' if smtp_pass else 'MISSING'}")

    if not smtp_pass:
        raise SystemExit("No SMTP password provided.")

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = admin_email
    msg["Subject"] = "TIS Gmail SMTP diagnostic"
    msg.set_content(
        "This is a TIS Gmail SMTP diagnostic sent at "
        f"{datetime.now().isoformat(timespec='seconds')}."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            code, _ = server.ehlo()
            print(f"ehlo_before_tls={code}")
            code, _ = server.starttls(context=ssl.create_default_context())
            print(f"starttls={code}")
            code, _ = server.ehlo()
            print(f"ehlo_after_tls={code}")
            code, _ = server.login(smtp_user, smtp_pass)
            print(f"login={code}")
            refused = server.send_message(msg)
            print(f"send_refused={refused}")
        print("Gmail SMTP diagnostic succeeded.")
    except Exception as exc:
        print(f"Gmail SMTP diagnostic failed: {type(exc).__name__}: {exc!r}")
        raise


if __name__ == "__main__":
    main()
