import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Studio from "./app/Studio.tsx";

const root = createRoot(document.getElementById("root")!);
if (new URLSearchParams(location.search).get("legacy") === "1") {
    Promise.all([import("./App.tsx"), import("./index.css")]).then(
        ([{ default: App }]) =>
            root.render(
                <StrictMode>
                    <App />
                </StrictMode>,
            ),
    );
} else {
    root.render(
        <StrictMode>
            <Studio />
        </StrictMode>,
    );
}
