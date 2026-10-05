from pathlib import Path

from langchain_google_community.gmail.send_message import GmailSendMessage
from langchain_google_community.gmail.utils import (
    build_resource_service,
    get_gmail_credentials,
)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CREDENTIALS_FILE = PROJECT_ROOT / "credentials.json"
TOKEN_FILE = PROJECT_ROOT / "token.pickle"

GMAIL_SCOPE = [
    "https://www.googleapis.com/auth/gmail.send"
]


# ---------------------------------------------------------
# Singleton
# ---------------------------------------------------------

_gmail_service = None
_gmail_toolkit = None
_gmail_initialized = False
_gmail_error = None


# ---------------------------------------------------------
# Gmail service
# ---------------------------------------------------------

def get_gmail_service():
    """
    Authenticate with Gmail using OAuth and return
    the Gmail API resource.
    """

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found: {CREDENTIALS_FILE}"
        )

    credentials = get_gmail_credentials(
        token_file=str(TOKEN_FILE),
        scopes=GMAIL_SCOPE,
        client_sercret_file=str(CREDENTIALS_FILE),
    )

    return build_resource_service(
        credentials=credentials
    )


# ---------------------------------------------------------
# Initialize Gmail
# ---------------------------------------------------------

def initialize_gmail() -> bool:
    """
    Initialize Gmail once.

    Returns:
        True  -> Gmail successfully initialized
        False -> Gmail unavailable/not configured
    """

    global _gmail_service
    global _gmail_toolkit
    global _gmail_initialized
    global _gmail_error

    if _gmail_initialized:
        return _gmail_service is not None

    _gmail_initialized = True

    try:

        _gmail_service = get_gmail_service()

        _gmail_toolkit = GmailSendMessage(api_resource=_gmail_service)

        _gmail_error = None
        print("[GMAIL] Gmail initialized successfully")

        return True

    except Exception as exc:
        _gmail_error = str(exc)

        _gmail_service = None
        _gmail_toolkit = None

        print(
            f"[GMAIL] Gmail not available: {exc}"
        )

        return False


# ---------------------------------------------------------
# Gmail tools
# ---------------------------------------------------------

def get_gmail_tools():
    """
    Return GmailToolkit tools if Gmail is available.
    """

    if not initialize_gmail():
        return []

    return [_gmail_toolkit]


# ---------------------------------------------------------
# Gmail availability
# ---------------------------------------------------------

def is_gmail_available() -> bool:
    """
    Return whether Gmail is available.
    """

    return _gmail_service is not None


def get_gmail_error():
    """Return the last setup/send failure for the administrator."""
    return _gmail_error


def send_action_notification(user_email, subject, body):
    """Send one post-approval email to the database-verified customer.

    Sending is explicit application code, never an LLM tool choice. Failure
    is reported independently and does not undo a committed business action.
    """
    import base64
    from email.message import EmailMessage
    global _gmail_error
    if not initialize_gmail():
        return {"sent": False, "message_id": None,
                "error": _gmail_error or "Gmail is not configured."}
    try:
        message = EmailMessage()
        message["To"] = user_email
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = _gmail_service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        message_id = response.get("id")
        if not message_id:
            raise RuntimeError("Gmail did not return a message ID.")
        _gmail_error = None
        print(f"[GMAIL] Approval notification accepted: message_id={message_id}")
        return {"sent": True, "message_id": message_id, "error": None}
    except Exception as exc:
        _gmail_error = f"{type(exc).__name__}: {exc}"
        print(f"[GMAIL] Approval notification failed: {_gmail_error}")
        return {"sent": False, "message_id": None, "error": _gmail_error}


def notification_status(result):
    if result["sent"]:
        return f"Email status: SENT (Gmail message ID: {result['message_id']})."
    return f"Email status: NOT_SENT. {result['error']}"
