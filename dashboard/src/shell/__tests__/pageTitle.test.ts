// The registry first, as in the app: it is what loads every module's index.ts (see core/modules.ts).
import "@/core/modules";

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, ref } from "vue";
import { createMemoryHistory, createRouter, RouterView } from "vue-router";

import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { pageTitleFor, usePageTitle } from "@/lib/usePageTitle";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { json, me } from "@/test/fixtures";

import TopBar from "../TopBar.vue";

const name = ref<string | null>(null);
const ProjectPage = defineComponent({
  setup() {
    usePageTitle(() => name.value);
    return () => h("p", "project page");
  },
});

async function shell(path: string) {
  setActivePinia(createPinia());
  useSessionStore().me = me();
  useCompanyStore().setCurrent(1);
  setLanguage("en");
  mergeModuleMessages("projects", { en: { "projects.title": "Projects", "projects.project.title": "Project" } });
  vi.stubGlobal("fetch", vi.fn(async () => json({})));
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/c/:companyId/projects", component: { render: () => h("p", "list") }, meta: { module: "projects", title: "projects.title" } },
      { path: "/c/:companyId/projects/:projectId/:tab?", component: ProjectPage, meta: { module: "projects", title: "projects.project.title" } },
    ],
  });
  await router.push(path);
  const Host = defineComponent({
    setup: () => () => [h(TopBar, { phone: false, companyless: false, aiAvailable: false, inboxCount: 0, inboxCritical: false }), h(RouterView)],
  });
  const wrapper = mount(Host, { global: { plugins: [router, i18n] }, attachTo: document.body });
  await flushPromises();
  return { router, wrapper };
}

const crumbs = (wrapper: ReturnType<typeof mount>) => wrapper.findAll("nav ol li").map((li) => li.text());

afterEach(() => {
  name.value = null;
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("usePageTitle", () => {
  it("names the last breadcrumb after the record the page shows, and only while that page is open", async () => {
    const { router, wrapper } = await shell("/c/1/projects/5/board");
    // Still loading: the route's own title.
    expect(crumbs(wrapper).at(-1)).toBe("Project");
    name.value = "Yunusobod storage room";
    await flushPromises();
    expect(crumbs(wrapper).at(-1)).toBe("Yunusobod storage room");
    expect(pageTitleFor(router.currentRoute.value)).toBe("Yunusobod storage room");
    // Another tab of the same page keeps it.
    await router.push("/c/1/projects/5/list");
    await flushPromises();
    expect(crumbs(wrapper).at(-1)).toBe("Yunusobod storage room");
    // Another page drops it (and the page's unmount clears it).
    await router.push("/c/1/projects");
    await flushPromises();
    expect(crumbs(wrapper).join(" / ")).not.toContain("Yunusobod");
    expect(pageTitleFor(router.currentRoute.value)).toBeNull();
    wrapper.unmount();
  });
});
