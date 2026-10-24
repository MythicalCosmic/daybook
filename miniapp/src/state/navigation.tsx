import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";

/**
 * Where the person is in the app: a tab, a stack of pages over it, and at most one sheet.
 *
 * Pages are `PageRef`s: `{feature, page, params}`. The app's own pages use the feature "core"
 * (`task` with `{id}`, `team`); feature folders push their own (`{feature: "wallet", page:
 * "payslip", params: {id: 12}}`). The original calls (`goTo`, `openTask`, `openPage`,
 * `openSheet` and their closers) work on top of the stack exactly as before. Telegram's back
 * button closes the sheet first, then pops the stack.
 */

export type Tab = "home" | "tasks" | "activity" | "profile";
/** "given": work I gave others (for whoever hands out work). */
export type TasksTab = "daily" | "assigned" | "personal" | "review" | "given";
/** The app's own full-screen pages opened from a tab, like the team results. */
export type Page = "team";

export type Params = Record<string, string | number>;
export type PageRef = { feature: string; page: string; params?: Params };

/** The feature name of the app's built-in pages. */
export const CORE = "core";

export type Sheet =
  | { kind: "complete"; taskId: number }
  | { kind: "return"; taskId: number }
  /** Reminders later: 15 min, 1 h, or (my own task) tomorrow morning. */
  | { kind: "snooze"; taskId: number }
  /** "Can't do it", with a reason. */
  | { kind: "blocker"; taskId: number }
  /** "Need more time": ask the giver for a later deadline. */
  | { kind: "extension"; taskId: number }
  /** The giver hands blocked work to someone else. */
  | { kind: "reassign"; taskId: number }
  /** A new deadline: my own change, or the giver's answer to a blocker (`resolve`). */
  | { kind: "due"; taskId: number; resolve?: boolean }
  | { kind: "edit"; taskId: number }
  /** Edit, reschedule, delete: what `task.actions` allows. */
  | { kind: "taskMenu"; taskId: number }
  | { kind: "add" }
  | { kind: "language" }
  | { kind: "company" }
  | { kind: "timeOff" }
  /** A sheet a feature folder registered under `sheets`. */
  | { kind: "feature"; feature: string; sheet: string; params?: Params };

export type NavigationState = {
  tab: Tab;
  tasksTab: TasksTab;
  stack: PageRef[];
  sheet: Sheet | null;
};

/** A starting point, from a deep link: anything left out takes the default. */
export type NavigationInit = Partial<NavigationState>;

export type NavigationAction =
  | { type: "tab"; tab: Tab; tasksTab?: TasksTab }
  | { type: "tasksTab"; tasksTab: TasksTab }
  | { type: "push"; page: PageRef }
  | { type: "pop" }
  | { type: "replace"; page: PageRef }
  | { type: "openTask"; taskId: number }
  | { type: "closeTask" }
  | { type: "openPage"; page: Page }
  | { type: "closePage" }
  | { type: "reset"; init?: NavigationInit }
  | { type: "sheet"; sheet: Sheet | null };

const LEGACY_PAGES: readonly string[] = ["team"] satisfies Page[];

export const taskPage = (taskId: number): PageRef => ({ feature: CORE, page: "task", params: { id: taskId } });
const isTask = (ref: PageRef) => ref.feature === CORE && ref.page === "task";
const isLegacyPage = (ref: PageRef) => ref.feature === CORE && LEGACY_PAGES.includes(ref.page);

function sameParams(a: Params = {}, b: Params = {}): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((key) => String(a[key]) === String(b[key]));
}

export function samePage(a: PageRef | undefined, b: PageRef | undefined): boolean {
  return Boolean(a && b && a.feature === b.feature && a.page === b.page && sameParams(a.params, b.params));
}

/** Drop the last entry matching `test` and everything above it. */
function closeLast(stack: PageRef[], test: (ref: PageRef) => boolean): PageRef[] {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (test(stack[index])) return stack.slice(0, index);
  }
  return stack;
}

export function initialNavigation(init: NavigationInit = {}): NavigationState {
  return {
    tab: init.tab ?? "home",
    tasksTab: init.tasksTab ?? "daily",
    stack: init.stack ?? [],
    sheet: init.sheet ?? null,
  };
}

