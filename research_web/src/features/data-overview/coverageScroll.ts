export interface CoverageScrollAdapter {
    storage: Pick<Storage, "getItem" | "setItem">;
    window: Pick<
        Window,
        "scrollY" | "scrollTo" | "addEventListener" | "removeEventListener"
    >;
    table: () => HTMLElement | null;
    requestFrame: typeof requestAnimationFrame;
    cancelFrame: typeof cancelAnimationFrame;
}

interface ScrollSnapshot {
    windowY: number;
    table: { top: number; left: number } | null;
}

function readSnapshot(
    key: string,
    storage: CoverageScrollAdapter["storage"],
): ScrollSnapshot {
    let windowY = 0;
    let table: ScrollSnapshot["table"] = null;
    try {
        const storedY = Number(storage.getItem(`coverage-scroll:${key}`));
        if (Number.isFinite(storedY) && storedY >= 0) windowY = storedY;
        const storedTable = storage.getItem(`coverage-table-scroll:${key}`);
        if (storedTable) {
            const parsed = JSON.parse(storedTable) as {
                top?: number;
                left?: number;
            };
            const top = Number(parsed.top ?? 0);
            const left = Number(parsed.left ?? 0);
            if (
                Number.isFinite(top) &&
                top >= 0 &&
                Number.isFinite(left) &&
                left >= 0
            ) {
                table = { top, left };
            }
        }
    } catch {
        // A blocked or stale session storage value should not prevent navigation.
    }
    return { windowY, table };
}

/** Restore a query's outer and matrix scroll positions without cross-writing them. */
export function restoreCoverageScroll(
    key: string,
    adapter: CoverageScrollAdapter,
): () => void {
    // Read before installing listeners: native restoration or scrollTo must not
    // overwrite the values that this invocation is about to restore.
    const saved = readSnapshot(key, adapter.storage);
    let mounted = true;
    let restoring = true;
    let releaseFrame: number | null = null;
    const windowKey = `coverage-scroll:${key}`;
    const tableKey = `coverage-table-scroll:${key}`;
    const tableAtMount = adapter.table();

    const saveWindow = () => {
        if (
            !mounted ||
            restoring ||
            !tableAtMount?.isConnected ||
            adapter.table() !== tableAtMount
        )
            return;
        try {
            adapter.storage.setItem(windowKey, String(adapter.window.scrollY));
        } catch {
            // Storage is optional.
        }
    };
    const saveTable = (event: Event) => {
        const eventTable = event.currentTarget as HTMLElement | null;
        if (
            !mounted ||
            restoring ||
            !eventTable?.isConnected ||
            eventTable !== adapter.table()
        )
            return;
        try {
            adapter.storage.setItem(
                tableKey,
                JSON.stringify({
                    top: eventTable.scrollTop,
                    left: eventTable.scrollLeft,
                }),
            );
        } catch {
            // Storage is optional.
        }
    };

    adapter.window.addEventListener("scroll", saveWindow, { passive: true });
    if (tableAtMount?.isConnected)
        tableAtMount.addEventListener("scroll", saveTable, { passive: true });

    const restoreFrame = adapter.requestFrame(() => {
        if (!mounted) return;
        restoring = true;
        adapter.window.scrollTo({ top: saved.windowY, behavior: "instant" });
        const table = adapter.table();
        if (saved.table && table?.isConnected) {
            table.scrollTop = saved.table.top;
            table.scrollLeft = saved.table.left;
        }
        // Keep restoration events gated through the next paint.
        releaseFrame = adapter.requestFrame(() => {
            if (mounted) restoring = false;
        });
    });

    return () => {
        mounted = false;
        adapter.cancelFrame(restoreFrame);
        if (releaseFrame !== null) adapter.cancelFrame(releaseFrame);
        adapter.window.removeEventListener("scroll", saveWindow);
        if (tableAtMount) tableAtMount.removeEventListener("scroll", saveTable);
    };
}
