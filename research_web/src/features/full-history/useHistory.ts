import { useCallback, useEffect, useRef, useState } from "react";
import { readHistory, readHistoryWhenReady } from "./api.ts";
import {
    dateIndex,
    initialHistoryIndex,
    isCurrentRequest,
    type RequestIdentity,
} from "./model.ts";
import {
    HISTORY_SCHEMA,
    type HistoryMetadata,
    type HistoryFrame,
    type HistoryDetail,
    type HistoryDirectory,
} from "./types.ts";

/** One snapshot and one rendered date; interrupted requests never replace newer data. */
export function useHistory(active: boolean) {
    const [metadata, setMetadata] = useState<HistoryMetadata | null>(null);
    const [metadataError, setMetadataError] = useState("");
    const [startup, setStartup] = useState<{
        stage: string;
        completed: number;
        total: number;
    } | null>(null);
    const [directory, setDirectory] = useState<HistoryDirectory | null>(null);
    const [directoryError, setDirectoryError] = useState("");
    const [retry, setRetry] = useState(0);
    const [index, setIndex] = useState(0);
    const [frame, setFrame] = useState<HistoryFrame | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [playing, setPlaying] = useState(false);
    const [step, setStep] = useState(20);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [detail, setDetail] = useState<HistoryDetail | null>(null);
    const [detailError, setDetailError] = useState("");
    const [detailLoading, setDetailLoading] = useState(false);
    const request = useRef<RequestIdentity>({
        epoch: 0,
        catalogId: "",
        date: "",
    });
    const frameAbort = useRef<AbortController | null>(null);
    const detailEpoch = useRef(0);
    const cached = useRef(new Map<string, HistoryFrame>());
    const [queryDate, setQueryDate] = useState("");
    const lastQueryAt = useRef(0);
    const desiredDate = metadata?.dates[index] ?? "";
    const navigate = useCallback(
        (next: number) => {
            if (!metadata) return;
            const clamped = Math.max(
                0,
                Math.min(next, metadata.dates.length - 1),
            );
            if (clamped === index) return;
            detailEpoch.current += 1;
            setIndex(clamped);
            setError("");
            const saved = cached.current.get(metadata.dates[clamped]);
            if (saved?.catalogId === metadata.catalogId) {
                frameAbort.current?.abort();
                request.current.epoch += 1;
                setFrame(saved);
                setLoading(false);
            }
        },
        [metadata, index],
    );
    const goToDate = useCallback(
        (date: string) => {
            if (!metadata || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
            setPlaying(false);
            navigate(dateIndex(metadata.dates, date));
        },
        [metadata, navigate],
    );
    useEffect(() => {
        if (!active || !desiredDate) return;
        // Leading updates while dragging, then a trailing update to the exact
        // final date. A continuous gesture must not starve all frame requests.
        const delay = Math.max(
            0,
            180 - (performance.now() - lastQueryAt.current),
        );
        const timer = window.setTimeout(() => {
            lastQueryAt.current = performance.now();
            setQueryDate(desiredDate);
        }, delay);
        return () => window.clearTimeout(timer);
    }, [active, desiredDate]);
    useEffect(() => {
        if (!active || metadata) return;
        const controller = new AbortController();
        setMetadataError("");
        readHistoryWhenReady<HistoryMetadata>(
            "/metadata",
            controller.signal,
            (value) => {
                if (!controller.signal.aborted) setStartup(value);
            },
        )
            .then((data) => {
                if (controller.signal.aborted) return;
                if (
                    data.schema !== HISTORY_SCHEMA ||
                    !data.catalogId ||
                    !data.dates.length ||
                    data.dates.some(
                        (d, i) =>
                            !/^\d{4}-\d{2}-\d{2}$/.test(d) ||
                            (i > 0 && d <= data.dates[i - 1]),
                    )
                )
                    throw new Error("歷史日期資料不完整");
                const [page, query = ""] = location.hash.split("?");
                const requestedDate =
                    page === "#market"
                        ? new URLSearchParams(query).get("date")
                        : null;
                setIndex(
                    initialHistoryIndex(
                        data.dates,
                        data.catalogId,
                        (key) => localStorage.getItem(key),
                        requestedDate,
                    ),
                );
                setMetadata(data);
            })
            .catch((cause) => {
                if (!controller.signal.aborted) setMetadataError(String(cause));
            });
        return () => controller.abort();
    }, [active, metadata, retry]);
    useEffect(() => {
        if (!active || !metadata || directory) return;
        const controller = new AbortController();
        setDirectoryError("");
        readHistory<HistoryDirectory>("/directory", controller.signal)
            .then((data) => {
                if (controller.signal.aborted) return;
                if (
                    data.schema !== HISTORY_SCHEMA ||
                    data.catalogId !== metadata.catalogId ||
                    !Array.isArray(data.rows)
                )
                    throw new Error("時間帶與地圖的資料版本不一致");
                setDirectory(data);
            })
            .catch((cause) => {
                if (!controller.signal.aborted)
                    setDirectoryError(String(cause));
            });
        return () => controller.abort();
    }, [active, metadata, directory, retry]);
    useEffect(() => {
        const identity = {
            epoch: request.current.epoch + 1,
            catalogId: metadata?.catalogId ?? "",
            date: queryDate,
        };
        request.current = identity;
        if (!active || !metadata || !queryDate) {
            setLoading(false);
            setPlaying(false);
            return;
        }
        try {
            localStorage.setItem(
                `history.date.${metadata.catalogId}`,
                queryDate,
            );
        } catch {
            /* Optional. */
        }
        const saved = cached.current.get(queryDate);
        if (saved?.catalogId === metadata.catalogId) {
            setFrame(saved);
            setLoading(false);
            return;
        }
        const controller = new AbortController();
        frameAbort.current = controller;
        setLoading(true);
        const timer = window.setTimeout(() => {
            readHistory<HistoryFrame>(
                `/frame?date=${encodeURIComponent(queryDate)}`,
                controller.signal,
            )
                .then((data) => {
                    if (
                        controller.signal.aborted ||
                        !isCurrentRequest(identity, request.current)
                    )
                        return;
                    if (!isCurrentRequest(identity, request.current, data))
                        throw new Error("資料日期或版本不一致");
                    cached.current.set(data.date, data);
                    if (cached.current.size > 24)
                        cached.current.delete(
                            cached.current.keys().next().value!,
                        );
                    setFrame(data);
                    setError("");
                    setLoading(false);
                })
                .catch((cause) => {
                    if (
                        !controller.signal.aborted &&
                        isCurrentRequest(identity, request.current)
                    ) {
                        setError(String(cause));
                        setLoading(false);
                        setPlaying(false);
                    }
                });
        }, 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
            request.current.epoch += 1;
        };
    }, [active, metadata, queryDate, retry]);
    useEffect(() => {
        if (
            !active ||
            !playing ||
            !metadata ||
            loading ||
            error ||
            frame?.date !== desiredDate
        )
            return;
        if (index >= metadata.dates.length - 1) {
            setPlaying(false);
            return;
        }
        const timer = window.setTimeout(
            () => navigate(Math.min(index + step, metadata.dates.length - 1)),
            650,
        );
        return () => window.clearTimeout(timer);
    }, [
        active,
        playing,
        metadata,
        loading,
        error,
        frame,
        desiredDate,
        index,
        step,
        navigate,
    ]);
    useEffect(() => {
        const epoch = ++detailEpoch.current;
        setDetail(null);
        setDetailError("");
        setDetailLoading(false);
        if (
            !active ||
            !frame ||
            !selectedId ||
            loading ||
            frame.date !== desiredDate
        )
            return;
        const selected = frame.rows.find(
            (row) => row.securityId === selectedId,
        );
        const directoryRow = directory?.rows.find(
            (row) => row.securityId === selectedId,
        );
        const code = selected?.code ?? directoryRow?.code;
        if (!code) return;
        const controller = new AbortController();
        // The displayed frame may be a cache hit before the throttled map
        // query catches up. Detail requests have their own generation/date.
        const identity = {
            epoch,
            catalogId: frame.catalogId,
            date: frame.date,
        };
        setDetailLoading(true);
        readHistory<HistoryDetail>(
            `/security/${encodeURIComponent(code)}?date=${encodeURIComponent(frame.date)}`,
            controller.signal,
        )
            .then((data) => {
                if (controller.signal.aborted || epoch !== detailEpoch.current)
                    return;
                if (
                    data.catalogId !== identity.catalogId ||
                    data.date !== identity.date ||
                    (data.row && data.row.securityId !== selectedId)
                )
                    throw new Error("個股資料與地圖日期不一致");
                setDetail(data);
                setDetailLoading(false);
            })
            .catch((cause) => {
                if (
                    !controller.signal.aborted &&
                    epoch === detailEpoch.current
                ) {
                    setDetailError(String(cause));
                    setDetailLoading(false);
                }
            });
        return () => {
            controller.abort();
            detailEpoch.current += 1;
        };
    }, [active, frame, selectedId, directory, loading, desiredDate, retry]);
    return {
        metadata,
        metadataError,
        startup,
        directory,
        directoryError,
        index,
        frame,
        loading,
        error,
        desiredDate,
        playing,
        setPlaying,
        step,
        setStep,
        navigate,
        goToDate,
        selectedId,
        setSelectedId,
        detail,
        detailError,
        detailLoading,
        retry: () => setRetry((v) => v + 1),
    };
}
