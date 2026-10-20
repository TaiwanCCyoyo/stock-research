export type PrivateReadState<T = unknown> =
    | { status: "loading"; historical: null }
    | { status: "failure"; message: string; historical: null }
    | { status: "success"; historical: T }
    | { status: "demo"; historical: T | null };

export type PrivateReadEvent<T = unknown> =
    | { type: "retry" }
    | { type: "failed"; message: string }
    | { type: "loaded"; historical: T }
    | { type: "explicit-demo" };

export function privateReadTransition<T>(
    state: PrivateReadState<T>,
    event: PrivateReadEvent<T>,
): PrivateReadState<T> {
    switch (event.type) {
        case "retry":
            return { status: "loading", historical: null };
        case "failed":
            return {
                status: "failure",
                message: event.message,
                historical: null,
            };
        case "loaded":
            return { status: "success", historical: event.historical };
        case "explicit-demo":
            return { status: "demo", historical: state.historical };
    }
}
