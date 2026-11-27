import { SourceInfo, VerdictBadge } from "../../components/ui/primitives";
import type { StudyCard, StudyDetails } from "./model";
import { StudyCaveats } from "./StudyCaveats";
import { currentStudyHash, readingDate, readingState } from "./reading";
import {
    datasetDetailHref,
    studyContext,
} from "../data-overview/datasetJourney";

const UNIT: Record<StudyCard["keyNumbers"][number]["unit"], string> = {
    percent: "%",
    ratio: " 倍",
    count: "",
    days: " 天",
    twd: " 元",
};

function shortDate(date: string) {
    return date ? date.replaceAll("-", "/") : "日期未提供";
}

export function StudyCardView({
    card,
    compact = false,
}: {
    card: StudyCard;
    compact?: boolean;
}) {
    return (
        <article
            className="u-card st-card"
            id={"study-" + card.id}
            tabIndex={-1}
        >
            <div className="st-meta">
                <span>
                    {card.accountRun
                        ? card.accountRun.note
                        : `${card.reading?.updated_at ? "閱讀版更新 " : "紀錄日期 "}${shortDate(readingDate(card))}`}
                </span>
                {card.verdict && <VerdictBadge verdict={card.verdict} />}
            </div>
            <h3 className="st-question">{card.question}</h3>
            <p className="st-identity">{card.id}</p>
            {card.dataPeriod && (
                <p className="st-period">
                    研究資料：{card.dataPeriod.from} ～ {card.dataPeriod.to}
                </p>
            )}
            {card.reportKind !== "html" &&
                card.reading &&
                readingState(card) !== "ready" &&
                card.reading.reason !== card.limitation && (
                    <p className="u-notice">
                        {card.reading?.reason ?? "原始紀錄尚未完成閱讀版核對。"}
                    </p>
                )}
            {card.answer && (
                <p className={`st-answer${compact ? " is-clamped" : ""}`}>
                    {card.answer}
                </p>
            )}
            <StudyCaveats caveats={card.caveats} />
            {card.progress && <RunProgress progress={card.progress} />}
            {card.keyNumbers.length > 0 && (
                <dl className="st-numbers" aria-label="研究重點數字">
                    {card.keyNumbers.map((number) => (
                        <div
                            key={number.label}
                            className={
                                number.highlight ? "is-highlighted" : undefined
                            }
                        >
                            <dt>{number.label}</dt>
                            <dd>
                                {number.value}
                                {UNIT[number.unit]}
                            </dd>
                        </div>
                    ))}
                </dl>
            )}
            {card.limitation && <p className="st-limit">{card.limitation}</p>}
            {(card.reportHref || card.accountRun) && (
                <div className="u-actions">
                    {card.reportHref && (
                        <a
                            className="u-btn u-btn-primary"
                            href={(() => {
                                const [base, query] =
                                    card.reportHref.split("?");
                                const params = new URLSearchParams(query);
                                params.set(
                                    "back",
                                    currentStudyHash().startsWith("#studies")
                                        ? currentStudyHash()
                                        : "#studies",
                                );
                                return `${base}?${params}`;
                            })()}
                        >
                            {card.reportKind === "summary"
                                ? "查看研究紀錄"
                                : !card.reading?.edition &&
                                    card.reportHref.includes("view=reading")
                                  ? "查看原文"
                                  : "查看報告"}
                        </a>
                    )}
                    {card.accountRun && (
                        <a
                            className={`u-btn${card.reportHref ? "" : " u-btn-primary"}`}
                            href={`#strategy/${encodeURIComponent(card.accountRun.runId)}`}
                        >
                            查看模擬交易結果
                        </a>
                    )}
                </div>
            )}
            {!compact && (
                <StudyDetailsView details={card.details} studyId={card.id} />
            )}
        </article>
    );
}

export function StudyDetailsView({
    details,
    studyId,
}: {
    details: StudyDetails;
    studyId: string;
}) {
    const hasAny =
        details.originalSummary ||
        details.reportPath ||
        details.webReportReason ||
        details.sharedData.length ||
        details.sharedDataReason ||
        details.note ||
        details.numberSources.length;
    if (!hasAny) return null;
    return (
        <SourceInfo label="原文與資料來源">
            <p>研究代號：{studyId}</p>
            {details.originalSummary && (
                <p className="st-original">{details.originalSummary}</p>
            )}
            {details.webReportReason && (
                <p>沒有網頁報告：{details.webReportReason}</p>
            )}
            {details.sharedData.length > 0 && (
                <p>
                    使用的共用資料：
                    {details.sharedData.map((id, index) => (
                        <span key={id}>
                            {index ? "、" : ""}
                            <a
                                href={datasetDetailHref(
                                    id,
                                    studyContext(
                                        globalThis.location?.hash ?? "",
                                        studyId,
                                    ),
                                )}
                            >
                                {id}
                            </a>
                        </span>
                    ))}
                    {" · "}
                    <a href="#data">查看資料總覽</a>
                </p>
            )}
            {details.sharedDataReason && <p>{details.sharedDataReason}</p>}
            {details.note && <p>{details.note}</p>}
            {details.numberSources.map((source) => (
                <p key={source.label} className="st-original">
                    {source.label}的出處：{source.excerpt}
                </p>
            ))}
            {details.reportPath && <p>報告檔：{details.reportPath}</p>}
        </SourceInfo>
    );
}

function RunProgress({
    progress,
}: {
    progress: NonNullable<StudyCard["progress"]>;
}) {
    const ratio =
        progress.step !== null && progress.total
            ? Math.min(1, Math.max(0, progress.step / progress.total))
            : null;
    return (
        <div className="st-progress">
            <span>
                {ratio !== null
                    ? `執行中：第 ${progress.step}／${progress.total} 步`
                    : "執行中"}
                {progress.label ? `・${progress.label}` : ""}
            </span>
            {ratio !== null && (
                <span className="u-track">
                    <span style={{ width: `${ratio * 100}%` }} />
                </span>
            )}
        </div>
    );
}
