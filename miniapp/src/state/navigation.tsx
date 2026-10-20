import { createContext, useContext, useMemo, useReducer, type ReactNode } from "react";

export type Tab = "home" | "tasks" | "activity" | "profile";
export type TasksTab = "daily" | "assigned" | "personal" | "review";
export type Sheet =
  | { kind: "complete"; taskId: number }
  | { kind: "return"; taskId: number }
  | { kind: "add" }
  | { kind: "language" }
  | { kind: "company" };

type State = { tab: Tab; tasksTab: TasksTab; taskId: number | null; sheet: Sheet | null };

type Action =
  | { type: "tab"; tab: Tab; tasksTab?: TasksTab }
  | { type: "tasksTab"; tasksTab: TasksTab }
  | { type: "openTask"; taskId: number }
  | { type: "closeTask" }
  | { type: "sheet"; sheet: Sheet | null };

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "tab":
      return {
        ...state,
        tab: action.tab,
        tasksTab: action.tasksTab ?? state.tasksTab,
        taskId: null,
        sheet: null,
      };
    case "tasksTab":
      return { ...state, tasksTab: action.tasksTab };
    case "openTask":
      return { ...state, taskId: action.taskId, sheet: null };
    case "closeTask":
      return { ...state, taskId: null };
    case "sheet":
      return { ...state, sheet: action.sheet };
  }
}

type Navigation = State & {
  goTo: (tab: Tab, tasksTab?: TasksTab) => void;
  setTasksTab: (tasksTab: TasksTab) => void;
  openTask: (taskId: number) => void;
  closeTask: () => void;
  openSheet: (sheet: Sheet) => void;
  closeSheet: () => void;
};

const NavigationContext = createContext<Navigation | null>(null);

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, {
    tab: "home",
    tasksTab: "daily",
    taskId: null,
    sheet: null,
  });
  const value = useMemo<Navigation>(
    () => ({
      ...state,
      goTo: (tab, tasksTab) => dispatch({ type: "tab", tab, tasksTab }),
      setTasksTab: (tasksTab) => dispatch({ type: "tasksTab", tasksTab }),
      openTask: (taskId) => dispatch({ type: "openTask", taskId }),
      closeTask: () => dispatch({ type: "closeTask" }),
      openSheet: (sheet) => dispatch({ type: "sheet", sheet }),
      closeSheet: () => dispatch({ type: "sheet", sheet: null }),
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
