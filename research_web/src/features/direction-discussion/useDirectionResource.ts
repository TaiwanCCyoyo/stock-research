import { useEffect, useState } from "react";

export type DirectionResource<T> =
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "loaded"; data: T };

export function useDirectionResource<T>(
    requestKey: string,
    load: (signal: AbortSignal) => Promise<T>,
) {
    const [attempt, setAttempt] = useState(0);
    const [stored, setStored] = useState<{
        requestKey: string;
        attempt: number;
        state: DirectionResource<T>;
    } | null>(null);
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setStored({ requestKey, attempt, state: { status: "loading" } });
        load(controller.signal)
            .then((data) => {
                if (active && !controller.signal.aborted)
                    setStored({
                        requestKey,
                        attempt,
                        state: { status: "loaded", data },
                    });
            })
            .catch((error: unknown) => {
                if (active && !controller.signal.aborted)
                    setStored({
                        requestKey,
                        attempt,
                        state: {
                            status: "error",
                            message:
                                error instanceof Error
                                    ? error.message
                                    : "方向草稿暫時無法讀取。",
                        },
                    });
            });
        return () => {
            active = false;
            controller.abort();
        };
    }, [requestKey, attempt, load]);
    // A prop/retry change hides the old view immediately, before effect cleanup runs.
    const state: DirectionResource<T> =
        stored?.requestKey === requestKey && stored.attempt === attempt
            ? stored.state
            : { status: "loading" };
    return { state, retry: () => setAttempt((value) => value + 1) };
}
