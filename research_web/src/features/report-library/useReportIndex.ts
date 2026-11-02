import { useCallback, useEffect, useState } from "react";
import {
    readReportIndex,
    ReportIndexError,
    type ReportEntry,
    type ReportIndexIssue,
} from "./model";

/** Reads /reports/index.json, which the Vite plugin builds from report meta tags. */
export function useReportIndex() {
    const [reports, setReports] = useState<ReportEntry[] | null>(null);
    const [error, setError] = useState("");
    const [issue, setIssue] = useState<ReportIndexIssue | null>(null);
    const [loading, setLoading] = useState(true);
    const [attempt, setAttempt] = useState(0);
    const retry = useCallback(() => setAttempt((value) => value + 1), []);
    useEffect(() => {
        const control = new AbortController();
        setLoading(true);
        const expectedVersion = document.querySelector<HTMLMetaElement>(
            'meta[name="research-web-version"]',
        )?.content;
        readReportIndex(control.signal, expectedVersion)
            .then((value) => {
                if (control.signal.aborted) return;
                setReports(value.reports);
                setError("");
                setIssue(null);
            })
            .catch((e: unknown) => {
                if (control.signal.aborted) return;
                setError(e instanceof Error ? e.message : String(e));
                setIssue(e instanceof ReportIndexError ? e.code : "network");
            })
            .finally(() => {
                if (!control.signal.aborted) setLoading(false);
            });
        return () => control.abort();
    }, [attempt]);
    return { reports, error, issue, loading, retry };
}
