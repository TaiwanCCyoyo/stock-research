import { useMemo } from "react";
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

/** Research cards from the saved history, the static web-report index and the
 *  archived account runs. The report index needs no history API, so reports
 *  stay reachable when that service is unavailable. Replaced by GET /studies
 *  once study-card.v2 is served. */
export function useStudyCards() {
    const history = useStudioHistory(),
        index = useStudioIndex(),
        reportIndex = useReportIndex();
    const cards = useMemo<StudyCard[] | null>(() => {
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
    }, [history.data, index.data, reportIndex.reports]);
    return {
        cards,
        partial: !history.data && !!history.error && !!cards,
        synthetic: history.data?.source?.mode === "public-synthetic",
        source: history.data?.source,
        loading: history.loading,
        error: history.error,
        retry: () => {
            history.retry();
            index.retry();
        },
    };
}
