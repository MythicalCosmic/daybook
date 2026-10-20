import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h, nextTick } from "vue";

import DataTable from "@/components/DataTable.vue";
import type { TableColumn } from "@/components/table";
import { directionOf, nextOrdering, useDataTable, type DataTableState } from "@/components/useDataTable";
import { mountWithProviders, testApp, type TestApp } from "@/test/plugins";

interface Row {
  id: number;
  name: string;
  amount: string;
}

const rows = (n: number, offset = 0): Row[] =>
  Array.from({ length: n }, (_, i) => ({ id: offset + i + 1, name: `Person ${offset + i + 1}`, amount: `${(offset + i + 1) * 1000}.00` }));

const columns: TableColumn<Row>[] = [
  { id: "name", header: "Name", sortable: true, hideable: false },
  { id: "amount", header: "Amount", sortable: "total_amount", numeric: true },
  { id: "note", header: "Note", value: () => null },
];

let app: TestApp;

beforeEach(async () => {
  localStorage.clear();
  app = await testApp("/c/1/finance/transactions");
});

afterEach(() => {
  document.body.innerHTML = "";
});

/** Runs useDataTable inside a component so the URL-bound refs have a router. */
async function withState(options: Parameters<typeof useDataTable>[0]): Promise<DataTableState> {
  let state!: DataTableState;
  const Host = defineComponent({
    setup() {
      state = useDataTable(options);
      return () => h("div");
    },
  });
  mount(Host, { global: { plugins: app.plugins } });
  await flushPromises();
  return state;
}

describe("ordering", () => {
  it("cycles ascending → descending → default", () => {
    expect(nextOrdering("", "name", "")).toBe("name");
    expect(nextOrdering("name", "name", "")).toBe("-name");
    expect(nextOrdering("-name", "name", "")).toBe("");
    expect(nextOrdering("-name", "amount", "-date")).toBe("amount");
  });

  it("never stalls on the default descending column", () => {
    expect(nextOrdering("-date", "date", "-date")).toBe("date");
    expect(nextOrdering("date", "date", "-date")).toBe("-date");
  });

  it("reads the direction of the first ordering field", () => {
    expect(directionOf("-date,name", "date")).toBe("desc");
    expect(directionOf("name", "name")).toBe("asc");
    expect(directionOf("name", "date")).toBeNull();
  });
});

describe("useDataTable", () => {
  it("builds the API params and resets to page 1 when sorting", async () => {
    const state = await withState({ pageSize: 25, ordering: "-date" });
    expect(state.params.value).toEqual({ page: 1, page_size: 25, ordering: "-date" });
    state.page.value = 3;
    state.toggleSort("amount");
    expect(state.params.value).toEqual({ page: 1, page_size: 25, ordering: "amount" });
  });

  it("keeps page, size and ordering in the URL when asked", async () => {
    const state = await withState({ url: true, ordering: "-date", pageSize: 50 });
    state.page.value = 2;
    state.ordering.value = "name";
    await flushPromises();
    expect(app.router.currentRoute.value.query).toEqual({ page: "2", ordering: "name" });
    state.ordering.value = "-date";
    state.page.value = 1;
    await flushPromises();
    expect(app.router.currentRoute.value.query).toEqual({});
  });

  it("remembers hidden columns per table id", async () => {
    const first = await withState({ id: "finance.transactions", hidden: ["note"] });
    expect(first.isColumnVisible("note")).toBe(false);
    first.setColumnVisible("note", true);
    first.setColumnVisible("amount", false);
    const second = await withState({ id: "finance.transactions", hidden: ["note"] });
    expect(second.hiddenColumns.value).toEqual(["amount"]);
    second.resetColumns();
    expect(second.hiddenColumns.value).toEqual(["note"]);
  });

  it("keeps the selection across pages", async () => {
    const state = await withState({});
    state.setRows(["1", "2", "3"], true);
    state.page.value = 2;
    state.toggleRow("51");
    state.toggleRow("2");
    expect(state.selectedIds.value.sort()).toEqual(["1", "3", "51"]);
    state.clearSelection();
    expect(state.selectedIds.value).toEqual([]);
  });
});

describe("DataTable", () => {
  async function render(props: Record<string, unknown> = {}, slots: Record<string, unknown> = {}) {
    const state = await withState({ ordering: "", pageSize: 50 });
    const { wrapper: host, inner } = mountWithProviders(DataTable, {
      props: { state, columns, rows: rows(3), rowKey: "id", total: 3, ...props },
      slots,
      plugins: app.plugins,
    });
    await flushPromises();
    return { state, wrapper: inner, host };
  }

  it("renders rows, empty cells as a dash, and the range", async () => {
    const { wrapper } = await render();
    const body = wrapper.findAll("tbody tr");
    expect(body).toHaveLength(3);
    expect(body[0]!.text()).toContain("Person 1");
    expect(body[0]!.text()).toContain("—");
    expect(wrapper.text()).toContain("1–3 of 3");
  });

  it("sorts from the header with aria-sort", async () => {
    const { wrapper, state } = await render();
    const header = wrapper.findAll("thead th")[1]!;
    expect(header.attributes("aria-sort")).toBe("none");
    await header.get("button").trigger("click");
    expect(state.ordering.value).toBe("total_amount");
    await nextTick();
    expect(wrapper.findAll("thead th")[1]!.attributes("aria-sort")).toBe("ascending");
  });

  it("uses custom cell slots", async () => {
    const { wrapper } = await render({}, { "cell-amount": ({ row }: { row: Row }) => h("b", { class: "money" }, row.amount) });
    expect(wrapper.findAll(".money").map((el) => el.text())).toEqual(["1000.00", "2000.00", "3000.00"]);
  });

  it("selects the page from the header checkbox and shows the bulk bar", async () => {
    const { wrapper, state } = await render({ selectable: true }, { bulk: () => h("button", { class: "approve-all" }, "Approve") });
    await wrapper.get("thead [role=checkbox]").trigger("click");
    expect(state.selectedIds.value.sort()).toEqual(["1", "2", "3"]);
    await nextTick();
    expect(document.body.querySelector("[role=toolbar]")?.textContent).toContain("3 selected");
    expect(document.body.querySelector(".approve-all")).not.toBeNull();
  });

  it("opens a row with Enter and moves with the arrow keys", async () => {
    const { wrapper } = await render({ clickable: true });
    const first = wrapper.findAll("tbody tr")[0]!;
    (first.element as HTMLElement).focus();
    await first.trigger("keydown", { key: "ArrowDown" });
    expect(document.activeElement).toBe(wrapper.findAll("tbody tr")[1]!.element);
    await wrapper.findAll("tbody tr")[1]!.trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("row-click")?.[0]?.[0]).toMatchObject({ id: 2 });
  });

  it("virtualizes long pages", async () => {
    // jsdom has no layout: give the scroller a viewport of 600 px.
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(600);
    vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(1000);
    const { wrapper } = await render({ rows: rows(200), total: 200 });
    const rendered = wrapper.findAll("tbody tr[data-row-key]").length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(200);
  });

  it("says when filters match nothing and offers to clear them", async () => {
    const { wrapper } = await render({ rows: [], total: 0, filtered: true });
    expect(wrapper.text()).toContain("Nothing matches these filters");
    await wrapper.findAll("button").find((b) => b.text() === "Clear filters")!.trigger("click");
    expect(wrapper.emitted("clear-filters")).toHaveLength(1);
  });
});
