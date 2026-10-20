import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, type Lang } from "../i18n";
import { ToastProvider, useToast } from "../state/toast";
import { Button } from "./Button";
import { countedNotes, countedTotal, DenominationCounter } from "./DenominationCounter";
import { Field, Input } from "./Field";
import { ListRow } from "./ListRow";
import { MoneyInput } from "./MoneyInput";
import { NumberPad, pressKey } from "./NumberPad";
import { ProgressRing } from "./Progress";
import { Segmented } from "./Segmented";
import { SkeletonList } from "./Skeleton";
import { SlideToConfirm } from "./SlideToConfirm";
import { Stepper } from "./Stepper";

const NB = " ";
const inLang = (lang: Lang, node: React.ReactNode) => render(<I18nProvider lang={lang}>{node}</I18nProvider>);

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("number pad", () => {
  it("builds amounts key by key", () => {
    const keys = (start: string, presses: Parameters<typeof pressKey>[1][], options = {}) =>
      presses.reduce((value, key) => pressKey(value, key, options), start);
    expect(keys("", ["1", "2", "000"])).toBe("12000");
    expect(keys("", ["000"])).toBe("");
    expect(keys("", ["0", "0", "5"])).toBe("5");
    expect(keys("12", ["back", "back", "back"])).toBe("");
    expect(keys("", ["."])).toBe("");
    expect(keys("", [".", "5", "0", "1"], { decimals: true })).toBe("0.50");
    expect(keys("3.5", ["000", "."], { decimals: true })).toBe("3.5");
    expect(keys("999999", ["9"], { maxDigits: 6 })).toBe("999999");
    expect(keys("99999", ["000"], { maxDigits: 6 })).toBe("99999");
  });

  it("shows the grouped amount with the currency and types into it", () => {
    function Pad() {
      const [value, setValue] = useState("125");
      return <NumberPad value={value} onChange={setValue} label="Cash in the drawer" />;
    }
    const { container } = inLang("uz", <Pad />);
    fireEvent.click(screen.getByRole("button", { name: "000" }));
    expect(container.querySelector(".ui-numpad-amount")?.textContent).toBe(`125${NB}000so‘m`);
    fireEvent.click(screen.getByRole("button", { name: "O‘chirish" }));
    expect(container.querySelector(".ui-numpad-amount .heading")?.textContent).toBe(`12${NB}500`);
  });
});

describe("money input", () => {
  function Controlled({ currency = "UZS" }: { currency?: "UZS" | "USD" }) {
    const [value, setValue] = useState("");
    return (
      <>
        <Field label="Amount">
          <MoneyInput value={value} onChange={setValue} currency={currency} />
        </Field>
        <output>{value}</output>
      </>
    );
  }

  it("groups digits as you type and keeps a plain value", () => {
    const { container } = inLang("ru", <Controlled />);
    const input = screen.getByLabelText("Amount") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "1250000" } });
    expect(input.value).toBe(`1${NB}250${NB}000`);
    expect(container.querySelector("output")?.textContent).toBe("1250000");
    expect(container.querySelector(".ui-money-suffix")?.textContent).toBe("сум");
    expect(input.inputMode).toBe("numeric");
  });

  it("takes cents for dollars", () => {
    const { container } = inLang("en", <Controlled currency="USD" />);
    const input = screen.getByLabelText("Amount") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "1,250.555" } });
    expect(input.value).toBe("1,250.55");
    expect(container.querySelector("output")?.textContent).toBe("1250.55");
    expect(input.inputMode).toBe("decimal");
  });
});

describe("fields", () => {
  it("wire the label, the hint or the error to the control", () => {
    inLang(
      "uz",
      <>
        <Field label="Reason" optional hint="Short is fine">
          <Input />
        </Field>
        <Field label="Phone" error="Wrong number">
          <Input />
        </Field>
      </>,
    );
    const reason = screen.getByLabelText(/Reason/);
    expect(screen.getByText("Reason").textContent).toBe("Reason (ixtiyoriy)");
    expect(document.getElementById(reason.getAttribute("aria-describedby")!)?.textContent).toBe("Short is fine");
    const phone = screen.getByLabelText("Phone");
    expect(phone.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe("Wrong number");
  });
});

describe("segmented control", () => {
  it("marks the choice for screen readers and reports changes", () => {
    const onChange = vi.fn();
    inLang(
      "en",
      <Segmented
        role="tablist"
        value="week"
        onChange={onChange}
        options={[
          { value: "week", label: "Week" },
          { value: "month", label: "Month", count: 3 },
        ]}
      />,
    );
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.getAttribute("aria-selected"))).toEqual(["true", "false"]);
    expect(tabs[1].textContent).toBe("Month3");
    fireEvent.click(tabs[0]);
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(tabs[1]);
    expect(onChange).toHaveBeenCalledWith("month");
  });
});

