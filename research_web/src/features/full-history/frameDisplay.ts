export type FrameDisplayStatus = "loading" | "updating" | "failed" | "ready";

export interface FrameDisplay {
    status: FrameDisplayStatus;
    renderedDate: string | null;
    requestedDate: string;
    rowCount: number | null;
    hasFrame: boolean;
}

/** A pending request never turns unavailable data into a successful empty frame. */
export function historyFrameDisplay({
    frame,
    desiredDate,
    loading,
    error,
}: {
    frame: { date: string; rows: readonly unknown[] } | null;
    desiredDate: string;
    loading: boolean;
    error: string;
}): FrameDisplay {
    const hasFrame = frame !== null;
    const status = loading
        ? hasFrame
            ? "updating"
            : "loading"
        : error
          ? "failed"
          : !hasFrame
            ? "loading"
            : frame.date !== desiredDate
              ? "updating"
              : "ready";
    return {
        status,
        renderedDate: frame?.date ?? null,
        requestedDate: desiredDate,
        rowCount: frame?.rows.length ?? null,
        hasFrame,
    };
}

export function frameStatusMessage(display: FrameDisplay): string {
    if (display.status === "ready") return `正在觀察 ${display.renderedDate}`;
    const request = display.requestedDate ? ` ${display.requestedDate}` : "";
    const retained = display.hasFrame
        ? `；仍顯示 ${display.renderedDate} 的行情`
        : "";
    return display.status === "failed"
        ? `行情${request}讀取失敗${retained}`
        : `正在讀取${request} 的行情${retained}`;
}
