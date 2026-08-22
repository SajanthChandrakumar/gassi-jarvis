"""
Gassi-Jarvis — API Contract Models (Pydantic v2)

Defines the strict JSON schemas for all communication between
the frontend (Layer 1) and the FastAPI gateway (Layer 2).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MessagePayload(BaseModel):
    """
    The inner payload of every chat message.

    Attributes:
        type: The input modality — currently 'text', future: 'audio'.
        content: The raw user input string.
    """

    type: Literal["text", "audio"] = Field(
        ...,
        description="Input type: 'text' or 'audio'.",
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


class ChatResponse(BaseModel):
    """
    Top-level response schema for the /api/chat endpoint.

    Attributes:
        status: Always 'success' for 2xx responses; errors use HTTP status codes.
        jarvis_response: Jarvis' text answer.
        audio_base64: Base64-encoded MP3 of the TTS rendering (may be empty).
        action_taken: Machine-readable description of what the backend did.
        research_payload: Canonical Phase-7 output for read-only research actions.
    """

    status: Literal["success"] = "success"
    jarvis_response: str
    audio_base64: str = ""
    action_taken: str = "none"
    research_payload: dict[str, Any] | None = None


class ResearchRunRequest(BaseModel):
    """Validated, LLM-free request from the Command Center workflow forms."""

    mode: Literal["asset", "compare", "history", "relationship"]
    asset: str = Field(..., min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-]+$")
    benchmark: str | None = Field(None, min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-]+$")
    timeframe: Literal["6m", "1y", "2y", "5y", "all"] = "1y"
    analysis: Literal["correlation", "beta"] = "correlation"

    @model_validator(mode="after")
    def require_second_asset(self):
        if self.mode in {"compare", "relationship"} and not self.benchmark:
            raise ValueError("benchmark is required for comparison and relationship research")
        return self


class RecentMemoriesResponse(BaseModel):
    """
    Response schema for GET /api/memories/recent.

    A lightweight, LLM-free endpoint for external dashboards (e.g. Homepage's
    Custom API widget) to display recently saved facts without triggering a
    Gemini call.

    Attributes:
        memories: Up to n most recently saved facts, newest first. Each entry
                   has 'text' (the saved fact) and 'timestamp' (ISO-8601).
    """

    memories: list[dict] = []
