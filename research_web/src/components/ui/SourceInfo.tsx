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
import { TIP_NAVIGATION_EVENTS } from "./tipState.ts";
import {
    SOURCE_CLOSED,
    sourceHandleScroll,
    sourceNextTabStop,
    sourceOpen,
    sourcePanelPosition,
    sourceReducer,
    sourceRestoreFocus,
    sourceReturnFromClose,
    sourceTabStops,
} from "./sourceInfoState.ts";

/** Interactive provenance preview; tapping pins the same readable content. */
export function SourceInfo({
    children,
    label = "資料來源",
}: {
    children: ReactNode;
    label?: string;
}) {
    const id = useId();
    const [state, dispatch] = useReducer(sourceReducer, SOURCE_CLOSED);
    const open = sourceOpen(state);
    const trigger = useRef<HTMLButtonElement>(null);
    const panel = useRef<HTMLDivElement>(null);
    const leaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const focusOnCommit = useRef(false);
    const [place, setPlace] = useState<{ left: number; top: number } | null>(
        null,
    );
    const contains = (target: EventTarget | null) =>
        target instanceof Node &&
        Boolean(
            trigger.current?.contains(target) ||
            panel.current?.contains(target),
        );
    const cancelLeave = () => {
        if (leaveTimer.current !== null) clearTimeout(leaveTimer.current);
        leaveTimer.current = null;
    };
    const enter = (pointerType: string) => {
        if (pointerType !== "mouse") return;
        cancelLeave();
        dispatch("enter");
    };
    const leave = (pointerType: string) => {
        if (pointerType !== "mouse") return;
        cancelLeave();
        // Bridge the small visual gap between the trigger and its portal.
        leaveTimer.current = setTimeout(() => dispatch("leave"), 150);
    };
    const reposition = () => {
        if (trigger.current && panel.current)
            setPlace(
                sourcePanelPosition(
                    trigger.current.getBoundingClientRect(),
                    panel.current.getBoundingClientRect(),
                    { width: innerWidth, height: innerHeight },
                ),
            );
    };
    useEffect(() => () => cancelLeave(), []);
    useEffect(() => {
        if (!open) return;
        const outside = (event: PointerEvent) => {
            if (!contains(event.target)) dispatch("outside");
        };
        const escape = (event: KeyboardEvent) => {
            if (event.key !== "Escape") return;
            dispatch("escape");
            if (sourceRestoreFocus(panel.current, trigger.current))
                event.preventDefault();
        };
        const away = () => dispatch("navigate");
        const scroll = (event: Event) => {
            sourceHandleScroll(
                trigger.current,
                panel.current,
                event.target instanceof Node ? event.target : null,
                reposition,
                away,
            );
        };
        document.addEventListener("pointerdown", outside);
        document.addEventListener("keydown", escape);
        window.addEventListener("scroll", scroll, true);
        window.addEventListener("resize", away);
        for (const name of TIP_NAVIGATION_EVENTS)
            window.addEventListener(name, away);
        return () => {
            document.removeEventListener("pointerdown", outside);
            document.removeEventListener("keydown", escape);
            window.removeEventListener("scroll", scroll, true);
            window.removeEventListener("resize", away);
            for (const name of TIP_NAVIGATION_EVENTS)
                window.removeEventListener(name, away);
        };
    }, [open]);
    useLayoutEffect(() => {
        if (!open) return setPlace(null);
        reposition();
    }, [open, children]);
    useLayoutEffect(() => {
        if (open && state.pinned && focusOnCommit.current) {
            focusOnCommit.current = false;
            panel.current
                ?.querySelector<HTMLButtonElement>(".u-source-close")
                ?.focus({ preventScroll: true });
        }
    }, [open, state.pinned]);
    return (
        <span className="u-source">
            <button
                ref={trigger}
                id={`${id}-trigger`}
                className="u-source-trigger"
                type="button"
                aria-expanded={open}
                aria-controls={open ? id : undefined}
                onPointerEnter={(event) => enter(event.pointerType)}
                onPointerLeave={(event) => leave(event.pointerType)}
                onFocus={() => dispatch("focus")}
                onBlur={(event) => {
                    if (!contains(event.relatedTarget)) dispatch("blur");
                }}
                onKeyDown={(event) => {
                    if (
                        event.key === "Tab" &&
                        !event.shiftKey &&
                        open &&
                        panel.current
                    ) {
                        const first = sourceTabStops(panel.current)[0];
                        if (first) {
                            event.preventDefault();
                            first.focus();
                        }
                    }
                }}
                onClick={(event) => {
                    event.stopPropagation();
                    cancelLeave();
                    focusOnCommit.current = event.detail === 0 && !state.pinned;
                    dispatch("toggle");
                }}
            >
                <span aria-hidden="true" className="u-source-icon">
                    i
                </span>
                {label}
            </button>
            {open &&
                createPortal(
                    <div
                        ref={panel}
                        id={id}
                        role="region"
                        aria-labelledby={`${id}-trigger`}
                        tabIndex={-1}
                        className="u-source-panel"
                        style={
                            place
                                ? place
                                : { left: -9999, top: 0, visibility: "hidden" }
                        }
                        onPointerEnter={(event) => enter(event.pointerType)}
                        onPointerLeave={(event) => leave(event.pointerType)}
                        onFocus={() => dispatch("focus")}
                        onBlur={(event) => {
                            if (!contains(event.relatedTarget))
                                dispatch("blur");
                        }}
                        onKeyDown={(event) => {
                            if (event.key !== "Tab" || !panel.current) return;
                            const controls = sourceTabStops(panel.current);
                            if (
                                event.shiftKey &&
                                event.target === controls[0]
                            ) {
                                event.preventDefault();
                                trigger.current?.focus({ preventScroll: true });
                            } else if (
                                !event.shiftKey &&
                                event.target === controls.at(-1)
                            ) {
                                event.preventDefault();
                                const next =
                                    trigger.current &&
                                    sourceNextTabStop(trigger.current);
                                dispatch("escape");
                                (next ?? trigger.current)?.focus({
                                    preventScroll: true,
                                });
                            }
                        }}
                    >
                        <div className="u-source-panel-toolbar">
                            <button
                                type="button"
                                className="u-source-close"
                                aria-label={`關閉${label}`}
                                onKeyDown={(event) =>
                                    sourceReturnFromClose(
                                        event,
                                        trigger.current,
                                    )
                                }
                                onClick={() => {
                                    dispatch("escape");
                                    trigger.current?.focus({
                                        preventScroll: true,
                                    });
                                }}
                            >
                                關閉 ×
                            </button>
                        </div>
                        {children}
                    </div>,
                    trigger.current?.closest<HTMLElement>(".studio") ??
                        document.body,
                )}
        </span>
    );
}
