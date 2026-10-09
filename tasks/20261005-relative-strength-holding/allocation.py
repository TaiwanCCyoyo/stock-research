"""Modeled half allocation before the retained provider generates termination."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import replace
from types import FunctionType
from typing import Any, cast

from research_core.auction import RoutedOrder
from research_core.chronology import ExecutionProvider, ExecutionWindow
from research_core.decision import ExecutionAccountSnapshot

LOGGER = logging.getLogger(__name__)
MODEL_ID = "h05-half-allocation-minimum-exit-unit-v1"
BASIS = "modeled: half requested quantity rounded down to venue unit; minimum one exit unit; capped by native allocation; not observed queue"


def half_allocation_factory(
    native_resumption_factory: Callable[[], ExecutionProvider],
    *,
    native_module: Any,
    modeled_module: Any,
    audit: list[dict[str, Any]],
) -> Callable[[], ExecutionProvider]:
    """Adapt only the verified native quote closure, after resumption correction.

    This seam constructs quotes with no explicit broker reports. Arbitrary
    ExecutionEvidence and terminal reports are never edited or reinterpreted.
    """

    def factory() -> ExecutionProvider:
        native = native_resumption_factory()
        if not isinstance(native, FunctionType) or set(native.__code__.co_freevars) != {"policy", "quote_for"} or native.__globals__ is not vars(native_module):
            raise ValueError("half allocation requires the verified native provider closure")
        cells = dict(zip(native.__code__.co_freevars, native.__closure__ or (), strict=True))
        original_policy = cells["policy"].cell_contents
        quote_for = cells["quote_for"].cell_contents
        if not isinstance(original_policy, modeled_module.EndOfWindowTermination) or not callable(quote_for):
            raise ValueError("half allocation native policy/quote closure is incompatible")
        policy = modeled_module.EndOfWindowTermination(
            f"{original_policy.model_id}|{MODEL_ID}",
            f"{original_policy.basis}; {BASIS}",
            original_policy.max_positions,
        )
        LOGGER.debug("Constructed half allocation provider using %s", policy.model_id)

        def provide(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Sequence[RoutedOrder]) -> Any:
            if not routes:
                raise ValueError("half allocation requires nonempty routed evidence")
            if any(route.batch.venue not in {"regular_open", "afterhours_odd"} for route in routes):
                raise ValueError("half allocation supports regular_open and afterhours_odd only")
            if len({route.order.code for route in routes}) != len(routes):
                raise ValueError("native quote seam requires one routed order per code")
            day = window.sessions[0].batch.auction_at.date()
            quotes = {}
            for route in routes:
                quote = quote_for(day, route)
                if not isinstance(quote, native_module.SessionQuote):
                    raise ValueError("native quote closure returned an incompatible quote")
                quote = cast(Any, quote)
                if quote.status == "TRADED":
                    if not isinstance(quote.capacity, native_module.CapacityPolicy):
                        raise ValueError("native quote capacity is incompatible")
                    requested = route.order.qty
                    target = max(1000, (requested // 2 // 1000) * 1000) if route.batch.venue == "regular_open" else max(1, requested // 2)
                    native_allocation = quote.capacity.shares
                    allocation = min(native_allocation, target)
                    quote = replace(quote, capacity=native_module.CapacityPolicy(allocation, f"{quote.capacity.basis}; {BASIS}"))
                    audit.append({
                        "model_id": MODEL_ID,
                        "date": day.isoformat(),
                        "order_id": route.order.order_id,
                        "code": route.order.code,
                        "venue": route.batch.venue,
                        "requested_qty": requested,
                        "native_allocation": native_allocation,
                        "modeled_allocation": allocation,
                    })
                quotes[route.order.code] = quote
            session = native_module.SessionExecutionEvidence(f"modeled-open-{day.isoformat()}|{MODEL_ID}", quotes)
            return modeled_module.build_modeled_execution_provider({day: session}, policy)(window, snapshot, routes)

        return provide

    return factory
