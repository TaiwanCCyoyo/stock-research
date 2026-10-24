import { useEffect, useMemo, useState } from "react";
import { useStudioHistory, useStudioIndex } from "../../api/strategyStudio";
import { useReportIndex } from "../report-library/useReportIndex";
import { money } from "../strategies/format";
import { strategyTitle } from "../strategies/presentation";
import {
    cardFromHistory,
    cardFromReport,
    cardFromRun,
    mergeStudyCards,
    type StudyCard,
} from "./model";
import {
    cardsFromStudies,
    hiddenCount,
    readStudies,
    type StudiesResponse,
} from "./v2";

function useStudiesV2() {
    const [state, setState] = useState<{
        data: StudiesResponse | null;
        error: string;
    }>({ data: null, error: "" });
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setState({ data: null, error: "" });
        readStudies(control.signal)
            .then((data) => setState({ data, error: "" }))
            .catch((cause: Error) => {
                if (cause.name !== "AbortError")
                    setState({
                        data: null,
                        error: cause.message || "研究卡片暫時讀不到。",
                    });
            });
        return () => control.abort();
    }, [retry]);
    return { ...state, retry: () => setRetry((n) => n + 1) };
}

/** Research cards from GET /studies (study-card.v2). When that service is
 *  unavailable, falls back to the saved history, the static web-report index
 *  and the archived account runs so the page never loses its report links. */
export function useStudyCards() {
    const studies = useStudiesV2();
    const fallback = !!studies.error;
    const history = useStudioHistory(),
        index = useStudioIndex(),
        reportIndex = useReportIndex();
    const cards = useMemo<StudyCard[] | null>(() => {
        // A successful /studies response is authoritative: a card it omits
        // failed source checks and must not return through the report index.
        if (studies.data) return cardsFromStudies(studies.data);
        if (!fallback) return null;
        const runs = (index.data?.runs ?? []).map((run) =>
            cardFromRun(
                run,
                strategyTitle(run),
                `${money(run.initialCapital)} 變成 ${money(run.finalEquity)}。`,
            ),
        );
        const merged = mergeStudyCards(
            history.data?.items.map(cardFromHistory) ?? null,
            reportIndex.reports?.map(cardFromReport) ?? null,
        );
        return merged && [...merged, ...runs];
    }, [studies.data, fallback, history.data, index.data, reportIndex.reports]);
    return {
        cards,
        hidden: studies.data ? hiddenCount(studies.data) : 0,
        partial: fallback && !history.data && !!history.error && !!cards,
        synthetic: history.data?.source?.mode === "public-synthetic",
        source: fallback ? history.data?.source : undefined,
        loading: !studies.data && (!fallback || history.loading),
        error: fallback && !cards ? history.error || studies.error : "",
        retry: () => {
            studies.retry();
            history.retry();
            index.retry();
        },
    };
}
