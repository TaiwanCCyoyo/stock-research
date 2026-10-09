import { layoutCells } from "./geometry";
import type { CellInput, CellLayout } from "./geometry";

type WorkerNode = CellInput & Record<string, unknown>;
type GeometryRequest = {
    requestId: number;
    nodes: WorkerNode[];
    period: string;
};
type GeometryResult = GeometryRequest & { cells: CellLayout[] };
type GeometryError = GeometryRequest & { error: string };

self.addEventListener("message", (event: MessageEvent<GeometryRequest>) => {
    const request = event.data;
    try {
        const result: GeometryResult = {
            ...request,
            cells: layoutCells(request.nodes, 1000, 550),
        };
        self.postMessage(result);
    } catch (caught) {
        const result: GeometryError = {
            ...request,
            error:
                caught instanceof Error
                    ? caught.message
                    : "Unknown geometry calculation error",
        };
        self.postMessage(result);
    }
});
