import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuditTrail from "@/components/AuditTrail.vue";
import { json } from "@/test/fixtures";
import { mountWithProviders, testApp } from "@/test/plugins";

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("AuditTrail", () => {
  it("reads audit/records/ rows as the backend sends them: changes, secrets, reasons and other details", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return json({
          count: 2,
          next: null,
          previous: null,
          results: [
            {
              id: 2,
              created_at: "2026-10-21T05:00:00Z",
              action: "task.changed",
              action_label: "Changed a task",
              actor: { id: 11, name: "Dilnoza Karimova" },
              target_type: "task",
              target_id: 9,
              target: "Fridge check",
              details: { changes: { due_at: ["2026-10-21T09:00:00", "2026-10-22T09:00:00"], card_number: ["•••", "•••"], priority: [null, "high"] }, reason: "Supplier is late" },
            },
            { id: 1, created_at: "2026-10-20T05:00:00Z", action: "task.assigned", action_label: "Gave a task", actor: null, target_type: "task", target_id: 9, target: "Fridge check", details: { branch: "Chilonzor", urgent: true } },
          ],
        });
      }),
    );
    const app = await testApp("/c/1/tasks");
    const { wrapper } = mountWithProviders(AuditTrail, { plugins: app.plugins, props: { targetType: "task", targetId: 9, fieldLabels: { due_at: "Due" } } });
    await flushPromises();
    expect(calls[0]).toBe("/api/v1/owner/companies/1/audit/records/?target_type=task&target_id=9&page=1&page_size=30");
    const text = wrapper.text();
    expect(text).toContain("Dilnoza Karimova");
    expect(text).toContain("Changed a task");
    expect(text).toContain("Supplier is late");
    // Labels from the page, or the field name made readable.
    expect(text).toContain("Due");
    expect(text).toContain("Card number");
    expect(text).toContain("hidden");
    expect(text).not.toContain("•••");
    expect(text).toContain("empty");
    expect(text).toContain("high");
    // A system row and its plain details.
    expect(text).toContain("System");
    expect(text).toContain("Chilonzor");
    expect(text).toContain("Yes");
  });
});
