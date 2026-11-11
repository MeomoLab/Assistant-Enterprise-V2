"""The invitation mailer records messages locally; it never sends real email."""
from datetime import datetime, timezone
from email.message import EmailMessage
import re
from pathlib import Path


def send_email(app, to, subject, body):
    message = EmailMessage()
    message["From"] = app.config["MAIL_FROM"]
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    message.set_content(body)
    if app.config["MAIL_BACKEND"] == "console":
        print(message.as_string())
        return "printed to the console"
    # A later smtp backend would be added here without changing invitation flows.
    folder = Path(app.instance_path) / "outbox"
    folder.mkdir(parents=True, exist_ok=True)
    safe_to = re.sub(r"[^A-Za-z0-9.-]", "_", to)
    filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}-{safe_to}.eml"
    (folder / filename).write_bytes(message.as_bytes())
    print(f"Invitation recorded in {filename}.")
    return filename
