"""MongoDB document models for users, conversations, and chat history."""
from datetime import datetime
import re
from typing import Optional, Tuple

import bcrypt
from beanie import Document, Indexed
from pydantic import Field


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """Require min 8 chars, at least 1 upper, 1 lower, 1 digit, 1 special."""
    if len(password) < 8:
        return False, "Password must be at least 8 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number."
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?]", password):
        return False, "Password must contain at least one special character."
    return True, None


class User(Document):
    username: Indexed(str, unique=True)
    password_hash: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode("utf-8"), self.password_hash.encode("utf-8")
        )

    def to_public_dict(self) -> dict:
        return {
            "id": str(self.id),
            "username": self.username,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Conversation(Document):
    user_id: Indexed(str)
    title: str = "New chat"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "conversations"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Document):
    user_id: Indexed(str)
    conversation_id: Optional[Indexed(str)] = None
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "chat_messages"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
