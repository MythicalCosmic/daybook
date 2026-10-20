import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";

import { applyQueryPatch, patchQuery, rs, useRouteState, useRouteStates } from "@/lib/useRouteState";

function makeRouter(): Router {
  return createRouter({ history: createMemoryHistory(), routes: [{ path: "/:any(.*)*", component: { render: () => null } }] });
}

const flush = async () => {
  await Promise.resolve();
  await nextTick();
  await new Promise((resolve) => setTimeout(resolve, 0));
};

describe("codecs", () => {
  it("parse and drop defaults from the URL", () => {
    expect(rs.string("all").parse(undefined)).toBe("all");
    expect(rs.string("all").serialize("all")).toBeUndefined();
    expect(rs.number(1).parse("3")).toBe(3);
    expect(rs.number(1).parse("x")).toBe(1);
    expect(rs.number(1).serialize(1)).toBeUndefined();
    expect(rs.optionalNumber().parse("")).toBeNull();
    expect(rs.boolean().parse("1")).toBe(true);
    expect(rs.boolean(true).serialize(false)).toBe("0");
    expect(rs.enum(["table", "board"] as const, "table").parse("board")).toBe("board");
    expect(rs.enum(["table", "board"] as const, "table").parse("calendar")).toBe("table");
    expect(rs.list().parse(["a", "b,c"])).toEqual(["a", "b", "c"]);
    expect(rs.numberList().parse("1,2,x")).toEqual([1, 2]);
    expect(rs.numberList().serialize([])).toBeUndefined();
    expect(rs.day().parse("2026-10-20")).toBe("2026-10-20");
    expect(rs.day().parse("20.10.2026")).toBeNull();
  });

  it("patches a query", () => {
    expect(applyQueryPatch({ a: "1", b: "2" }, { a: undefined, c: ["x", "y"] })).toEqual({ b: "2", c: ["x", "y"] });
  });
});

describe("useRouteState", () => {
  it("binds a ref to the URL and batches writes in one navigation", async () => {
    const router = makeRouter();
    await router.push("/tasks?status=late");
    let refs: ReturnType<typeof setup> | undefined;
    const setup = () => ({
      status: useRouteState("status", rs.enum(["open", "late", "done"] as const, "open")),
      page: useRouteState("page", rs.number(1)),
      states: useRouteStates({ branch: rs.numberList(), q: rs.string() }),
    });
    const Probe = defineComponent({
      setup() {
        refs = setup();
        return () => h("div");
      },
    });
    mount(Probe, { global: { plugins: [router] } });
    expect(refs!.status.value).toBe("late");
    expect(refs!.page.value).toBe(1);

    let navigations = 0;
    router.afterEach(() => navigations++);
    refs!.status.value = "done";
    refs!.page.value = 3;
    refs!.states.branch.value = [2, 5];
    await flush();
    expect(navigations).toBe(1);
    expect(router.currentRoute.value.query).toEqual({ status: "done", page: "3", branch: ["2", "5"] });

    refs!.states.q.value = "fridge";
    await flush();
    refs!.states.reset();
    refs!.status.value = "open";
    await flush();
    expect(router.currentRoute.value.query).toEqual({ page: "3" });
  });

  it("can push history entries (drawers)", async () => {
    const router = makeRouter();
    await router.push("/tasks");
    patchQuery(router, { task: "345" }, true);
    await flush();
    expect(router.currentRoute.value.fullPath).toBe("/tasks?task=345");
    router.back();
    await flush();
  });
});
