/**
 * A task row: the row and its round tick are sibling buttons (a button inside a button can't be
 * reached by screen readers), each with its own tap, and the row looks and taps as it did.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ctxFor, makeTask } from "../test/harness";
import { TaskRow } from "./TaskRow";

afterEach(cleanup);

describe("TaskRow", () => {
  it("puts the row and the tick side by side, never one inside the other", () => {
    const onOpen = vi.fn();
    const onTick = vi.fn();
    const { container } = render(<TaskRow task={makeTask({ title: "Shelf labels" })} ctx={ctxFor()} onOpen={onOpen} onTick={onTick} />);
    expect(container.querySelectorAll("button button, [role='button'] button, [role='button'] [role='button']")).toHaveLength(0);
    expect(container.querySelector("[role='button']")).toBeNull();

    const row = screen.getByRole("button", { name: /Shelf labels/ });
    const tick = screen.getByRole("button", { name: "Mark as done" });
    expect(tick.parentElement).toBe(row.parentElement);
    // The tick says which task it is for.
    expect(document.getElementById(tick.getAttribute("aria-describedby") ?? "")?.textContent).toBe("Shelf labels");

    fireEvent.click(tick);
    expect(onTick).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
    fireEvent.click(row);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onTick).toHaveBeenCalledTimes(1);
    // The row keeps the tick's place, so its words don't move.
    expect(row.querySelector(".glyph-slot")).toBeTruthy();
  });

  it("opens from the keyboard like any button", () => {
    const onOpen = vi.fn();
    render(<TaskRow task={makeTask({ title: "Fridge log" })} ctx={ctxFor()} onOpen={onOpen} onTick={vi.fn()} />);
    const row = screen.getByRole("button", { name: /Fridge log/ });
    expect(row.tagName).toBe("BUTTON");
    expect(row.getAttribute("type")).toBe("button");
  });

  it("without a tick, the circle only shows the state and a tap on it opens the task", () => {
    const onOpen = vi.fn();
    const { container } = render(<TaskRow task={makeTask({ title: "Count the till", status: "done" })} ctx={ctxFor()} onOpen={onOpen} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Mark as done" })).toBeNull();
    const circle = container.querySelector(".glyph") as HTMLElement;
    expect(circle.className).toContain("glyph--done");
    expect(circle.getAttribute("aria-hidden")).toBe("true");
    fireEvent.click(circle);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
