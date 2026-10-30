/** Preview tracks both surfaces; pinning survives pointer and focus departures. */
export type SourceState = {
    hovered: boolean;
    focused: boolean;
    pinned: boolean;
    dismissed: boolean;
};
export type SourceEvent =
    | "enter"
    | "leave"
    | "focus"
    | "blur"
    | "toggle"
    | "escape"
    | "outside"
    | "navigate";
export const SOURCE_CLOSED: SourceState = {
    hovered: false,
    focused: false,
    pinned: false,
    dismissed: false,
};
export const sourceOpen = (state: SourceState) =>
    !state.dismissed && (state.hovered || state.focused || state.pinned);

export function sourceReducer(
    state: SourceState,
    event: SourceEvent,
): SourceState {
    switch (event) {
        case "enter":
            return { ...state, hovered: true, dismissed: false };
        case "leave":
            return { ...state, hovered: false };
        case "focus":
            return { ...state, focused: true };
        case "blur":
            return { ...state, focused: false, dismissed: false };
        case "toggle":
            return state.pinned
                ? { ...SOURCE_CLOSED, dismissed: true }
                : { ...state, pinned: true, dismissed: false };
        case "escape":
            return { ...SOURCE_CLOSED, dismissed: true };
        case "outside":
        case "navigate":
            return SOURCE_CLOSED;
    }
}

export function sourcePanelPosition(
    anchor: { left: number; bottom: number; top: number },
    size: { width: number; height: number },
    viewport: { width: number; height: number },
) {
    return {
        left: Math.max(
            12,
            Math.min(anchor.left, viewport.width - size.width - 12),
        ),
        top:
            anchor.bottom + 8 + size.height <= viewport.height - 12
                ? anchor.bottom + 8
                : Math.max(12, anchor.top - size.height - 8),
    };
}

/** Small DOM-order bridge for a portal; excludes controls unavailable to Tab. */
export function sourceTabStops(
    root: ParentNode,
    excludePanels = false,
): HTMLElement[] {
    return Array.from(
        root.querySelectorAll<HTMLElement>(
            "a[href], area[href], button, input, select, textarea, iframe, object, embed, summary, audio[controls], video[controls], [contenteditable], [tabindex]",
        ),
    )
        .filter(
            (element) =>
                element.tabIndex >= 0 &&
                !element.matches(":disabled") &&
                !element.closest("[hidden], [inert]") &&
                (!excludePanels || !element.closest(".u-source-panel")) &&
                element.getClientRects().length > 0 &&
                element.ownerDocument.defaultView?.getComputedStyle(element)
                    .visibility !== "hidden",
        )
        .sort((a, b) => (a.tabIndex || Infinity) - (b.tabIndex || Infinity));
}

export function sourceNextTabStop(trigger: HTMLElement): HTMLElement | null {
    const controls = sourceTabStops(trigger.ownerDocument, true);
    const index = controls.indexOf(trigger);
    return index >= 0 ? (controls[index + 1] ?? null) : null;
}

export function sourceRestoreFocus(
    panel: HTMLElement | null,
    trigger: HTMLElement | null,
): boolean {
    if (
        !panel ||
        !trigger ||
        !panel.contains(panel.ownerDocument.activeElement)
    )
        return false;
    trigger.focus({ preventScroll: true });
    return true;
}
