"""Deterministic signal-omission contracts without market or clock reads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fractions import Fraction
from typing import Any

import pytest

from research_core.signals import SignalError, SignalIdentity, SignalOmission

TZ = timezone(timedelta(hours=8))


def signal(identity: str = "s") -> SignalIdentity:
    return SignalIdentity(identity, "2330", "BUY", datetime(2026, 1, 2, 8, 55, tzinfo=TZ))


def test_known_vector_and_reordered_calls_are_stable() -> None:
    sampler = SignalOmission("seed", Fraction(1, 10))
    draw = sampler.draw(signal())
    # Public SHA-256 test vector for the synthetic payload, not a credential.
    expected = "48a5234f7a364275f11125e095306657d83874ebba4863bccfc00efb7f64104d"  # pragma: allowlist secret
    assert draw.digest_hex == expected
    assert draw == sampler.draw(signal())
    sampler.draw(signal("unrelated"))
    assert draw == sampler.draw(signal())


def test_rate_edges_and_subset_are_deterministic() -> None:
    items = [signal(str(index)) for index in range(20)]
    assert not any(SignalOmission("x", Fraction(0)).draw(item).omitted for item in items)
    assert all(SignalOmission("x", Fraction(1)).draw(item).omitted for item in items)
    ten_percent = {draw.signal.signal_id for draw in (SignalOmission("x", Fraction(1, 10)).draw(item) for item in items) if draw.omitted}
    twenty_percent = {draw.signal.signal_id for draw in (SignalOmission("x", Fraction(1, 5)).draw(item) for item in items) if draw.omitted}
    assert ten_percent
    assert twenty_percent
    assert ten_percent <= twenty_percent


@pytest.mark.parametrize("rate", [True, 0.1, Fraction(-1, 2), Fraction(2)])
def test_invalid_rates(rate: Any) -> None:
    with pytest.raises(SignalError):
        SignalOmission("x", rate)


@pytest.mark.parametrize(
    "args",
    [
        ("", "A", "BUY", datetime(2026, 1, 1, tzinfo=TZ)),
        ("x", "", "BUY", datetime(2026, 1, 1, tzinfo=TZ)),
        ("x", "A", "HOLD", datetime(2026, 1, 1, tzinfo=TZ)),
        ("x", "A", "BUY", datetime(2026, 1, 1)),
        ("x", "A", "BUY", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_invalid_identity(args: tuple[str, str, str, datetime]) -> None:
    with pytest.raises(SignalError):
        SignalIdentity(*args)


@pytest.mark.parametrize("seed", ["", None])
def test_invalid_seed(seed: Any) -> None:
    with pytest.raises(SignalError):
        SignalOmission(seed, Fraction(1, 10))


def test_draw_rejects_nonidentity() -> None:
    with pytest.raises(SignalError):
        SignalOmission("seed", Fraction(1, 10)).draw("not-a-signal")  # type: ignore[arg-type]
