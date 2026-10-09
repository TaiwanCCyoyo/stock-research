import { analyzeComparisons } from "./analysis";
import type { LabCase, Scale } from "./types";

self.onmessage = (event: MessageEvent<{ sample: LabCase; scale: Scale }>) => {
    try {
        self.postMessage({
            results: analyzeComparisons(event.data.sample, event.data.scale),
        });
    } catch (error) {
        self.postMessage({
            error: error instanceof Error ? error.message : "分析未完成",
        });
    }
};
