/** "Checked by" on the task screen, as the person looking at it reads it. */
import { describe, expect, it } from "vitest";

import type { Task } from "../api/types";
import { translate } from "../i18n";
import { checker } from "./TaskDetail";

const t = ((key: string, vars?: Record<string, string | number>) => translate("en", key, vars)) as Parameters<typeof checker>[2];
const manager = { id: 3, name: "Bekzod Mirzayev", position: null };
const owner = { id: 9, name: "Dilnoza Karimova", position: null };

function task(fields: Partial<Task>): Task {
  return { kind: "daily", needs_confirmation: true, actions: [], created_by: manager, confirmed_by: null, ...fields } as unknown as Task;
}

describe("who checks a task", () => {
  it("is the manager to the person who does it, and the giver of assigned work", () => {
    expect(checker(task({}), 7, t)).toBe("Your manager");
    expect(checker(task({ kind: "assigned" }), 7, t)).toBe("Bekzod Mirzayev");
    expect(checker(task({ needs_confirmation: false }), 7, t)).toBe("No check needed");
  });

  it("is you for whoever checks it, not their own manager", () => {
    // Waiting for my check, or work I gave or set up.
    expect(checker(task({ status: "review", actions: ["confirm", "return"] }), 9, t)).toBe("You");
    expect(checker(task({}), 3, t)).toBe("You");
  });

  it("names who checked it once it's checked", () => {
    expect(checker(task({ status: "done", confirmed_by: owner }), 7, t)).toBe("Dilnoza Karimova");
    expect(checker(task({ status: "done", confirmed_by: owner }), 9, t)).toBe("You");
  });
});
