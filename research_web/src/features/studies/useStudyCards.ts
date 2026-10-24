import { useMemo } from "react";
import { useStudioHistory, useStudioIndex } from "../../api/strategyStudio";
import { money } from "../strategies/format";
import { strategyTitle } from "../strategies/presentation";
import { cardFromHistory, cardFromRun, type StudyCard } from "./model";

/** Research cards from the saved history plus the archived account runs.
 *  Replaced by GET /studies once study-card.v2 is served. */
export function useStudyCards() {
    const history = useStudioHistory(),
        index = useStudioIndex();
    const cards = useMemo<StudyCard[] | null>(() => {
        if (!history.data) return null;
        const runs = (index.data?.runs ?? []).map((run) =>
            cardFromRun(
                run,
                strategyTitle(run),
                `${money(run.initialCapital)} 變成 ${money(run.finalEquity)}。`,
            ),
        );
        return [...history.data.items.map(cardFromHistory), ...runs];
    }, [history.data, index.data]);
    return {
        cards,
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
