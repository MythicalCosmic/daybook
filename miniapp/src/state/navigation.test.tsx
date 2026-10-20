import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  CORE,
  initialNavigation,
  NavigationProvider,
  openLegacyPage,
  openTaskId,
  reduceNavigation,
  taskPage,
  useNavigation,
  type Navigation,
  type NavigationAction,
  type NavigationState,
} from "./navigation";

const run = (actions: NavigationAction[], start: NavigationState = initialNavigation()) =>
  actions.reduce(reduceNavigation, start);

const wallet = { feature: "wallet", page: "payslip", params: { id: 12 } };

describe("navigation stack", () => {
  it("starts on Home with nothing open", () => {
    expect(initialNavigation()).toEqual({ tab: "home", tasksTab: "daily", stack: [], sheet: null });
  });

  it("pushes, pops and replaces pages, closing any sheet on the way in", () => {
    const opened = run([{ type: "sheet", sheet: { kind: "add" } }, { type: "push", page: wallet }]);
    expect(opened.stack).toEqual([wallet]);
    expect(opened.sheet).toBeNull();

    const deeper = run([{ type: "push", page: { feature: "wallet", page: "advance" } }], opened);
    expect(deeper.stack.map((ref) => ref.page)).toEqual(["payslip", "advance"]);

    const replaced = run([{ type: "replace", page: { feature: "wallet", page: "home" } }], deeper);
    expect(replaced.stack.map((ref) => ref.page)).toEqual(["payslip", "home"]);

    expect(run([{ type: "pop" }, { type: "pop" }, { type: "pop" }], replaced).stack).toEqual([]);
  });

  it("doesn't stack the same page twice", () => {
    const state = run([{ type: "push", page: wallet }, { type: "push", page: { ...wallet, params: { id: "12" } } }]);
    expect(state.stack).toHaveLength(1);
  });

  it("starts fresh on a tab switch, keeping the tasks tab unless one is given", () => {
    const busy = run([{ type: "tasksTab", tasksTab: "review" }, { type: "push", page: wallet }, { type: "sheet", sheet: { kind: "language" } }]);
    const switched = run([{ type: "tab", tab: "profile" }], busy);
    expect(switched).toEqual({ tab: "profile", tasksTab: "review", stack: [], sheet: null });
    expect(run([{ type: "tab", tab: "tasks", tasksTab: "personal" }], busy).tasksTab).toBe("personal");
  });

  it("keeps one task open at a time, as before the stack", () => {
    const state = run([{ type: "openTask", taskId: 5 }, { type: "openTask", taskId: 7 }]);
    expect(state.stack).toEqual([taskPage(7)]);
    expect(openTaskId(state.stack)).toBe(7);
  });

  it("closes the task and anything opened from it", () => {
    const state = run([
      { type: "openPage", page: "team" },
      { type: "openTask", taskId: 3 },
      { type: "push", page: wallet },
      { type: "closeTask" },
    ]);
    expect(state.stack).toEqual([{ feature: CORE, page: "team" }]);
    expect(openLegacyPage(state.stack)).toBe("team");
    expect(openTaskId(state.stack)).toBeNull();
    expect(run([{ type: "closePage" }], state).stack).toEqual([]);
  });

  it("leaves the sheet alone when closing a task, like the original", () => {
    const state = run([{ type: "openTask", taskId: 3 }, { type: "sheet", sheet: { kind: "complete", taskId: 3 } }, { type: "closeTask" }]);
    expect(state.sheet).toEqual({ kind: "complete", taskId: 3 });
  });

  it("starts from a deep link and resets to one", () => {
    const start = initialNavigation({ tab: "profile", stack: [wallet] });
    expect(start).toEqual({ tab: "profile", tasksTab: "daily", stack: [wallet], sheet: null });
    expect(run([{ type: "reset", init: { tab: "tasks", tasksTab: "review" } }], start)).toEqual({
      tab: "tasks",
      tasksTab: "review",
      stack: [],
      sheet: null,
    });
  });
});

describe("NavigationProvider", () => {
  afterEach(cleanup);

  function mount(initial?: Parameters<typeof NavigationProvider>[0]["initial"]) {
    const current: { value: Navigation | null } = { value: null };
    function Probe() {
      current.value = useNavigation();
      return null;
    }
    render(
      <NavigationProvider initial={initial}>
        <Probe />
      </NavigationProvider>,
    );
    return () => current.value!;
  }

  it("keeps every call the screens used before the stack", () => {
    const nav = mount();
    act(() => nav().goTo("tasks", "assigned"));
    expect([nav().tab, nav().tasksTab]).toEqual(["tasks", "assigned"]);
    act(() => nav().setTasksTab("personal"));
    expect(nav().tasksTab).toBe("personal");

    act(() => nav().openPage("team"));
    expect(nav().page).toBe("team");
    act(() => nav().openTask(42));
    expect([nav().page, nav().taskId]).toEqual(["team", 42]);
    act(() => nav().openSheet({ kind: "return", taskId: 42 }));
    expect(nav().sheet).toEqual({ kind: "return", taskId: 42 });
    act(() => nav().closeSheet());
    act(() => nav().closeTask());
    expect([nav().page, nav().taskId]).toEqual(["team", null]);
    act(() => nav().closePage());
    expect(nav().page).toBeNull();
    expect(nav().stack).toEqual([]);
  });

  it("goes back like Telegram's back button: the sheet, then the top page, then nothing", () => {
    const nav = mount({ stack: [wallet] });
    expect(nav().top).toEqual(wallet);
    act(() => nav().openSheet({ kind: "feature", feature: "wallet", sheet: "advance" }));

    let handled = false;
    act(() => {
      handled = nav().back();
    });
    expect(handled).toBe(true);
    expect(nav().sheet).toBeNull();
    expect(nav().stack).toEqual([wallet]);

    act(() => {
      handled = nav().back();
    });
    expect(handled).toBe(true);
    expect(nav().stack).toEqual([]);

    act(() => {
      handled = nav().back();
    });
    expect(handled).toBe(false);
  });
});
