import { useEffect, useState } from "react";
import { artifactMode } from "../../api/artifactMode";
import { readShared } from "../shared-data/api";
import type { Families } from "../shared-data/model";
import { metadataText } from "../shared-data/model";
import { SourceInfo } from "../../components/ui/primitives";
import { CatalogCard } from "../shared-data/SharedCatalog";
import {
    datasetDetailHref,
    resolveDataset,
    safeStudyBack,
} from "./datasetJourney";
import { readStudies, type StudyCardV2 } from "../studies/v2";

function RecordedStudies({ reference }: { reference: string }) {
    const [result, setResult] = useState<{
        reference: string;
        cards?: StudyCardV2[];
        error?: string;
    }>({ reference: "" });
    useEffect(() => {
        const control = new AbortController();
        setResult({ reference });
        readStudies(control.signal)
            .then((data) => {
                if (!control.signal.aborted)
                    setResult({ reference, cards: data.cards });
            })
            .catch(() => {
                if (!control.signal.aborted)
                    setResult({ reference, error: "研究引用暫時無法核實。" });
            });
        return () => control.abort();
    }, [reference]);
    if (result.reference !== reference || !result.cards)
        return <p>{result.error ?? "正在核對研究引用…"}</p>;
    const related = result.cards.filter((card) =>
        card.provenance.shared_data.includes(reference),
    );
    return (
        <aside>
            <h2>記錄了相同引用的研究</h2>
            <p>
                僅依研究卡片的明確引用連結；未指定版本的引用不證明使用了本頁選定版本。
            </p>
            {related.length ? (
                <ul>
                    {related.map((card) => (
                        <li key={card.task_id}>
                            <a
                                href={
                                    "#studies?" +
                                    new URLSearchParams({ study: card.task_id })
                                }
                            >
                                {card.question}
                            </a>
                        </li>
                    ))}
                </ul>
            ) : (
                <p>目前沒有可核實的相同引用。</p>
            )}
        </aside>
    );
}

export function DatasetDetailPage() {
    const hash = globalThis.location?.hash ?? "#dataset";
    const query = new URLSearchParams(hash.split("?")[1] ?? "");
    const reference = query.get("ref") ?? "";
    const version = query.get("version");
    const back = safeStudyBack(query.get("back"));
    const privateMode =
        artifactMode(import.meta.env.VITE_ARTIFACT_MODE) === "local-private";
    const [retry, setRetry] = useState(0);
    const [result, setResult] = useState<{
        key: string;
        data?: Families;
        error?: string;
    }>({ key: "" });
    useEffect(() => {
        if (!privateMode) return;
        const control = new AbortController();
        setResult({ key: hash });
        readShared<Families>("families", control.signal)
            .then((data) => {
                if (!control.signal.aborted) setResult({ key: hash, data });
            })
            .catch((error: Error) => {
                if (!control.signal.aborted)
                    setResult({ key: hash, error: error.message });
            });
        return () => control.abort();
    }, [hash, privateMode, retry]);
    const current = result.key === hash ? result : null;
    const match = current?.data
        ? resolveDataset(current.data, reference, version)
        : null;
    return (
        <section className="u-page">
            <a className="u-btn" href={back}>
                返回研究情境
            </a>
            <h1 className="u-title">資料集詳情</h1>
            <p style={{ overflowWrap: "anywhere" }}>
                引用：{reference || "未提供資料身分"}
            </p>
            {version && (
                <p style={{ overflowWrap: "anywhere" }}>指定版本：{version}</p>
            )}
            {!privateMode ? (
                <p role="status">
                    公開示範模式不讀取本機研究資料。請於本機私人模式查閱此引用。
                </p>
            ) : current?.error ? (
                <div role="alert">
                    <p>{current.error}</p>
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重試
                    </button>
                </div>
            ) : !match ? (
                <p role="status">正在讀取資料身分…</p>
            ) : match.kind === "choose" ? (
                <>
                    <p>
                        這份引用沒有指定版本，無法確認研究當時使用哪一份。請明確選擇要查閱的版本；選擇目前資料不代表重現原研究。
                    </p>
                    <ul>
                        {match.choices.map((choice) => (
                            <li key={choice.version}>
                                <a
                                    href={datasetDetailHref(
                                        reference,
                                        back,
                                        choice.version,
                                    )}
                                    style={{ overflowWrap: "anywhere" }}
                                >
                                    {choice.label}：{choice.version}
                                </a>
                            </li>
                        ))}
                    </ul>
                </>
            ) : match.kind === "catalog" ? (
                <>
                    <CatalogCard
                        key={match.entry.version_id}
                        entries={[match.entry]}
                    />
                    <p>
                        此版本目前只有可核實的摘要；尚無成員
                        reader，不能從此資料集開啟股票。
                    </p>
                </>
            ) : match.kind === "family" ? (
                <>
                    <h2>{match.family.display_title || match.family.family}</h2>
                    <p>{match.family.purpose}</p>
                    <SourceInfo>
                        <p>定義：{metadataText(match.family.definition)}</p>
                        <p>價格基礎：{metadataText(match.family.bases)}</p>
                        <p>技術欄位：{metadataText(match.family.technical)}</p>
                        <p>
                            粒度與單位須依資料定義核對；此頁不是歷史當時可知資料重建。
                        </p>
                    </SourceInfo>
                    <p style={{ overflowWrap: "anywhere" }}>
                        generation：{match.family.generation}
                    </p>
                    <p>
                        {match.family.calendar.first} —{" "}
                        {match.family.calendar.last}
                    </p>
                    <p>
                        此頁確認指定
                        generation；涵蓋表與個股頁查看的是目前資料，並非這份研究的歷史重現。
                    </p>
                    {match.family.family === "adjusted-daily-v1" && (
                        <a
                            className="u-btn"
                            href={
                                "#overview/stocks?" +
                                new URLSearchParams({
                                    dataset: "adjusted_daily",
                                    kind: "",
                                    status: "all",
                                    context: hash,
                                })
                            }
                        >
                            另查目前股票涵蓋
                        </a>
                    )}
                </>
            ) : (
                <p role="alert">
                    {match.kind === "ambiguous"
                        ? "資料身分有歧義，請核對引用；不自動選取。"
                        : match.kind === "unavailable"
                          ? "此引用所需的資料來源暫時不可讀，無法判斷引用是否存在。"
                          : "找不到指定資料或版本已失效；不改用最新版本。"}
                </p>
            )}
            {privateMode && <RecordedStudies reference={reference} />}
        </section>
    );
}
