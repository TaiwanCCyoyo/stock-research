import { HISTORY_SCHEMA, type HistoryFrame } from "./types.ts";

export interface FrameIdentity {
    catalogId: string;
    date: string;
}

const keyOf = ({ catalogId, date }: FrameIdentity) => `${catalogId}:${date}`;

/** Small, session-only LRU. Pending frames are shared by playback and lookahead. */
export class FrameBuffer {
    private readonly frames = new Map<string, HistoryFrame>();
    private readonly pending = new Map<
        string,
        { controller: AbortController; promise: Promise<HistoryFrame> }
    >();
    private readonly load: (
        date: string,
        signal: AbortSignal,
    ) => Promise<HistoryFrame>;
    private readonly capacity: number;

    constructor(
        load: (date: string, signal: AbortSignal) => Promise<HistoryFrame>,
        capacity = 24,
    ) {
        this.load = load;
        this.capacity = capacity;
    }

    peek(identity: FrameIdentity): HistoryFrame | undefined {
        const key = keyOf(identity);
        const frame = this.frames.get(key);
        if (frame) {
            this.frames.delete(key);
            this.frames.set(key, frame);
        }
        return frame;
    }

    read(identity: FrameIdentity): Promise<HistoryFrame> {
        const saved = this.peek(identity);
        if (saved) return Promise.resolve(saved);
        const key = keyOf(identity);
        const pending = this.pending.get(key);
        if (pending) return pending.promise;
        const controller = new AbortController();
        const promise = this.load(identity.date, controller.signal)
            .then((frame) => {
                if (controller.signal.aborted)
                    throw new DOMException("Aborted", "AbortError");
                if (
                    frame.schema !== HISTORY_SCHEMA ||
                    frame.catalogId !== identity.catalogId ||
                    frame.date !== identity.date ||
                    !Array.isArray(frame.rows)
                )
                    throw new Error("資料日期或版本不一致");
                this.frames.set(key, frame);
                while (this.frames.size > this.capacity)
                    this.frames.delete(this.frames.keys().next().value!);
                return frame;
            })
            .finally(() => {
                if (this.pending.get(key)?.controller === controller)
                    this.pending.delete(key);
            });
        this.pending.set(key, { controller, promise });
        return promise;
    }

    /** Keep only current/next playback requests; seek, pause and exit cancel the rest. */
    retain(identities: readonly FrameIdentity[]): void {
        const keep = new Set(identities.map(keyOf));
        for (const [key, pending] of this.pending) {
            if (keep.has(key)) continue;
            this.pending.delete(key);
            pending.controller.abort();
        }
    }
}

/** At most two future frames, including the exact final trading day. */
export function playbackLookahead(
    dates: readonly string[],
    index: number,
    step: number,
    depth = 2,
): string[] {
    const result: string[] = [];
    for (
        let offset = 1;
        offset <= depth && index < dates.length - 1;
        offset++
    ) {
        const next = dates[Math.min(index + step * offset, dates.length - 1)];
        if (next && next !== dates[index] && !result.includes(next))
            result.push(next);
    }
    return result;
}
