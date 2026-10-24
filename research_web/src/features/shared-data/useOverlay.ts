import { useEffect, useState } from "react";
import { readSeries, type SeriesResponse } from "./overlays";

/** Loads one stored overlay series for the shown stock, only while enabled. */
export function useOverlay<Row>(
    dataset: SeriesResponse<Row>["dataset"],
    code: string | null,
    from: string | null,
    enabled: boolean,
) {
    const [state, setState] = useState<{
        key: string;
        data: SeriesResponse<Row> | null;
        error: string;
    }>({ key: "", data: null, error: "" });
    const key = enabled && code ? `${dataset}:${code}:${from ?? ""}` : "";
    useEffect(() => {
        if (!key || !code) return;
        const control = new AbortController();
        readSeries<Row>(dataset, code, from, control.signal)
            .then((data) => setState({ key, data, error: "" }))
            .catch((cause: Error) => {
                if (cause.name !== "AbortError")
                    setState({
                        key,
                        data: null,
                        error: cause.message || "資料暫時讀不到。",
                    });
            });
        return () => control.abort();
    }, [key, dataset, code, from]);
    const current = state.key === key && key !== "";
    return {
        data: current ? state.data : null,
        error: current ? state.error : "",
        loading: key !== "" && !current,
    };
}
