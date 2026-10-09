"""Deterministic, stateless signal-omission sampling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Any


class SignalError(ValueError):
    """Raised when a deterministic signal identity or sampler is malformed."""


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SignalError(f"{name} must be a nonempty string")
    return value


def _time(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise SignalError("origin_at must be an aware +08:00 datetime")
    return value


@dataclass(frozen=True)
class SignalIdentity:
    signal_id: str
    code: str
    side: str
    origin_at: datetime

    def __post_init__(self) -> None:
        _text(self.signal_id, "signal_id")
        _text(self.code, "code")
        if self.side not in {"BUY", "SELL"}:
            raise SignalError("side must be BUY or SELL")
        _time(self.origin_at)


@dataclass(frozen=True)
class SignalDraw:
    signal: SignalIdentity
    digest_hex: str
    omitted: bool


@dataclass(frozen=True)
class SignalOmission:
    seed: str
    rate: Fraction

    def __post_init__(self) -> None:
        _text(self.seed, "seed")
        if type(self.rate) is not Fraction or not 0 <= self.rate <= 1:
            raise SignalError("rate must be a Fraction from zero through one")

    def draw(self, signal: SignalIdentity) -> SignalDraw:
        if not isinstance(signal, SignalIdentity):
            raise SignalError("signal must be SignalIdentity")
        payload = json.dumps(
            ["stock-signal-omission.v1", self.seed, signal.signal_id, signal.code, signal.side, signal.origin_at.isoformat()],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(payload).digest()
        value = int.from_bytes(digest, "big")
        omitted = value * self.rate.denominator < self.rate.numerator * (1 << 256)
        return SignalDraw(signal, digest.hex(), omitted)
