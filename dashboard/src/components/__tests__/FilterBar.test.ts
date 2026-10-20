import { flushPromises } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { defineComponent, h, ref } from "vue";

import FilterBar from "@/components/FilterBar.vue";
import { activeCount, fromQuery, summarize, toParams, toQuery, useUrlFilters, type FilterDef, type FilterValues } from "@/components/filters";
import { mountWithProviders, testApp } from "@/test/plugins";

const defs: FilterDef[] = [
  {
    key: "status",
    label: "Status",
    type: "multi",
    options: [
      { value: "open", label: "Open" },
      { value: "late", label: "Late" },
      { value: "done", label: "Done" },
    ],
  },
  { key: "assignee", label: "Assignee", type: "select", options: [{ value: "12", label: "Madina" }] },
  { key: "proof", label: "Has proof", type: "boolean" },
  { key: "due", label: "Due", type: "date-range" },
  { key: "period", label: "Period", type: "date-range", params: ["from", "to"] },
  { key: "amount", label: "Amount", type: "number-range" },
  { key: "note", label: "Note", type: "text" },
];

const ctx = {
  yes: "Yes",
  no: "No",
  day: (day: string) => day.slice(5),
  range: (r: { from: string; to: string }) => `${r.from.slice(5)}–${r.to.slice(5)}`,
  number: (v: string) => v,
  more: (n: number) => `+${n}`,
};

describe("filter values and the URL", () => {
  it("reads the query, including repeated and comma lists and range keys", () => {
    const values = fromQuery(defs, { status: ["open", "late"], assignee: "12", proof: "true", due_from: "2026-10-01", from: "2026-10-05", to: "2026-10-09", amount_to: "500000" });
    expect(values).toEqual({
      status: ["open", "late"],
      assignee: "12",
      proof: true,
      due: { from: "2026-10-01", to: null },
      period: { from: "2026-10-05", to: "2026-10-09" },
      amount: { from: null, to: "500000" },
      note: null,
    });
    expect(fromQuery(defs, { status: "open,done" }).status).toEqual(["open", "done"]);
    expect(fromQuery(defs, { proof: "0" }).proof).toBe(false);
  });

  it("writes query keys that are also the API params, removing empty ones", () => {
    const values: FilterValues = { status: ["late"], assignee: null, proof: false, due: { from: null, to: "2026-10-31" }, note: "" };
    expect(toQuery(defs, values)).toEqual({
      status: ["late"],
      assignee: undefined,
      proof: "false",
      due_from: undefined,
      due_to: "2026-10-31",
      from: undefined,
      to: undefined,
      amount_from: undefined,
      amount_to: undefined,
      note: undefined,
    });
    expect(toParams(defs, values)).toEqual({ status: ["late"], proof: "false", due_to: "2026-10-31" });
    expect(activeCount(defs, values)).toBe(3);
  });

  it("round-trips", () => {
    const values = fromQuery(defs, { status: ["open"], from: "2026-10-01", to: "2026-10-20", note: "fridge" });
    expect(fromQuery(defs, toQuery(defs, values) as Record<string, string | string[]>)).toEqual(values);
  });

  it("summarizes chips", () => {
    expect(summarize(defs[0]!, ["open", "late", "done"], ctx)).toBe("Open, Late +1");
    expect(summarize(defs[1]!, "12", ctx)).toBe("Madina");
    expect(summarize(defs[2]!, false, ctx)).toBe("No");
    expect(summarize(defs[3]!, { from: "2026-10-01", to: "2026-10-09" }, ctx)).toBe("10-01–10-09");
    expect(summarize(defs[3]!, { from: null, to: "2026-10-09" }, ctx)).toBe("≤ 10-09");
    expect(summarize(defs[5]!, { from: "100", to: null }, ctx)).toBe("≥ 100");
    expect(summarize(defs[0]!, [], ctx)).toBe("");
  });

  it("binds to the route", async () => {
    const app = await testApp("/c/1/tasks?status=open&view=board");
    let filters!: ReturnType<typeof useUrlFilters>;
    const Host = defineComponent({
      setup() {
        filters = useUrlFilters(defs);
        return () => h("div");
      },
    });
    mountWithProviders(Host, { plugins: app.plugins });
    expect(filters.values.value.status).toEqual(["open"]);
    filters.values.value = { ...filters.values.value, status: ["open", "late"], proof: true };
    await flushPromises();
    expect(app.router.currentRoute.value.query).toEqual({ status: ["open", "late"], proof: "true", view: "board" });
    expect(filters.params.value).toEqual({ status: ["open", "late"], proof: "true" });
    filters.clear();
    await flushPromises();
    expect(app.router.currentRoute.value.query).toEqual({ view: "board" });
  });
});

describe("FilterBar", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  async function bar(values: FilterValues) {
    const app = await testApp("/c/1/tasks");
    const model = ref(values);
    const Host = defineComponent({
      setup: () => () => h(FilterBar, { defs, modelValue: model.value, "onUpdate:modelValue": (next: FilterValues) => (model.value = next) }),
    });
    const { wrapper } = mountWithProviders(Host, { plugins: app.plugins });
    await flushPromises();
    return { wrapper, model };
  }

  it("shows a chip per active filter with its summary", async () => {
    const { wrapper } = await bar({ status: ["open", "late"], proof: true });
    expect(wrapper.text()).toContain("StatusOpen, Late");
    expect(wrapper.text()).toContain("Has proofYes");
    expect(wrapper.text()).not.toContain("Assignee");
    expect(wrapper.text()).toContain("Clear filters");
  });

  it("removes one filter and clears them all", async () => {
    const { wrapper, model } = await bar({ status: ["open"], proof: true, note: "x" });
    await wrapper.get('[aria-label="Remove the filter “Status”"]').trigger("click");
    expect(model.value.status).toEqual([]);
    expect(model.value.proof).toBe(true);
    await wrapper.findAll("button").find((b) => b.text() === "Clear filters")!.trigger("click");
    expect(Object.values(model.value).every((v) => v === null || (Array.isArray(v) && !v.length))).toBe(true);
  });

  it("edits a boolean filter from its chip", async () => {
    const { wrapper, model } = await bar({ proof: true });
    await wrapper.findAll("button").find((b) => b.text().startsWith("Has proof"))!.trigger("click");
    await flushPromises();
    const no = [...document.body.querySelectorAll<HTMLButtonElement>("[role=radio]")].find((el) => el.textContent?.trim() === "No")!;
    no.click();
    await flushPromises();
    expect(model.value.proof).toBe(false);
  });
});
