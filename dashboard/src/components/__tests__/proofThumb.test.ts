/** A proof thumbnail mounts its lightbox only while it is open: the photo wall shows up to 300. */
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { describe, expect, it } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import ImageLightbox from "@/components/ImageLightbox.vue";
import ProofThumb from "@/components/ProofThumb.vue";
import { i18n, setLanguage } from "@/i18n";

describe("ProofThumb", () => {
  it("mounts its lightbox only when opened", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    setLanguage("en");
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
    const thumb = mount(ProofThumb, { props: { src: "/media/proof.jpg", alt: "Fridge" }, global: { plugins: [pinia, router, i18n] }, attachTo: document.body });
    await thumb.find("img").trigger("load");
    expect(thumb.findComponent(ImageLightbox).exists()).toBe(false);
    await thumb.find("button").trigger("click");
    await flushPromises();
    expect(thumb.findComponent(ImageLightbox).exists()).toBe(true);
    thumb.unmount();
  });
});
