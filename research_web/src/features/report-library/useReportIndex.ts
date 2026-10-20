import { useEffect, useState } from "react";
import { validateReportIndex, type ReportEntry } from "./model";

/** Reads /reports/index.json, which the Vite plugin builds from report meta tags. */
export function useReportIndex() {
    const [reports, setReports] = useState<ReportEntry[] | null>(null);
    const [error, setError] = useState("");
    useEffect(() => {
        const control = new AbortController();
        const expectedVersion = document.querySelector<HTMLMetaElement>(
            'meta[name="research-web-version"]',
        )?.content;
        fetch("/reports/index.json", {
            signal: control.signal,
            cache: "no-store",
        })
            .then((response) => {
                if (!response.ok)
                    throw new Error(
                        `報告清單讀取失敗（HTTP ${response.status}）`,
                    );
                return response.json();
            })
            .then((value) =>
                setReports(validateReportIndex(value, expectedVersion).reports),
            )
            .catch((e) => {
                if (e.name !== "AbortError") setError(e.message);
            });
        return () => control.abort();
    }, []);
    return { reports, error };
}