export function reduceNavigation(state: NavigationState, action: NavigationAction): NavigationState {
  switch (action.type) {
    case "tab":
      // Switching tabs starts fresh: no pages, no sheet.
      return { ...state, tab: action.tab, tasksTab: action.tasksTab ?? state.tasksTab, stack: [], sheet: null };
    case "tasksTab":
      return { ...state, tasksTab: action.tasksTab };
    case "push":
      if (samePage(state.stack.at(-1), action.page)) return { ...state, sheet: null };
      return { ...state, stack: [...state.stack, action.page], sheet: null };
    case "pop":
      return state.stack.length ? { ...state, stack: state.stack.slice(0, -1) } : state;
    case "replace":
      return { ...state, stack: [...state.stack.slice(0, -1), action.page], sheet: null };
    case "openTask": {
      // One task at a time, as before: a second task replaces the first instead of stacking.
      const top = state.stack.at(-1);
      const stack = top && isTask(top) ? state.stack.slice(0, -1) : state.stack;
      return { ...state, stack: [...stack, taskPage(action.taskId)], sheet: null };
    }
    case "closeTask":
      return { ...state, stack: closeLast(state.stack, isTask) };
    case "openPage": {
      const page: PageRef = { feature: CORE, page: action.page };
      if (samePage(state.stack.at(-1), page)) return { ...state, sheet: null };
      return { ...state, stack: [...state.stack, page], sheet: null };
    }
    case "closePage":
      return { ...state, stack: closeLast(state.stack, isLegacyPage) };
    case "reset":
      return initialNavigation(action.init);
    case "sheet":
      return { ...state, sheet: action.sheet };
  }
}

/** The open task (the topmost core task page), for code written before the stack. */
export function openTaskId(stack: readonly PageRef[]): number | null {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    const ref = stack[index];
    if (isTask(ref)) return Number(ref.params?.id);
  }
  return null;
}

/** The open built-in page, for code written before the stack. */
export function openLegacyPage(stack: readonly PageRef[]): Page | null {
  for (let index = stack.length - 1; index >= 0; index -= 1) {
    if (isLegacyPage(stack[index])) return stack[index].page as Page;
  }
  return null;
}

export type Navigation = NavigationState & {
  /** The open built-in page ("team"), if any. */
  page: Page | null;
  /** The open task, if any. */
  taskId: number | null;
  /** The page on top of the stack, or null on a tab. */
  top: PageRef | null;
  goTo: (tab: Tab, tasksTab?: TasksTab) => void;
  setTasksTab: (tasksTab: TasksTab) => void;
  openTask: (taskId: number) => void;
  closeTask: () => void;
  openPage: (page: Page) => void;
  closePage: () => void;
  openSheet: (sheet: Sheet) => void;
  closeSheet: () => void;
  /** Open a page over the current one (closes any sheet). */
  push: (page: PageRef) => void;
  /** Close the top page. */
  pop: () => void;
  /** Swap the top page for another (or open it when on a tab). */
  replace: (page: PageRef) => void;
  /** Start over from a tab (default: Home). */
  reset: (init?: NavigationInit) => void;
  /** What Telegram's back button does: close the sheet, else pop. False when there's nothing to close. */
  back: () => boolean;
};

const NavigationContext = createContext<Navigation | null>(null);

export function NavigationProvider({ children, initial }: { children: ReactNode; initial?: NavigationInit | null }) {
  const [state, dispatch] = useReducer(reduceNavigation, initial ?? undefined, initialNavigation);
  const value = useMemo<Navigation>(
    () => ({
      ...state,
      page: openLegacyPage(state.stack),
      taskId: openTaskId(state.stack),
      top: state.stack.at(-1) ?? null,
      goTo: (tab, tasksTab) => dispatch({ type: "tab", tab, tasksTab }),
      setTasksTab: (tasksTab) => dispatch({ type: "tasksTab", tasksTab }),
      openTask: (taskId) => dispatch({ type: "openTask", taskId }),
      closeTask: () => dispatch({ type: "closeTask" }),
      openPage: (page) => dispatch({ type: "openPage", page }),
      closePage: () => dispatch({ type: "closePage" }),
      openSheet: (sheet) => dispatch({ type: "sheet", sheet }),
      closeSheet: () => dispatch({ type: "sheet", sheet: null }),
      push: (page) => dispatch({ type: "push", page }),
      pop: () => dispatch({ type: "pop" }),
      replace: (page) => dispatch({ type: "replace", page }),
      reset: (init) => dispatch({ type: "reset", init }),
      back: () => {
        if (state.sheet) dispatch({ type: "sheet", sheet: null });
        else if (state.stack.length) dispatch({ type: "pop" });
        else return false;
        return true;
      },
    }),
    [state],
  );
  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>;
}

export function useNavigation(): Navigation {
  const navigation = useContext(NavigationContext);
  if (!navigation) throw new Error("useNavigation outside NavigationProvider");
  return navigation;
}
