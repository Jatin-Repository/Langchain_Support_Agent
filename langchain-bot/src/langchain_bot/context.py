from dataclasses import dataclass


@dataclass
class SessionContext:
    user_email: str
    conversation_id: str
    role: str = "customer"