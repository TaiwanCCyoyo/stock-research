import "../../../discussion-kit/v1/discussion.js";
import { interactiveModel, type DirectionDetail } from "./model.ts";

export interface DiscussionKit {
    validateModel(model: unknown): unknown;
    createSession(model: unknown): {
        setNotes(notes: string): void;
        exportFeedback(): unknown;
    };
    mount(
        root: HTMLElement,
        model: unknown,
        initialFeedback?: unknown,
    ): { destroy(): void; exportFeedback(): unknown };
}
declare global {
    var DirectionDiscussion: DiscussionKit;
}

/** React owns the root; the shared renderer owns only this mount's children/listeners. */
export function attachDiscussion(
    root: HTMLElement,
    detail: DirectionDetail,
    kit: DiscussionKit = globalThis.DirectionDiscussion,
    initialFeedback?: unknown,
): () => void {
    const model = interactiveModel(detail);
    kit.validateModel(model);
    const view = kit.mount(root, model, initialFeedback);
    return () => view.destroy();
}
