/** Open/pinned state of an ⓘ tip. Hover and focus preview it; a tap or Enter
 *  pins it; Escape, an outside tap and any page navigation close it. Pages may
 *  stay mounted while hidden (the map does), so navigation must close a tip
 *  even when its component is not unmounted. */
export interface TipState {
    open: boolean;
    pinned: boolean;
}

export type TipEvent =
    | "enter"
    | "leave"
    | "focus"
    | "blur"
    | "toggle"
    | "escape"
    | "outside"
    | "navigate";

export const CLOSED: TipState = { open: false, pinned: false };

/** Browser events after which a tip must close. */
export const TIP_NAVIGATION_EVENTS = ["hashchange", "popstate"] as const;

export function tipReducer(state: TipState, event: TipEvent): TipState {
    switch (event) {
        case "enter":
        case "focus":
            return { ...state, open: true };
        case "leave":
        case "blur":
            return state.pinned ? state : CLOSED;
        case "toggle":
            return state.pinned ? CLOSED : { open: true, pinned: true };
        case "escape":
        case "outside":
        case "navigate":
            return CLOSED;
    }
}
