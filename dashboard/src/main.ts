import "@fontsource-variable/figtree";
import "@fontsource/caprasimo/400.css";
import "./styles/index.css";

import { createApp } from "vue";

import App from "./app/App.vue";
import { installProviders } from "./app/providers";
import { createAppRouter } from "./app/router";
import { registerDevModules } from "./core/modules";
import { bindTelegram, detectTelegram } from "./shell/TelegramBridge";

async function start(): Promise<void> {
  // Development only: serve the API from demo data and show placeholder modules for packages that
  // haven't landed. `import.meta.env.DEV` is false in a build, so none of this ships.
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === "1") {
    const [{ installMock }, { devStubModules }] = await Promise.all([import("./dev/mock"), import("./dev/stubModules")]);
    installMock();
    registerDevModules(devStubModules());
  }

  await detectTelegram();
  const app = createApp(App);
  const router = createAppRouter();
  // Development only: the component kitchen at /dashboard/_kitchen (plan §6.3), W0-D's visual acceptance test.
  if (import.meta.env.DEV) {
    router.addRoute({ path: "/_kitchen", name: "kitchen", component: () => import("./dev/Kitchen.vue"), meta: { public: true, title: "dev.kitchen.title" } });
  }
  installProviders(app, router);
  app.use(router);
  bindTelegram(router);
  await router.isReady();
  app.mount("#app");
}

void start();
