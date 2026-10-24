/** One plain line about an overlay that is loading, busy, empty or failed. */
export function OverlayStatus({
    label,
    overlay,
}: {
    label: string;
    overlay: {
        loading: boolean;
        error: string;
        data: { status: string; warnings: string[] } | null;
    };
}) {
    const { loading, error, data } = overlay;
    const text = loading
        ? `正在讀取${label}…`
        : error
          ? `${label}：${error}`
          : data?.status === "updating"
            ? `${label}：每日資料正在更新，稍後再試。`
            : data?.status === "missing"
              ? `${label}：${data.warnings[0] ?? "沒有已保存的資料。"}`
              : "";
    return text ? <p className="overlay-status">{text}</p> : null;
}
