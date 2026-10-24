/** When the user moves through dates faster than the map can follow, the map
 *  pops its bubbles and regathers them once the date settles. Playback steps
 *  never come through here: they call `navigate`, not `seek`. */

/** A new target sooner than this after the last one means the glide to it
 *  would be cut short: the user is still dragging. */
export const SCRUB_GAP = 300;
/** A jump of more than this many trading days is too far to glide across. */
export const SCRUB_JUMP = 40;
/** The date counts as settled this long after the last target. */
export const SCRUB_SETTLE = 220;

export function isFastSeek(input: {
    /** ms since the previous seek (Infinity when there was none). */
    elapsed: number;
    /** Where the user was heading before this seek. */
    from: number;
    to: number;
}): boolean {
    return (
        input.elapsed < SCRUB_GAP ||
        Math.abs(input.to - input.from) > SCRUB_JUMP
    );
}

/** The map stays popped until the date is quiet and its own frame is shown. */
export function scrubStillActive(input: {
    flagged: boolean;
    quiet: boolean;
    frameDate: string | undefined;
    desiredDate: string;
    loading: boolean;
    failed: boolean;
}): boolean {
    if (!input.flagged || input.failed) return false;
    return !(
        input.quiet &&
        !input.loading &&
        input.frameDate !== undefined &&
        input.frameDate === input.desiredDate
    );
}
