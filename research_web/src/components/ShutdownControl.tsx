import { useState } from "react";
import { shutdownDashboard } from "../api/client";

interface ShutdownControlProps {
    /** Called once the shutdown request has been sent, so App can show the closed state. */
    onShutdown: () => void;
}

/**
 * Always-visible control that lets a researcher stop the local dashboard server
 * without touching the terminal. Renders its own confirm step so a stray click
 * can't take down the server (see research_api's POST /shutdown).
 */
export function ShutdownControl({ onShutdown }: ShutdownControlProps) {
    const [confirming, setConfirming] = useState(false);
    const [pending, setPending] = useState(false);

    const cancel = () => {
        if (pending) return;
        setConfirming(false);
    };

    const confirm = async () => {
        setPending(true);
        await shutdownDashboard();
        setPending(false);
        setConfirming(false);
        onShutdown();
    };

    return (
        <>
            <button
                type="button"
                className="shutdown-btn"
                onClick={() => setConfirming(true)}
                title="關閉 Dashboard"
            >
                <span aria-hidden="true">⏻</span> 關閉
            </button>
            {confirming && (
                <div
                    className="modal-overlay"
                    role="presentation"
                    onClick={cancel}
                >
                    <div
                        className="modal panel"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="shutdown-modal-title"
                        onClick={(event) => event.stopPropagation()}
                    >
                        <button
                            type="button"
                            className="modal-close"
                            aria-label="關閉對話框"
                            onClick={cancel}
                            disabled={pending}
                        >
                            ×
                        </button>
                        <h2 id="shutdown-modal-title" className="panel-title">
                            確認關閉 Dashboard？
                        </h2>
                        <p className="modal-body">
                            關閉後研究伺服器將會停止，需重新執行
                            scripts\research\open_research_dashboard.cmd
                            才能再次開啟。
                        </p>
                        <div className="modal-actions">
                            <button
                                type="button"
                                className="chip-toggle"
                                onClick={cancel}
                                disabled={pending}
                            >
                                取消
                            </button>
                            <button
                                type="button"
                                className="btn-danger"
                                onClick={confirm}
                                disabled={pending}
                            >
                                {pending ? "關閉中…" : "確認關閉"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
