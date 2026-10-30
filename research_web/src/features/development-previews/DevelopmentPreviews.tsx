import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../../api/base";
import {
    loadPreviews,
    openMainDashboard,
    startPreview,
    STATUS_LABELS,
    type PreviewIndex,
} from "./model";
import "./previews.css";

export function DevelopmentPreviews() {
    const [open, setOpen] = useState(false);
    const [revision, setRevision] = useState(0);
    const [index, setIndex] = useState<PreviewIndex>({
        items: [],
        current: null,
    });
    const [loading, setLoading] = useState(false);
    const [listError, setListError] = useState("");
    const [launchError, setLaunchError] = useState("");
    const [starting, setStarting] = useState<string | null>(null);
    const [mainPending, setMainPending] = useState(false);
    const [mainError, setMainError] = useState("");
    const dialog = useRef<HTMLDialogElement>(null);
    const trigger = useRef<HTMLButtonElement>(null);
    const launch = useRef<AbortController | null>(null);
    const mainLaunch = useRef<AbortController | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        let timer: ReturnType<typeof setTimeout> | undefined;
        let polls = 0;
        const refresh = async () => {
            setLoading(true);
            try {
                const next = await loadPreviews(
                    apiUrl("development-previews"),
                    controller.signal,
                );
                if (controller.signal.aborted) return;
                setIndex(next);
                setListError("");
                if (
                    open &&
                    next.items.some((item) => item.status === "starting")
                ) {
                    if (++polls < 60) timer = setTimeout(refresh, 2000);
                    else setListError("啟動仍未完成。可以稍後重新整理清單。");
                }
            } catch (reason) {
                if (!controller.signal.aborted)
                    setListError(
                        reason instanceof Error
                            ? reason.message
                            : "暫時無法取得預覽清單。",
                    );
            } finally {
                if (!controller.signal.aborted) setLoading(false);
            }
        };
        void refresh();
        return () => {
            controller.abort();
            clearTimeout(timer);
        };
    }, [open, revision]);

    useEffect(() => {
        if (open) dialog.current?.showModal();
        else dialog.current?.close();
    }, [open]);

    useEffect(
        () => () => {
            launch.current?.abort();
            const controller = mainLaunch.current;
            mainLaunch.current = null;
            controller?.abort();
        },
        [],
    );

    const returnToMain = async () => {
        if (!index.current || mainLaunch.current) return;
        const controller = new AbortController();
        mainLaunch.current = controller;
        setMainPending(true);
        setMainError("");
        try {
            const url = await openMainDashboard(
                apiUrl("development-main"),
                index.current.mainUrl,
                controller.signal,
            );
            if (!controller.signal.aborted) window.location.assign(url);
        } catch (reason) {
            if (!controller.signal.aborted)
                setMainError(
                    reason instanceof Error
                        ? reason.message
                        : "正式版暫時無法開啟，請稍後重試。",
                );
        } finally {
            if (mainLaunch.current === controller) {
                mainLaunch.current = null;
                setMainPending(false);
            }
        }
    };

    const cancelReturn = () => {
        mainLaunch.current?.abort();
        mainLaunch.current = null;
        setMainPending(false);
        setMainError("");
    };

    const close = () => {
        launch.current?.abort();
        setStarting(null);
        setOpen(false);
        trigger.current?.focus();
    };

    const start = async (id: string) => {
        launch.current?.abort();
        const controller = new AbortController();
        launch.current = controller;
        setStarting(id);
        setLaunchError("");
        try {
            await startPreview(
                apiUrl(`development-previews/${encodeURIComponent(id)}/open`),
                controller.signal,
            );
            if (!controller.signal.aborted) setRevision((value) => value + 1);
        } catch (reason) {
            if (!controller.signal.aborted)
                setLaunchError(
                    reason instanceof Error ? reason.message : "預覽未能啟動。",
                );
        } finally {
            if (!controller.signal.aborted) setStarting(null);
        }
    };

    return (
        <div className="dp-control">
            {index.current && (
                <span className="dp-context">
                    <span title={index.current.title}>
                        開發預覽
                        {index.current.pr ? ` · PR #${index.current.pr}` : ""}
                    </span>
                    <button
                        className="dp-return"
                        disabled={mainPending}
                        onClick={() => void returnToMain()}
                    >
                        {mainPending ? "正在開啟正式版…" : "返回正式版"}
                    </button>
                </span>
            )}
            {(mainPending || mainError) && (
                <section
                    className="dp-main-feedback"
                    aria-label="返回正式版狀態"
                >
                    <p role="status" aria-live="polite">
                        {mainPending ? "正在開啟正式版…" : mainError}
                    </p>
                    {mainPending ? (
                        <button onClick={cancelReturn}>取消等待</button>
                    ) : (
                        <div>
                            <button onClick={() => void returnToMain()}>
                                重試
                            </button>
                            <button onClick={() => setMainError("")}>
                                關閉
                            </button>
                        </div>
                    )}
                </section>
            )}
            <button
                className="dp-trigger"
                ref={trigger}
                aria-haspopup="dialog"
                aria-expanded={open}
                aria-controls="development-preview-dialog"
                onClick={() => setOpen(true)}
            >
                開發預覽
            </button>
            <dialog
                id="development-preview-dialog"
                ref={dialog}
                className="dp-dialog"
                aria-labelledby="development-preview-title"
                onCancel={(event) => {
                    event.preventDefault();
                    close();
                }}
                onClose={close}
            >
                <header className="dp-heading">
                    <h2 id="development-preview-title">開發預覽</h2>
                    <button
                        className="u-icon-button"
                        aria-label="關閉開發預覽"
                        onClick={close}
                    >
                        ×
                    </button>
                </header>
                <p className="dp-intro">
                    查看尚未合併的修改。預覽會在新分頁開啟。
                </p>
                <div aria-live="polite" role="status">
                    {listError && <p className="dp-error">{listError}</p>}
                    {launchError && <p className="dp-error">{launchError}</p>}
                    {loading && !index.items.length && <p>正在取得預覽清單…</p>}
                </div>
                {!loading && !listError && index.items.length === 0 && (
                    <p className="dp-empty">目前沒有已登記的開發預覽。</p>
                )}
                <ul className="dp-list">
                    {index.items.map((item) => (
                        <li key={item.id}>
                            <div className="dp-item-heading">
                                <strong>{item.title}</strong>
                                {item.pr && <span>PR #{item.pr}</span>}
                            </div>
                            <p className="dp-status">
                                {STATUS_LABELS[item.status]}
                            </p>
                            {item.message && (
                                <p className="dp-message">{item.message}</p>
                            )}
                            <details>
                                <summary>版本資訊</summary>
                                <p>
                                    {item.branch} ·{" "}
                                    {item.head.slice(0, 8) || "版本未提供"}
                                </p>
                            </details>
                            {item.status === "ready" && item.url ? (
                                <a
                                    className="dp-open"
                                    href={item.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    開啟預覽 ↗
                                </a>
                            ) : item.status === "stopped" ? (
                                <button
                                    className="dp-open"
                                    disabled={starting !== null}
                                    onClick={() => void start(item.id)}
                                >
                                    {starting === item.id
                                        ? "正在啟動…"
                                        : "啟動預覽"}
                                </button>
                            ) : null}
                        </li>
                    ))}
                </ul>
                <footer className="dp-footer">
                    <button
                        disabled={loading}
                        onClick={() => setRevision((value) => value + 1)}
                    >
                        {loading ? "正在更新…" : "重新整理清單"}
                    </button>
                </footer>
            </dialog>
        </div>
    );
}
