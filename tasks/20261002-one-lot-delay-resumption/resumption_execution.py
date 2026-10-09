"""Named resumed-session quote correction without mutating the preserved provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import FunctionType
from typing import Any, Callable


@dataclass(frozen=True)
class ResumptionCase:
    code: str
    reference_day: date
    halt_day: date
    resumed_day: date
    reference_close_cents: int
    halt_source_id: str
    reference_source_id: str
    resumed_source_id: str
    halt_price_source_id: str

    def __post_init__(self) -> None:
        if not (self.reference_day < self.halt_day < self.resumed_day):
            raise ValueError("resumption case dates must be strictly ordered")
        if isinstance(self.reference_close_cents, bool) or not isinstance(self.reference_close_cents, int) or self.reference_close_cents <= 0:
            raise ValueError("reference_close_cents must be a positive integer")
        if any(
            not isinstance(value, str) or not value
            for value in (self.code, self.halt_source_id, self.reference_source_id, self.resumed_source_id, self.halt_price_source_id)
        ):
            raise ValueError("resumption case identities must be nonempty strings")


def _cell(value: Any) -> Any:
    def capture() -> Any:
        return value

    closure = capture.__closure__
    assert closure is not None
    return closure[0]


def extend_factory(
    native_factory: Callable[[], Any], cases: tuple[ResumptionCase, ...], *, native_module: Any, audit: list[dict[str, Any]]
) -> Callable[[], Any]:
    by_key = {(case.resumed_day, case.code): case for case in cases}
    if len(by_key) != len(cases):
        raise ValueError("resumption cases must have unique resumed day/code keys")

    def factory() -> Any:
        provider = native_factory()
        if set(provider.__code__.co_freevars) != {"policy", "quote_for"}:
            raise ValueError("native provider closure is incompatible")
        provider_cells = dict(zip(provider.__code__.co_freevars, provider.__closure__ or (), strict=True))
        quote_for = provider_cells["quote_for"].cell_contents
        expected = {"confirmed_halts", "corporate_keys", "event_limits", "incomplete", "previous_session", "raw_by_key", "verified_regular_no_trades"}
        if set(quote_for.__code__.co_freevars) != expected:
            raise ValueError("native quote closure is incompatible")
        state = {name: cell.cell_contents for name, cell in zip(quote_for.__code__.co_freevars, quote_for.__closure__ or (), strict=True)}

        def resumed_quote(day: date, route: Any) -> Any:
            case = by_key.get((day, route.order.code))
            if case is None:
                return quote_for(day, route)
            raw, previous, halts = state["raw_by_key"], state["previous_session"], state["confirmed_halts"]
            row, halt, reference = raw.get((day, case.code)), raw.get((case.halt_day, case.code)), raw.get((case.reference_day, case.code))
            if route.batch.exchange != "TWSE" or previous.get(day) != case.halt_day or previous.get(case.halt_day) != case.reference_day:
                raise ValueError("named resumption session linkage or exchange contradicts case")
            if halts is None or halts.get((case.halt_day, case.code)) != case.halt_source_id:
                raise ValueError("named resumption halt identity contradicts case")
            if not all(isinstance(item, Mapping) for item in (row, halt, reference)):
                raise ValueError("named resumption rows are unavailable")
            if (
                reference.get("source_id") != case.reference_source_id
                or halt.get("source_id") != case.halt_price_source_id
                or row.get("source_id") != case.resumed_source_id
            ):
                raise ValueError("named resumption source identity contradicts case")
            if native_module._cents(reference.get("Close")) != case.reference_close_cents:
                raise ValueError("named resumption reference close contradicts case")
            if (
                not native_module._is_missing_normalized_price(halt.get("Open"))
                or not native_module._is_missing_normalized_price(halt.get("Close"))
                or isinstance(halt.get("Volume"), bool)
                or not isinstance(halt.get("Volume"), (int, float))
                or halt["Volume"] != 0
            ):
                raise ValueError("named halt bar is not null-price zero-volume")
            keys = {(case.reference_day, case.code), (case.halt_day, case.code), (day, case.code)}
            if keys & set(state["corporate_keys"]) or (state["event_limits"] is not None and keys & set(state["event_limits"])):
                raise ValueError("named resumption conflicts with corporate/event limits")
            field = "Close" if route.batch.venue == "afterhours_odd" else "Open"
            price = native_module._cents(row.get(field))
            if price is None:
                return quote_for(day, route)
            band = native_module.bounded_band(
                reference_price=Decimal(case.reference_close_cents) / 100,
                band=Fraction(1, 10),
                basis=f"modeled: named resumed reference {case.reference_day.isoformat()}:{case.reference_source_id}; halt:{case.halt_source_id}",
            )
            limits = band.resolve()
            observed = Decimal(price) / 100
            if observed < limits.lower or (limits.upper is not None and observed > limits.upper):
                return state["incomplete"](day, case.code, "open_outside_named_resumption_band", row["source_id"])
            adverse = (route.order.side == "BUY" and observed == limits.upper) or (route.order.side == "SELL" and observed == limits.lower)
            basis = native_module._AFTERHOURS_CAPACITY_BASIS if route.batch.venue == "afterhours_odd" else native_module._CAPACITY_BASIS
            proxy = "modeled:afterhours-regular-close-proxy-v1|" if route.batch.venue == "afterhours_odd" else ""
            source = (
                f"{proxy}modeled:named-resumed-reference:{case.reference_day.isoformat()}:{case.reference_source_id}"
                f"|halt:{case.halt_source_id}|current:{row['source_id']}"
            )
            quote = native_module.SessionQuote("TRADED", price, band, native_module.CapacityPolicy(0 if adverse else route.order.qty, basis), source)
            audit.append({
                "date": day.isoformat(),
                "code": case.code,
                "order_id": route.order.order_id,
                "exchange": route.batch.exchange,
                "venue": route.batch.venue,
                "reference_day": case.reference_day.isoformat(),
                "reference_close_cents": case.reference_close_cents,
                "reference_source_id": case.reference_source_id,
                "halt_source_id": case.halt_source_id,
                "current_source_id": row["source_id"],
                "quote_source_id": source,
                "status": "TRADED",
                "price_cents": price,
            })
            return quote

        quote_cells = tuple(
            _cell(resumed_quote) if name == "quote_for" else cell for name, cell in zip(provider.__code__.co_freevars, provider.__closure__ or (), strict=True)
        )
        return FunctionType(provider.__code__, provider.__globals__, provider.__name__, provider.__defaults__, quote_cells)

    return factory


__all__ = ["ResumptionCase", "extend_factory"]
