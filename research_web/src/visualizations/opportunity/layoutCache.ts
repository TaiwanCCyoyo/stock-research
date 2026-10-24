/** Small least-recently-used cache of packed layouts. A layout depends on the
 *  stocks shown, their groups and weights and the frame shape, but also on the
 *  layout the bubbles came from. Only layouts packed from scratch (nothing
 *  carried over) are therefore stored, so a hit is always the layout a fresh
 *  pack would produce. */
export const LAYOUT_CACHE_SIZE = 64;
/** A busy day holds hundreds of stocks, each with its own outline path, so the
 *  entries are also capped by how many stocks they hold in all. */
export const LAYOUT_CACHE_STOCKS = 12000;

export class LayoutCache<T> {
    private readonly entries = new Map<string, T>();
    private readonly capacity: number;
    private readonly maxWeight: number;
    private readonly weigh: (value: T) => number;
    private weight = 0;

    constructor(
        capacity = LAYOUT_CACHE_SIZE,
        maxWeight = Infinity,
        weigh: (value: T) => number = () => 0,
    ) {
        this.capacity = capacity;
        this.maxWeight = maxWeight;
        this.weigh = weigh;
    }

    get(key: string): T | undefined {
        const value = this.entries.get(key);
        if (value === undefined) return undefined;
        this.entries.delete(key);
        this.entries.set(key, value);
        return value;
    }

    set(key: string, value: T): void {
        this.drop(key);
        this.entries.set(key, value);
        this.weight += this.weigh(value);
        // Always keep the newest entry, even when it alone is over the cap.
        while (
            this.entries.size > 1 &&
            (this.entries.size > this.capacity || this.weight > this.maxWeight)
        )
            this.drop(this.entries.keys().next().value!);
    }

    private drop(key: string): void {
        const value = this.entries.get(key);
        if (value === undefined) return;
        this.weight -= this.weigh(value);
        this.entries.delete(key);
    }

    get size(): number {
        return this.entries.size;
    }

    clear(): void {
        this.entries.clear();
        this.weight = 0;
    }
}

export interface LayoutKeyInput {
    date: string;
    /** Frame shape bucket the layout was packed for. */
    aspectKey: number;
    radiusScale: number;
    nodes: readonly { id: string; groupId: string; weight: number }[];
}

/** Everything that changes the packed result, in a stable string. The node
 *  list is folded into a 64-bit-ish digest so keys stay short. */
export function layoutKey(input: LayoutKeyInput): string {
    let a = 2166136261;
    let b = 5381;
    for (const node of input.nodes) {
        const text = `${node.id}|${node.groupId}|${node.weight};`;
        for (let i = 0; i < text.length; i++) {
            const code = text.charCodeAt(i);
            a = Math.imul(a ^ code, 16777619);
            b = (Math.imul(b, 33) + code) | 0;
        }
    }
    return [
        input.date,
        input.aspectKey,
        input.radiusScale,
        input.nodes.length,
        (a >>> 0).toString(36),
        (b >>> 0).toString(36),
    ].join(":");
}
