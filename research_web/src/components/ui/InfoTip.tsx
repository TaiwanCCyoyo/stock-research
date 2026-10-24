import {
    useEffect,
    useId,
    useLayoutEffect,
    useRef,
    useState,
    type ReactNode,
} from "react";
import { createPortal } from "react-dom";

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
    const [open, setOpen] = useState(false);
    const [pinned, setPinned] = useState(false);
    const [place, setPlace] = useState<{ left: number; top: number } | null>(
        null,
    );
    const button = useRef<HTMLButtonElement>(null);
    const bubble = useRef<HTMLSpanElement>(null);
    const close = () => {
        setOpen(false);
        setPinned(false);
    };
    useEffect(() => {
        if (!open) return;
        const outside = (event: PointerEvent) => {
            const target = event.target as Node;
            if (
                !button.current?.contains(target) &&
                !bubble.current?.contains(target)
            )
                close();
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key === "Escape") close();
        };
        // The bubble is fixed; scrolling the page would detach it.
        const scroll = () => close();
        document.addEventListener("pointerdown", outside);
        document.addEventListener("keydown", escape);
        window.addEventListener("scroll", scroll, { passive: true });
        return () => {
            document.removeEventListener("pointerdown", outside);
            document.removeEventListener("keydown", escape);
            window.removeEventListener("scroll", scroll);
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
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => !pinned && setOpen(false)}
        >
            <button
                ref={button}
                type="button"
                className="u-tip-button"
                aria-label={label}
                aria-expanded={open}
                aria-describedby={open ? id : undefined}
                onFocus={() => setOpen(true)}
                onBlur={() => !pinned && setOpen(false)}
                onClick={(event) => {
                    // Tips may sit inside clickable rows; keep the tap here.
                    event.stopPropagation();
                    setOpen(!pinned);
                    setPinned(!pinned);
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
                        onMouseEnter={() => setOpen(true)}
                        onMouseLeave={() => !pinned && setOpen(false)}
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
