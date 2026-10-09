import { computePacking } from "./packing";
import type { PackingInput, PackingLayout } from "./packing";

export type PackingRequest = {
    requestId: number;
    date: string;
    input: PackingInput;
};
export type PackingResponse = { requestId: number; date: string } & (
    { layout: PackingLayout } | { error: string }
);

self.addEventListener("message", (event: MessageEvent<PackingRequest>) => {
    const { requestId, date, input } = event.data;
    let response: PackingResponse;
    try {
        response = { requestId, date, layout: computePacking(input) };
    } catch (error) {
        response = {
            requestId,
            date,
            error: error instanceof Error ? error.message : "Packing failed",
        };
    }
    self.postMessage(response);
});
