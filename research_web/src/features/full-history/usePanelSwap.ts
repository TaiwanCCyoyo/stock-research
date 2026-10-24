import { useEffect, useReducer, useRef } from "react";
import {
    initialPanel,
    panelWake,
    stepPanel,
    type PanelInput,
    type PanelPhase,
    type PanelSnap,
    type PanelState,
} from "./panelPolicy.ts";

type Step<T extends PanelSnap> = {
    input: PanelInput<T>;
    now: number;
};

/** Runs the side panel's policy (panelPolicy.ts): re-evaluates when the inputs
 *  change and when the policy asks to be woken, and hands back the snapshot
 *  the cards must show. */
export function usePanelSwap<T extends PanelSnap>(
    live: T | null,
    playing: boolean,
    scrubbing: boolean,
    reduced: boolean,
): { phase: PanelPhase; shown: T | null; swappedAt: number } {
    const [state, dispatch] = useReducer(
        (current: PanelState<T>, step: Step<T>) =>
            stepPanel(current, step.input, step.now),
        undefined,
        () => initialPanel<T>(),
    );
    const input = useRef<PanelInput<T>>({ live, playing, scrubbing, reduced });
    input.current = { live, playing, scrubbing, reduced };
    useEffect(() => {
        dispatch({ input: input.current, now: performance.now() });
    }, [live, playing, scrubbing, reduced]);
    useEffect(() => {
        const wait = panelWake(state, input.current, performance.now());
        if (wait === null) return;
        const timer = window.setTimeout(
            () => dispatch({ input: input.current, now: performance.now() }),
            wait + 1,
        );
        return () => window.clearTimeout(timer);
    }, [state, live, playing, scrubbing, reduced]);
    return {
        phase: state.phase,
        shown: state.shown,
        swappedAt: state.swappedAt,
    };
}
