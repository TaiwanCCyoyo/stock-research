/** Keep one active request and only the newest request waiting behind it. */
export class LatestQueue<T> {
    private active = false;
    private pending: T | null = null;

    offer(value: T): T | null {
        if (this.active) {
            this.pending = value;
            return null;
        }
        this.active = true;
        return value;
    }

    complete(): T | null {
        if (this.pending !== null) {
            const next = this.pending;
            this.pending = null;
            return next;
        }
        this.active = false;
        return null;
    }

    reset(): void {
        this.active = false;
        this.pending = null;
    }
}
