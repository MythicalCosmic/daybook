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

  it("shows fields in the order the page gives, not Postgres' shortest-key-first order", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: 5,
              created_at: "2026-10-21T05:00:00Z",
              action: "timeoff.recorded",
              action_label: "Recorded time off",
              actor: { id: 11, name: "Dilnoza Karimova" },
              target_type: "timeoff",
              target_id: 3,
              target: "Time off",
              // As jsonb returns them: keys sorted by length.
              details: { member: "Bekzod Mirzayev", last_day: "2026-10-24", first_day: "2026-10-22", changes: { last_day: ["2026-10-23", "2026-10-24"], first_day: ["2026-10-21", "2026-10-22"] } },
            },
          ],
        }),
      ),
    );
    const app = await testApp("/c/1/time-off");
    const labels = { member: "Person", first_day: "First day", last_day: "Last day" };
    const { wrapper } = mountWithProviders(AuditTrail, { plugins: app.plugins, props: { targetType: "timeoff", targetId: 3, fieldLabels: labels, fieldOrder: ["member", "first_day", "last_day"] } });
    await flushPromises();
    const fields = (w: typeof wrapper) => w.findAll("li > span.text-xs.font-semibold").map((span) => span.text());
    const rows = fields(wrapper);
    // Changes first (first day, then last day), then the plain details in the same order.
    expect(rows).toEqual(["First day", "Last day", "Person", "First day", "Last day"]);
    const unordered = mountWithProviders(AuditTrail, { plugins: app.plugins, props: { targetType: "timeoff", targetId: 3, fieldLabels: labels } });
    await flushPromises();
    expect(fields(unordered.wrapper)).toEqual(["Last day", "First day", "Person", "Last day", "First day"]);
  });
});
