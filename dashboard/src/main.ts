import "@fontsource-variable/figtree";
import "@fontsource/caprasimo/400.css";
import "./styles/fonts.css";
import "./styles/index.css";
import "./core/edition.css";

import { createApp } from "vue";

import App from "./app/App.vue";
import { installProviders } from "./app/providers";
import { createAppRouter } from "./app/router";
import { applyBrand } from "./core/brand";
import { DAYBOOK_INFO, loadEdition, rememberedEdition } from "./core/edition";
import { applyEdition, registerDevModules, type DashboardModule } from "./core/modules";
import { endForgottenSession } from "./core/remember";
import { currentLanguage, isLanguage, loadLanguage, setLanguage } from "./i18n";
import { readStored } from "./lib/storage";
import { bindTelegram, detectTelegram } from "./shell/TelegramBridge";

async function start(): Promise<void> {
  // The shell's strings in this browser's language load alongside everything below (the account's
  // language, if different, follows when `me` arrives). A failed load still mounts the app.
  let strings = loadLanguage(currentLanguage()).catch(() => undefined);
  // Development only: serve the API from demo data and show placeholder modules for packages that
  // haven't landed. `import.meta.env.DEV` is false in a build, so none of this ships.
  let stubs: DashboardModule[] | null = null;
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") {
    const [{ installMock }, { devStubModules }] = await Promise.all([import("./dev/mock"), import("./dev/stubModules")]);
    installMock();
    stubs = devStubModules();
  }

  // The edition comes first (core/edition.ts): only its modules are registered, so the router,
  // the sidebar and the dictionaries below are built from them. A browser that already knows this
  // server is Daybook doesn't wait for the answer (Daybook starts as fast as before); should the
  // server say otherwise, the page starts again in that edition.
  const asking = loadEdition();
  const knownDaybook = rememberedEdition() === "daybook";
  const [info] = await Promise.all([knownDaybook ? Promise.resolve(DAYBOOK_INFO) : asking, detectTelegram()]);
  if (knownDaybook) void asking.then((answer) => answer.edition !== "daybook" && window.location.reload());
  applyEdition(info.edition);
  if (stubs && info.edition === "daybook") registerDevModules(stubs);
  applyBrand();
  if (info.edition === "davomat") {
    // Before anyone chose a language in this browser, the organization's language.
    const chosen = readStored<string | null>("language", null);
    if (!isLanguage(chosen) && info.default_language !== currentLanguage()) strings = setLanguage(info.default_language).catch(() => undefined);
    // "Remember me" was unticked and the browser closed since: start signed out.
    await endForgottenSession();
  }

  const app = createApp(App);
  const router = createAppRouter();
  // Development only: the component kitchen at /dashboard/_kitchen (plan §6.3), W0-D's visual acceptance test.
  if (import.meta.env.DEV) {
    router.addRoute({ path: "/_kitchen", name: "kitchen", component: () => import("./dev/Kitchen.vue"), meta: { public: true, title: "dev.kitchen.title" } });
    // An agent's room in every state (?variant=hr&state=working|idle|asleep&night=1&theme=dark).
    router.addRoute({ path: "/_scene", name: "scene-lab", component: () => import("./dev/SceneLab.vue"), meta: { public: true, title: "dev.kitchen.title" } });
  }
  installProviders(app, router);
  app.use(router);
  bindTelegram(router);
  await Promise.all([router.isReady(), strings]);
  app.mount("#app");
}

void start();
