from pathlib import Path

from langchain_google_community import GmailToolkit
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

    if _gmail_initialized:
        return _gmail_service is not None

    _gmail_initialized = True

    try:

        _gmail_service = get_gmail_service()

        _gmail_toolkit = GmailToolkit(
            api_resource=_gmail_service
        )

        print("[GMAIL] Gmail initialized successfully")

        return True

    except Exception as exc:

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

    return _gmail_toolkit.get_tools()


# ---------------------------------------------------------
# Gmail availability
# ---------------------------------------------------------

def is_gmail_available() -> bool:
    """
    Return whether Gmail is available.
    """

    return _gmail_service is not None