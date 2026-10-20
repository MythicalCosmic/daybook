/** Plugins a component test needs: pinia with a signed-in owner in Demo Shop, a memory router, i18n in English, vue-query. */
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import { TooltipProvider } from "reka-ui";
import { defineComponent, h, type Component, type Plugin } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { i18n, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";

import { me } from "./fixtures";

export interface TestApp {
  pinia: Pinia;
  router: Router;
  client: QueryClient;
  plugins: Array<Plugin | [Plugin, ...unknown[]]>;
}

/**
 * Mounts a component inside reka-ui's TooltipProvider (App.vue provides it in the app), returning
 * the outer wrapper and the component's own wrapper (props, emitted events).
 */
export function mountWithProviders(
  component: object,
  options: { props?: Record<string, unknown>; slots?: Record<string, unknown>; plugins: TestApp["plugins"]; attach?: boolean },
) {
  const Host = defineComponent({
    setup: () => () => h(TooltipProvider, null, { default: () => h(component as Component, options.props ?? {}, options.slots ?? {}) }),
  });
  const wrapper = mount(Host, { global: { plugins: options.plugins }, attachTo: options.attach === false ? undefined : document.body });
  return { wrapper, inner: wrapper.findComponent(component as never) as VueWrapper };
}

export async function testApp(path = "/c/1/tasks", language: "uz" | "ru" | "en" = "en"): Promise<TestApp> {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me();
  useCompanyStore().setCurrent(1);
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
  await router.push(path);
  setLanguage(language);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { pinia, router, client, plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] };
}
