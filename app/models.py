"""
Gassi-Jarvis — API Contract Models (Pydantic v2)

Defines the strict JSON schemas for all communication between
the frontend (Layer 1) and the FastAPI gateway (Layer 2).
"""

from datetime import datetime
from pydantic import BaseModel, Field


class MessagePayload(BaseModel):
    """
    The inner payload of every chat message.

    Attributes:
        type: The input modality — currently 'text', future: 'audio'.
        content: The raw user input string.
    """

    type: str = Field(
        ...,
        description="Input type, e.g. 'text' or 'audio'.",
        examples=["text"],
    )
    content: str = Field(
        ...,
        min_length=1,
        description="The user's message content.",
        examples=["Jarvis, öffne Safari für mich."],
    )


class ChatRequest(BaseModel):
    """
    Top-level request schema for the /api/chat endpoint.

    Attributes:
        session_id: Unique identifier for the conversation session.
        timestamp: ISO-8601 timestamp from the client.
        payload: The nested message payload.
    """

    session_id: str = Field(
        ...,
        min_length=1,
        description="Unique session identifier from the client.",
        examples=["voice_walk_01"],
    )
    timestamp: datetime = Field(
        ...,
        description="Client-side timestamp in ISO-8601 format.",
    )
    payload: MessagePayload
