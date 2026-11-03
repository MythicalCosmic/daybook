// "Are you sure?" without markup: `useConfirm()({ ..., onConfirm })` must run the action once, then
// answer. An `onConfirm` bound next to the host's own `@confirm` used to merge with it into an
// array, so the action never ran and the dialog stayed open.
import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import ConfirmHost from "@/components/ConfirmHost.vue";
import { confirmQueue, requestConfirm } from "@/components/useConfirm";
import { mountWithProviders, testApp } from "@/test/plugins";

function button(label: string): HTMLButtonElement | undefined {
  return [...document.body.querySelectorAll("button")].find((b) => b.textContent?.trim() === label) as HTMLButtonElement | undefined;
}

describe("ConfirmHost", () => {
  afterEach(() => {
    confirmQueue.value = [];
    document.body.innerHTML = "";
  });

  it("runs the request's action once, then answers with the reason", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(ConfirmHost, { plugins: app.plugins });
    const action = vi.fn(async () => undefined);
    const answer = requestConfirm({ title: "Archive the account?", confirmLabel: "Archive", onConfirm: action });
    await flushPromises();
    button("Archive")!.click();
    await flushPromises();
    expect(action).toHaveBeenCalledTimes(1);
    await expect(answer).resolves.toEqual({ reason: "" });
    wrapper.unmount();
  });

  it("stays open and doesn't answer when the action fails", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(ConfirmHost, { plugins: app.plugins });
    const action = vi.fn(async () => {
      throw new Error("refused");
    });
    let settled = false;
    void requestConfirm({ title: "Void it?", confirmLabel: "Void", onConfirm: action }).then(() => (settled = true));
    await flushPromises();
    button("Void")!.click();
    await flushPromises();
    expect(action).toHaveBeenCalledTimes(1);
    expect(settled).toBe(false);
    expect(button("Void")).toBeDefined();
    wrapper.unmount();
  });

  it("answers a request without an action at once", async () => {
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(ConfirmHost, { plugins: app.plugins });
    const answer = requestConfirm({ title: "Delete?", confirmLabel: "Delete" });
    await flushPromises();
    button("Delete")!.click();
    await expect(answer).resolves.toEqual({ reason: "" });
    wrapper.unmount();
  });
});

describe("ConfirmDialog", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("runs its action once, also with a confirm listener", async () => {
    const app = await testApp("/c/1/tasks");
    const action = vi.fn();
    const listener = vi.fn();
    const { wrapper } = mountWithProviders(ConfirmDialog, {
      plugins: app.plugins,
      props: { open: true, title: "Lock the period?", confirmLabel: "Lock", action, onConfirm: listener },
    });
    await flushPromises();
    button("Lock")!.click();
    await flushPromises();
    expect(action).toHaveBeenCalledTimes(1);
    expect(listener).toHaveBeenCalledTimes(1);
    wrapper.unmount();
  });
});
