/**
 * The kitchen: every shared building block in src/ui on one page, for the polish pass, feature
 * engineers and screenshots. Dev server only (`/app/kitchen.html?lang=uz&theme=dark`); the
 * production build bundles index.html alone. Section titles are for developers (English); the
 * sample content comes in all three languages so the primitives can be checked in each.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../styles/tokens.css";
import "../styles/app.css";
import "../ui/ui.css";
import "./kitchen.css";

import { asLang, I18nProvider } from "../i18n";
import { ToastProvider } from "../state/toast";
import { Kitchen } from "./Kitchen";

const params = new URLSearchParams(window.location.search);
document.documentElement.dataset.theme = params.get("theme") === "dark" ? "dark" : "light";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider lang={asLang(params.get("lang") ?? "en")}>
      <ToastProvider>
        <Kitchen section={params.get("section")} />
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
);
