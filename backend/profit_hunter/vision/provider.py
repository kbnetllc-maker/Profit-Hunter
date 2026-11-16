"""The provider-independent interface. A provider turns images and text into
an ``IdentificationOutput``; it knows nothing about budgets, bids or the database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .schema import IdentificationOutput

OK, REFUSED, TRUNCATED, INVALID, EMPTY = "OK", "REFUSED", "TRUNCATED", "INVALID", "EMPTY"


@dataclass(frozen=True)
class PreparedImage:
    data: bytes  # JPEG, metadata removed, cropped and scaled
    width: int
    height: int
    sha256: str
    role: str


@dataclass(frozen=True)
class VisionRequest:
    model: str
    reasoning_effort: str
    max_output_tokens: int
    instructions: str
    user_text: str
    images: tuple[PreparedImage, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int  # includes reasoning tokens
    reasoning_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    """A response the provider answered (and billed). Only OK carries an output."""
    outcome: str
    output: IdentificationOutput | None
    usage: Usage | None
    model: str | None  # the model the provider says answered
    detail: str = ""


class ProviderError(Exception):
    """The call failed. ``may_have_billed`` is True when we cannot know whether
    the provider processed the request (timeout, dropped connection)."""

    def __init__(self, message: str, *, transient: bool, may_have_billed: bool):
        super().__init__(message)
        self.transient = transient
        self.may_have_billed = may_have_billed


class VisionProvider(Protocol):
    name: str
    bills: bool  # False for the mock: nothing is ever charged

    def identify(self, request: VisionRequest) -> ProviderResult: ...
