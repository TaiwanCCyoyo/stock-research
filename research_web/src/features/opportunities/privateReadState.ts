export type PrivateReadState =
    | { status: "loading" }
    | { status: "failure"; message: string }
    | { status: "success" }
    | { status: "demo" };

export type PrivateReadEvent =
    | { type: "retry" }
    | { type: "failed"; message: string }
    | { type: "loaded" }
    | { type: "explicit-demo" };

export function privateReadTransition(
    _state: PrivateReadState,
    event: PrivateReadEvent,
): PrivateReadState {
    switch (event.type) {
        case "retry":
            return { status: "loading" };
        case "failed":
            return { status: "failure", message: event.message };
        case "loaded":
            return { status: "success" };
        case "explicit-demo":
            return { status: "demo" };
    }
}
