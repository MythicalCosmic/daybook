import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, type Lang } from "../i18n";
import { ToastProvider, useToast } from "../state/toast";
import { Button } from "./Button";
import { countedNotes, countedTotal, DenominationCounter } from "./DenominationCounter";
import { Field, Input } from "./Field";
import { ListRow } from "./ListRow";
import { MoneyInput } from "./MoneyInput";
import { NumberPad, pressKey } from "./NumberPad";
import { PhotoInput } from "./PhotoInput";
import { ProgressRing } from "./Progress";
import { Segmented } from "./Segmented";
import { Sheet } from "./Sheet";
import { SkeletonList } from "./Skeleton";
import { SlideToConfirm } from "./SlideToConfirm";
import { Stepper } from "./Stepper";
import { useObjectUrl } from "./useObjectUrl";
import { useScrollEdges } from "./useScrollEdges";

const NB = " ";
const inLang = (lang: Lang, node: React.ReactNode) => render(<I18nProvider lang={lang}>{node}</I18nProvider>);

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
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

  it("types from a desktop keyboard once one of its keys has focus", () => {
    function Pad() {
      const [value, setValue] = useState("");
      return <NumberPad value={value} onChange={setValue} />;
    }
    const { container } = inLang("ru", <Pad />);
    const key = screen.getByRole("button", { name: "7" });
    fireEvent.keyDown(key, { key: "4" });
    fireEvent.keyDown(key, { key: "5" });
    fireEvent.keyDown(key, { key: "0" });
    fireEvent.keyDown(key, { key: "0" });
    fireEvent.keyDown(key, { key: "Backspace" });
    fireEvent.keyDown(key, { key: "s" });
    fireEvent.keyDown(key, { key: "1", ctrlKey: true });
    expect(container.querySelector(".ui-numpad-amount .heading")?.textContent).toBe("450");
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

describe("a strip that scrolls sideways", () => {
  function Strip() {
    const edges = useScrollEdges<HTMLDivElement>();
    return <div data-testid="strip" ref={edges.ref} />;
  }

  it("says which sides hide more of it, for the fade", () => {
    render(<Strip />);
    const strip = screen.getByTestId("strip");
    Object.defineProperty(strip, "clientWidth", { configurable: true, value: 300 });
    Object.defineProperty(strip, "scrollWidth", { configurable: true, value: 500 });
    const scrollTo = (left: number) => {
      strip.scrollLeft = left;
      fireEvent.scroll(strip);
    };
    scrollTo(0);
    expect(strip.dataset.more).toBe("right");
    scrollTo(100);
    expect(strip.dataset.more).toBe("both");
    scrollTo(200);
    expect(strip.dataset.more).toBe("left");
    Object.defineProperty(strip, "scrollWidth", { configurable: true, value: 300 });
    scrollTo(0);
    expect(strip.dataset.more).toBeUndefined();
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

  it("moves the choice with the arrow keys and keeps one Tab stop, like native radios", () => {
    function Period() {
      const [value, setValue] = useState<"week" | "month" | "year">("week");
      return (
        <Segmented
          label="Period"
          value={value}
          onChange={setValue}
          options={[
            { value: "week", label: "Week" },
            { value: "month", label: "Month", disabled: true },
            { value: "year", label: "Year" },
          ]}
        />
      );
    }
    inLang("en", <Period />);
    const radios = () => screen.getAllByRole("radio");
    expect(radios().map((radio) => radio.tabIndex)).toEqual([0, -1, -1]);
    act(() => radios()[0].focus());
    fireEvent.keyDown(radios()[0], { key: "ArrowRight" });
    // The disabled option is skipped; focus follows the choice.
    expect(radios().map((radio) => radio.getAttribute("aria-checked"))).toEqual(["false", "false", "true"]);
    expect(document.activeElement).toBe(radios()[2]);
    expect(radios().map((radio) => radio.tabIndex)).toEqual([-1, -1, 0]);
    fireEvent.keyDown(radios()[2], { key: "ArrowRight" });
    expect(radios()[0].getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(radios()[0], { key: "End" });
    expect(radios()[2].getAttribute("aria-checked")).toBe("true");
  });
});

describe("sheet", () => {
  it("is a named dialog that takes focus, closes on Escape and hands focus back", () => {
    function Host() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          {open && (
            <Sheet onClose={() => setOpen(false)}>
              <div className="heading title-sm">New expense</div>
              <button type="button">Send</button>
            </Sheet>
          )}
        </>
      );
    }
    // jsdom has no keyboard modality: treat the focused element as showing its ring, as after Tab.
    const matches = Element.prototype.matches;
    vi.spyOn(Element.prototype, "matches").mockImplementation(function (this: Element, selector: string) {
      return selector === ":focus-visible" ? this === document.activeElement : matches.call(this, selector);
    });
    inLang("en", <Host />);
    const opener = screen.getByRole("button", { name: "Open" });
    act(() => opener.focus());
    fireEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "New expense" });
    expect(document.activeElement).toBe(dialog);
    // Tab stays inside: from the dialog to its only button, and round again.
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Send" }));
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Send" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("doesn't move focus back after a tap, so no ring lights up on the + button", () => {
    function Host() {
      const [open, setOpen] = useState(true);
      return open ? (
        <Sheet onClose={() => setOpen(false)} label="Add">
          <button type="button">Send</button>
        </Sheet>
      ) : (
        <p>closed</p>
      );
    }
    const plus = document.createElement("button");
    document.body.append(plus);
    plus.focus();
    inLang("en", <Host />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByText("closed")).toBeTruthy();
    expect(document.activeElement).not.toBe(plus);
    plus.remove();
  });

  it("leaves focus on a field that asked for it", () => {
    inLang(
      "en",
      <Sheet onClose={() => undefined} title="Return the task">
        <textarea aria-label="Why?" autoFocus />
      </Sheet>,
    );
    expect(screen.getByRole("dialog", { name: "Return the task" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Why?" }));
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
    // Row subtotals stay short; the total names the currency.
    expect([...container.querySelectorAll(".ui-denom-sum")].map((sum) => sum.textContent)).toEqual(["100K", "1K"]);
    expect(container.querySelector(".ui-denoms-total-label")?.textContent).toBe("Total3 notes");
  });

  it("keeps steppers inside their limits", () => {
    const onChange = vi.fn();
    inLang("en", <Stepper value={0} onChange={onChange} max={1} />);
    expect((screen.getByRole("button", { name: "Less" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(onChange).toHaveBeenCalledWith(1);
  });

  it("stops a held + at the limit, so it can't undo a later −", () => {
    vi.useFakeTimers();
    const seen: number[] = [];
    function Counted() {
      const [value, setValue] = useState(0);
      return (
        <Stepper
          value={value}
          max={3}
          onChange={(next) => {
            seen.push(next);
            setValue(next);
          }}
        />
      );
    }
    inLang("en", <Counted />);
    const more = screen.getByRole("button", { name: "More" });
    // Held down: repeats climb to the limit, where the button turns disabled and the release is lost.
    fireEvent.pointerDown(more, { button: 0 });
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(seen).toEqual([1, 2, 3]);
    expect((more as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Less" }));
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(seen).toEqual([1, 2, 3, 2]);
    // The next keyboard press on + counts once, with no stale "that was a hold" flag.
    fireEvent.click(more);
    expect(seen).toEqual([1, 2, 3, 2, 3]);
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

  it("names the knob after its label even when the label is markup", () => {
    inLang(
      "en",
      <SlideToConfirm
        label={
          <>
            Slide to <b>close the till</b>
          </>
        }
        onConfirm={() => undefined}
      />,
    );
    expect(screen.getByRole("button", { name: "Slide to close the till" })).toBeTruthy();
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

  it("keep the ring's original label sizes and shrink a month of team work to fit", () => {
    const size = (value: number, total: number) => {
      const { container } = render(<ProgressRing value={value} total={total} />);
      const label = (container.querySelector(".ui-ring-label") as HTMLElement).style.fontSize;
      cleanup();
      return label;
    };
    expect([size(45, 60), size(45, 160), size(186, 240)]).toEqual(["13.5px", "11.5px", "9.75px"]);
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

  it("keep the value, badge and chevron at their size next to a long title", () => {
    const { container } = render(<ListRow title={"A very long page title ".repeat(6)} value="Must read" onClick={() => {}} />);
    expect(container.querySelector(".list-item-value > svg")?.getAttribute("class")).toContain("list-item-chevron");
    // jsdom lays nothing out, so check the rules themselves (the chevron used to shrink: Q's note).
    const css = readFileSync(resolve(__dirname, "../styles/app.css"), "utf8");
    const rule = (selector: string) => {
      const at = css.indexOf(`\n${selector} {`);
      return at < 0 ? "" : css.slice(at, css.indexOf("}", at));
    };
    expect(rule(".list-item-value")).toMatch(/flex: none;/);
    expect(rule(".list-item-chevron,\n.list-item-value > svg")).toMatch(/flex: none;/);
  });
});

describe("photo input", () => {
  function stubObjectUrls() {
    const made: string[] = [];
    const revoked = new Set<string>();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: (file: File) => {
        const url = `blob:${file.name}#${made.length + 1}`;
        made.push(url);
        return url;
      },
    });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: (url: string) => revoked.add(url) });
    const restore = () => {
      delete (URL as unknown as Record<string, unknown>).createObjectURL;
      delete (URL as unknown as Record<string, unknown>).revokeObjectURL;
    };
    return { made, revoked, restore };
  }
  const shown = (container: HTMLElement) => container.querySelector("img.ui-photo-thumb")?.getAttribute("src") ?? null;

  it("keeps the preview it shows alive under StrictMode, and revokes every URL it made", () => {
    const urls = stubObjectUrls();
    try {
      const first = new File(["a"], "z-report.jpg", { type: "image/jpeg" });
      const second = new File(["b"], "terminal.jpg", { type: "image/jpeg" });
      function Harness() {
        const [file, setFile] = useState<File | null>(first);
        return (
          <>
            <PhotoInput value={file} onChange={setFile} />
            <button type="button" onClick={() => setFile(second)}>
              swap
            </button>
          </>
        );
      }
      const { container, unmount } = inLang(
        "en",
        <StrictMode>
          <Harness />
        </StrictMode>,
      );
      // StrictMode mounts the effect twice: the first URL is revoked, the one on screen isn't.
      const before = shown(container);
      expect(before).toMatch(/^blob:z-report\.jpg#/);
      expect(urls.revoked.has(before!)).toBe(false);
      expect(screen.getByText("z-report.jpg")).toBeTruthy();

      fireEvent.click(screen.getByRole("button", { name: "swap" }));
      const after = shown(container);
      expect(after).toMatch(/^blob:terminal\.jpg#/);
      expect(urls.revoked.has(after!)).toBe(false);
      expect(urls.made.filter((url) => url.startsWith("blob:z-report")).every((url) => urls.revoked.has(url))).toBe(true);

      fireEvent.click(screen.getByRole("button", { name: "Remove" }));
      expect(shown(container)).toBeNull();
      expect(screen.getByText("Take or choose a photo")).toBeTruthy();
      unmount();
      expect(urls.made.every((url) => urls.revoked.has(url))).toBe(true);
    } finally {
      urls.restore();
    }
  });

  it("never hands out a URL made for another file", () => {
    const urls = stubObjectUrls();
    try {
      const seen: (string | null)[] = [];
      function Probe({ file }: { file: File | null }) {
        seen.push(useObjectUrl(file));
        return null;
      }
      const first = new File(["a"], "a.jpg");
      const second = new File(["b"], "b.jpg");
      const { rerender } = render(<Probe file={first} />);
      rerender(<Probe file={second} />);
      // The render with the new file, before its effect, gets null rather than a.jpg's URL.
      const index = seen.lastIndexOf(seen.find((url) => url?.startsWith("blob:b.jpg")) ?? "");
      expect(seen.slice(0, index).filter((url) => url?.startsWith("blob:a.jpg")).length).toBeGreaterThan(0);
      expect(seen[index - 1]).toBeNull();
      rerender(<Probe file={null} />);
      expect(seen.at(-1)).toBeNull();
    } finally {
      urls.restore();
    }
  });
});
