/**
 * Checklist steps keep their own rows: removing the middle of three leaves the other inputs, their
 * texts and the focus where they were (rows keyed by position handed "c" to "b"'s input and dropped
 * the focus, closing the phone's keyboard).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n";
import { StepsEditor } from "./StepsEditor";

function Harness({ initial }: { initial: string[] }) {
  const [steps, setSteps] = useState(initial);
  return (
    <I18nProvider lang="en">
      <StepsEditor steps={steps} onChange={setSteps} />
      <output data-testid="steps">{JSON.stringify(steps)}</output>
    </I18nProvider>
  );
}

const inputs = () => screen.getAllByRole("textbox") as HTMLInputElement[];

afterEach(cleanup);

describe("StepsEditor", () => {
  it("removes the middle of three steps; the others keep their values and the focus", () => {
    render(<Harness initial={["Count the till", "Check the fridge", "Send a photo"]} />);
    const [first, , third] = inputs();
    third!.focus();
    fireEvent.click(screen.getByRole("button", { name: "Remove step 2" }));

    expect(inputs().map((input) => input.value)).toEqual(["Count the till", "Send a photo"]);
    // The very same inputs: React didn't move "Send a photo" into the removed step's field.
    expect(inputs()[0]).toBe(first);
    expect(inputs()[1]).toBe(third);
    expect(document.activeElement).toBe(third);
    expect(screen.getByTestId("steps").textContent).toBe(JSON.stringify(["Count the till", "Send a photo"]));

    // Typing goes on in the right step.
    fireEvent.change(third!, { target: { value: "Send a photo of the thermometer" } });
    expect(inputs().map((input) => input.value)).toEqual(["Count the till", "Send a photo of the thermometer"]);
  });

  it("moves the focus to the step that took the removed one's place, or the one before", () => {
    render(<Harness initial={["a", "b", "c"]} />);
    const [, , third] = inputs();
    const removeSecond = screen.getByRole("button", { name: "Remove step 2" });
    removeSecond.focus();
    fireEvent.click(removeSecond);
    expect(document.activeElement).toBe(third);

    const removeLast = screen.getByRole("button", { name: "Remove step 2" });
    removeLast.focus();
    fireEvent.click(removeLast);
    expect(document.activeElement).toBe(inputs()[0]);
    expect(inputs().map((input) => input.value)).toEqual(["a"]);

    const removeOnly = screen.getByRole("button", { name: "Remove step 1" });
    removeOnly.focus();
    fireEvent.click(removeOnly);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add a step" }));
  });

  it("adds a step at the end and keeps the earlier ones", () => {
    render(<Harness initial={["a"]} />);
    const [first] = inputs();
    fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
    expect(inputs()).toHaveLength(2);
    expect(inputs()[0]).toBe(first);
    expect(document.activeElement).toBe(inputs()[1]);
  });
});
