import {
    CompareBars,
    SourceInfo,
    VerdictBadge,
} from "../../components/ui/primitives";
import type { StudyCard, StudyDetails } from "./model";

const UNIT: Record<StudyCard["keyNumbers"][number]["unit"], string> = {
    percent: "%",
    ratio: " 倍",
    count: "",
    days: " 天",
    twd: " 元",
};

function shortDate(date: string) {
    return `${Number(date.slice(5, 7))} 月 ${Number(date.slice(8, 10))} 日`;
}

export function StudyCardView({
    card,
    compact = false,
}: {
    card: StudyCard;
    compact?: boolean;
}) {
    return (
        <article className="u-card st-card">
            <div className="st-meta">
                <span>
                    {card.accountRun
                        ? card.accountRun.note
                        : shortDate(card.date)}
                </span>
                {card.verdict && <VerdictBadge verdict={card.verdict} />}
            </div>
            <h3 className="st-question">{card.question}</h3>
            {card.answer && (
                <p className={`st-answer${compact ? " is-clamped" : ""}`}>
                    {card.answer}
                </p>
            )}
            {card.keyNumbers.length > 0 && (
                <CompareBars
                    rows={card.keyNumbers.map((number) => ({
                        label: number.label,
                        value: number.value,
                        display: `${number.value}${UNIT[number.unit]}`,
                        highlight: number.highlight,
                    }))}
                />
            )}
            {card.limitation && !compact && (
                <p className="st-limit">{card.limitation}</p>
            )}
            {(card.reportHref || card.accountRun) && (
                <div className="u-actions">
                    {card.reportHref && (
                        <a
                            className="u-btn u-btn-primary"
                            href={card.reportHref}
                        >
                            讀報告
                        </a>
                    )}
                    {card.accountRun && (
                        <a
                            className={`u-btn${card.reportHref ? "" : " u-btn-primary"}`}
                            href={`#strategy/${encodeURIComponent(card.accountRun.runId)}`}
                        >
                            看帳戶模擬
                        </a>
                    )}
                </div>
            )}
            {!compact && <StudyDetailsView details={card.details} />}
        </article>
    );
}

function StudyDetailsView({ details }: { details: StudyDetails }) {
    const hasAny =
        details.originalSummary ||
        details.reportPath ||
        details.webReportReason ||
        details.sharedData.length ||
        details.sharedDataReason ||
        details.note;
    if (!hasAny) return null;
    return (
        <SourceInfo label="原文與資料來源">
            {details.summaryUnconfirmed && (
                <p>上面的白話摘要還沒經過研究端核對，以原文為準。</p>
            )}
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
                            <a href="#data">{id}</a>
                        </span>
                    ))}
                </p>
            )}
            {details.sharedDataReason && <p>{details.sharedDataReason}</p>}
            {details.note && <p>{details.note}</p>}
            {details.reportPath && <p>報告檔：{details.reportPath}</p>}
        </SourceInfo>
    );
}
