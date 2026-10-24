/** What a throttled side panel shows during playback. The frame and the
 *  holdings comparisons are captured together, so a panel never pairs one
 *  date's returns with another date's holdings. */
export interface PanelSnapshot<F, C> {
    frame: F;
    comparisons: C;
    at: number;
}

export const PANEL_REFRESH = 2000;

/** Paused: always the live pair. Playing: the live pair at most once per
 *  `refresh` ms, otherwise the previous snapshot unchanged. */
export function nextPanelSnapshot<F, C>(
    previous: PanelSnapshot<F, C> | null,
    live: { frame: F; comparisons: C },
    playing: boolean,
    now: number,
    refresh = PANEL_REFRESH,
): PanelSnapshot<F, C> {
    if (!playing || !previous || now - previous.at >= refresh)
        return { frame: live.frame, comparisons: live.comparisons, at: now };
    return previous;
}
