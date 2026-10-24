import { createElement } from "react";

/** Warnings stay beside the summary, never only inside a collapsed section. */
export function StudyCaveats({ caveats }: { caveats: readonly string[] }) {
    if (!caveats.length) return null;
    return createElement(
        "p",
        { className: "st-caveats", role: "note" },
        ...caveats.map((text) =>
            createElement("span", { key: text, className: "st-caveat" }, text),
        ),
    );
}