describe("counting cash", () => {
  it("totals notes exactly", () => {
    expect(countedTotal({ "200000": 12, "100000": 7, "5000": 4 })).toBe("3120000.00");
    expect(countedNotes({ "200000": 12, "100000": 7, "5000": 4 })).toBe(23);
    expect(countedTotal({})).toBe("0.00");
  });

  it("counts with steppers and shows the running total", () => {
    function Counter() {
      const [counts, setCounts] = useState({});
      return <DenominationCounter counts={counts} onChange={setCounts} notes={["50000", "1000"]} />;
    }
    const { container } = inLang("en", <Counter />);
    const more = screen.getAllByRole("button", { name: "More" });
    fireEvent.click(more[0]);
    fireEvent.click(more[0]);
    fireEvent.click(more[1]);
    expect(container.querySelector(".ui-denoms-total .ui-money")?.textContent).toBe("101,000UZS");
    expect(container.querySelector(".ui-denoms-total-label")?.textContent).toBe("Total3 notes");
  });

  it("keeps steppers inside their limits", () => {
    const onChange = vi.fn();
    inLang("en", <Stepper value={0} onChange={onChange} max={1} />);
    expect((screen.getByRole("button", { name: "Less" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(onChange).toHaveBeenCalledWith(1);
  });
});

describe("slide to confirm", () => {
  it("confirms from the keyboard, once", () => {
    const onConfirm = vi.fn();
    const { rerender } = inLang("en", <SlideToConfirm label="Slide to check in" onConfirm={onConfirm} />);
    const knob = screen.getByRole("button", { name: "Slide to check in" });
    fireEvent.keyDown(knob, { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledOnce();
    rerender(
      <I18nProvider lang="en">
        <SlideToConfirm label="Slide to check in" onConfirm={onConfirm} state="loading" />
      </I18nProvider>,
    );
    fireEvent.keyDown(knob, { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

describe("toasts", () => {
  it("keep the original markup for a plain message and add an action when asked", () => {
    vi.useFakeTimers();
    const undo = vi.fn();
    function Trigger() {
      const toast = useToast();
      return (
        <>
          <Button onClick={() => toast("Saved")}>plain</Button>
          <Button onClick={() => toast("Task done", { action: { label: "Undo", onPress: undo } })}>undo</Button>
        </>
      );
    }
    const { container } = inLang(
      "en",
      <ToastProvider>
        <Trigger />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "plain" }));
    expect(container.querySelector(".toast")?.outerHTML).toBe('<div class="toast" role="status"><div>Saved</div></div>');
    act(() => {
      vi.advanceTimersByTime(2700);
    });
    expect(container.querySelector(".toast")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "undo" }));
    act(() => {
      vi.advanceTimersByTime(4000);
    });
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(undo).toHaveBeenCalledOnce();
    expect(container.querySelector(".toast")).toBeNull();
  });
});

describe("extracted building blocks", () => {
  it("draw the home ring exactly as before", () => {
    const { container } = render(<ProgressRing value={3} total={8} />);
    const ring = container.querySelector(".ui-ring") as HTMLElement;
    expect(ring.style.width).toBe("66px");
    const circles = container.querySelectorAll("circle");
    expect(circles[0].getAttribute("r")).toBe("27");
    expect(circles[1].getAttribute("stroke-dasharray")).toBe(String(2 * Math.PI * 27));
    expect(container.querySelector(".ui-ring-label")?.textContent).toBe("3/8");
    expect((container.querySelector(".ui-ring-label") as HTMLElement).style.fontSize).toBe("16px");
  });

  it("render task row placeholders like RowSkeleton did", () => {
    const { container } = render(<SkeletonList count={2} />);
    expect(container.innerHTML).toBe('<div class="skeleton" style="height: 68px;" aria-hidden="true"></div>'.repeat(2));
  });

  it("render inset rows with icon, value, badge and chevron", () => {
    const onClick = vi.fn();
    const { container } = render(<ListRow title="Pay" value="3 days" badge={2} onClick={onClick} />);
    const row = container.querySelector("button.list-item")!;
    expect(row.querySelector(".list-item-label")?.textContent).toBe("Pay");
    expect(row.querySelector(".list-item-value")?.textContent).toBe("3 days2");
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledOnce();
  });
});
