import {
    useEffect,
    useId,
    useLayoutEffect,
    useReducer,
    useRef,
    useState,
    type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { CLOSED, TIP_NAVIGATION_EVENTS, tipReducer } from "./tipState.ts";

const MARGIN = 12;

/** A small ⓘ button whose explanation appears on hover, keyboard focus or tap.
 *  Use it for "how this is calculated" detail; anything that changes how a
 *  number must be read stays visible as a short chip next to it. The bubble is
 *  rendered in a fixed layer so no clipping container can hide it. */
export function InfoTip({
    children,
    label = "說明",
}: {
    children: ReactNode;
    /** Accessible name of the button, e.g. "怎麼算". */
    label?: string;
}) {
    const id = useId();
    const [{ open }, dispatch] = useReducer(tipReducer, CLOSED);
    const [place, setPlace] = useState<{ left: number; top: number } | null>(
        null,
    );
    const button = useRef<HTMLButtonElement>(null);
    const bubble = useRef<HTMLSpanElement>(null);
    useEffect(() => {
        if (!open) return;
        const outside = (event: PointerEvent) => {
            const target = event.target as Node;
            if (
                !button.current?.contains(target) &&
                !bubble.current?.contains(target)
            )
                dispatch("outside");
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === "Escape") dispatch("escape");
        };
        // The bubble is fixed; scrolling would detach it. Leaving the page
        // closes it too, even if the page stays mounted while hidden.
        const away = () => dispatch("navigate");
        document.addEventListener("pointerdown", outside);
        document.addEventListener("keydown", escape);
        window.addEventListener("scroll", away, { passive: true });
        for (const name of TIP_NAVIGATION_EVENTS)
            window.addEventListener(name, away);
        return () => {
            document.removeEventListener("pointerdown", outside);
            document.removeEventListener("keydown", escape);
            window.removeEventListener("scroll", away);
            for (const name of TIP_NAVIGATION_EVENTS)
                window.removeEventListener(name, away);
        };
    }, [open]);
    useLayoutEffect(() => {
        if (!open) return setPlace(null);
        if (!button.current || !bubble.current) return;
        const anchor = button.current.getBoundingClientRect();
        const size = bubble.current.getBoundingClientRect();
        const centered = anchor.left + anchor.width / 2 - size.width / 2;
        const left = Math.min(
            Math.max(MARGIN, centered),
            innerWidth - MARGIN - size.width,
        );
        const below = anchor.bottom + 8;
        const top =
            below + size.height > innerHeight - MARGIN
                ? Math.max(MARGIN, anchor.top - 8 - size.height)
                : below;
        setPlace({ left, top });
    }, [open]);
    const host =
        button.current?.closest<HTMLElement>(".studio") ?? document.body;
    return (
        <span
            className="u-tip"
            onMouseEnter={() => dispatch("enter")}
            onMouseLeave={() => dispatch("leave")}
        >
            <button
                ref={button}
                type="button"
                className="u-tip-button"
                aria-label={label}
                aria-expanded={open}
                aria-describedby={open ? id : undefined}
                onFocus={() => dispatch("focus")}
                onBlur={() => dispatch("blur")}
                onClick={(event) => {
                    // Tips may sit inside clickable rows; keep the tap here.
                    event.stopPropagation();
                    dispatch("toggle");
                }}
            >
                i
            </button>
            {open &&
                createPortal(
                    <span
                        ref={bubble}
                        id={id}
                        role="tooltip"
                        className="u-tip-bubble"
                        style={
                            place
                                ? { left: place.left, top: place.top }
                                : { left: -9999, top: 0, visibility: "hidden" }
                        }
                        onMouseEnter={() => dispatch("enter")}
                        onMouseLeave={() => dispatch("leave")}
                    >
                        {children}
                    </span>,
                    host,
                )}
        </span>
    );
}

/** A short, always-visible reading caveat ("事後回看") with its full
 *  sentence available in a tip. */
export function CaveatChip({
    children,
    detail,
}: {
    children: ReactNode;
    detail?: ReactNode;
}) {
    return (
        <span className="u-caveat">
            {children}
            {detail && (
                <InfoTip label={`${String(children)}的說明`}>{detail}</InfoTip>
            )}
        </span>
    );
}
