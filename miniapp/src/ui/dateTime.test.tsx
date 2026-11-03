/**
 * The app's own time and day pickers: always 24-hour times, the app's month and weekday names
 * whatever the phone's language, keys and screen readers, and the calendar's arithmetic.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { useState, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { I18nProvider, type Lang } from "../i18n";
import { clampDay, DateInput, HOURS, minuteOptions, monthWeeks, moveDay, shiftMonth, splitTime, TimeInput } from "./DateTime";
import { Field } from "./Field";
import { Sheet } from "./Sheet";

const inLang = (lang: Lang, node: ReactNode) => render(<I18nProvider lang={lang}>{node}</I18nProvider>);
/** The numbers the pill shows ("18:30"), without the lists' option texts. */
const shown = (group: HTMLElement) => [...group.querySelectorAll(".ui-time-text")].map((part) => part.textContent).join(":");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("every date and time in the app", () => {
  it("uses these pickers, never the phone's own date or time box", () => {
    const SRC = join(process.cwd(), "src");
    const files = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((entry) => (entry.isDirectory() ? files(join(dir, entry.name)) : [join(dir, entry.name)]));
    const native = files(SRC)
      .filter((path) => path.endsWith(".tsx") && !path.endsWith(".test.tsx"))
      .filter((path) => /type=["{]+["']?(date|time|datetime-local|month|week)["']/.test(readFileSync(path, "utf8")))
      .map((path) => relative(SRC, path));
    expect(native).toEqual([]);
  });
});

describe("time values", () => {
  it("reads HH:MM (seconds allowed) and nothing else", () => {
    expect(splitTime("18:30")).toEqual(["18", "30"]);
    expect(splitTime("07:05:00")).toEqual(["07", "05"]);
    expect(splitTime("")).toEqual(["", ""]);
    expect(splitTime("24:00")).toEqual(["", ""]);
    expect(splitTime("4:00 AM")).toEqual(["", ""]);
  });

  it("offers 24 hours and minutes by the step, keeping the value's own minute", () => {
    expect(HOURS).toHaveLength(24);
    expect([HOURS[0], HOURS[13], HOURS[23]]).toEqual(["00", "13", "23"]);
    expect(minuteOptions(5, "")).toEqual(["00", "05", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55"]);
    expect(minuteOptions(5, "17").slice(3, 6)).toEqual(["15", "17", "20"]);
    expect(minuteOptions(1, "")).toHaveLength(60);
  });
});

describe("calendar arithmetic", () => {
  it("lays a month out in weeks from Monday", () => {
    // 1 November 2026 is a Sunday; the 30th a Monday.
    const november = monthWeeks("2026-11");
    expect(november).toHaveLength(6);
    expect(november[0]).toEqual([null, null, null, null, null, null, "2026-11-01"]);
    expect(november[1][0]).toBe("2026-11-02");
    expect(november[5]).toEqual(["2026-11-30", null, null, null, null, null, null]);
    // February 2027 starts on a Monday and fills exactly four weeks.
    expect(monthWeeks("2027-02")).toHaveLength(4);
    expect(monthWeeks("2027-02")[0][0]).toBe("2027-02-01");
  });

  it("turns months and moves the focused day as the grid keys do", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(moveDay("2026-11-04", "ArrowRight")).toBe("2026-11-05");
    expect(moveDay("2026-11-04", "ArrowUp")).toBe("2026-10-28");
    expect(moveDay("2026-11-04", "Home")).toBe("2026-11-02");
    expect(moveDay("2026-11-04", "End")).toBe("2026-11-08");
    expect(moveDay("2026-01-31", "PageDown")).toBe("2026-02-28");
    expect(moveDay("2026-11-04", "x")).toBeNull();
    expect(clampDay("2026-11-01", "2026-11-03")).toBe("2026-11-03");
    expect(clampDay("2026-11-09", undefined, "2026-11-05")).toBe("2026-11-05");
  });
});

function TimeHost({ start = "18:30", onChange = vi.fn(), optional = false, step }: { start?: string; onChange?: (value: string) => void; optional?: boolean; step?: number }) {
  const [value, setValue] = useState(start);
  return (
    <TimeInput
      label="Time"
      value={value}
      optional={optional}
      step={step}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

describe("TimeInput", () => {
  it("is 24-hour whatever the language, and names its two lists", () => {
    const onChange = vi.fn();
    inLang("en", <TimeHost onChange={onChange} />);
    const group = screen.getByRole("group", { name: "Time" });
    const hour = within(group).getByRole("combobox", { name: "Hour" }) as HTMLSelectElement;
    const minute = within(group).getByRole("combobox", { name: "Minutes" }) as HTMLSelectElement;
    const hours = [...hour.options].map((option) => option.text);
    expect(hours).toEqual(HOURS);
    expect(group.textContent).not.toMatch(/AM|PM/);
    expect(shown(group)).toBe("18:30");
    fireEvent.change(hour, { target: { value: "09" } });
    expect(onChange).toHaveBeenLastCalledWith("09:30");
    fireEvent.change(minute, { target: { value: "45" } });
    expect(onChange).toHaveBeenLastCalledWith("09:45");
    expect(shown(group)).toBe("09:45");
  });

  it("speaks the app's language", () => {
    inLang("uz", <TimeHost />);
    expect(screen.getByRole("combobox", { name: "Soat" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Daqiqa" })).toBeTruthy();
  });

  it("can be left empty where a time is optional", () => {
    const onChange = vi.fn();
    inLang("en", <TimeHost start="" optional step={1} onChange={onChange} />);
    const hour = screen.getByRole("combobox", { name: "Hour" }) as HTMLSelectElement;
    const minute = screen.getByRole("combobox", { name: "Minutes" }) as HTMLSelectElement;
    expect(shown(screen.getByRole("group", { name: "Time" }))).toBe("––:––");
    expect(minute.disabled).toBe(true);
    fireEvent.change(hour, { target: { value: "08" } });
    expect(onChange).toHaveBeenLastCalledWith("08:00");
    expect(minute.options).toHaveLength(60);
    fireEvent.change(hour, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith("");
  });

  it("keeps a minute between the steps", () => {
    inLang("en", <TimeHost start="23:17" />);
    expect((screen.getByRole("combobox", { name: "Minutes" }) as HTMLSelectElement).value).toBe("17");
  });

  it("takes its id from the Field around it, so the label names it", () => {
    inLang(
      "en",
      <Field label="Arrived">
        <TimeInput label="Arrived" value="09:12" step={1} onChange={() => undefined} />
      </Field>,
    );
    expect(screen.getByLabelText("Arrived", { selector: "select" })).toBe(screen.getByRole("combobox", { name: "Hour" }));
  });
});

function DateHost({ start = "2026-11-04", lang = "uz" as Lang, onChange = vi.fn(), min = "2026-11-03", max }: { start?: string; lang?: Lang; onChange?: (value: string) => void; min?: string; max?: string }) {
  const [value, setValue] = useState(start);
  return (
    <I18nProvider lang={lang}>
      <DateInput
        label="Kun"
        value={value}
        min={min}
        max={max}
        today="2026-11-02"
        onChange={(next) => {
          onChange(next);
          setValue(next);
        }}
      />
    </I18nProvider>
  );
}

describe("DateInput", () => {
  it("shows the day and opens a calendar in the app's language", () => {
    const onChange = vi.fn();
    render(<DateHost onChange={onChange} />);
    const field = screen.getByRole("button", { name: "Kun: chorshanba, 4-noyabr" });
    expect(field.textContent).toBe("Chor, 4-noy");
    expect(field.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(field);
    expect(field.getAttribute("aria-expanded")).toBe("true");
    const grid = screen.getByRole("grid", { name: "Noyabr 2026" });
    expect([...grid.querySelectorAll("th")].map((head) => head.textContent)).toEqual(["Dush", "Sesh", "Chor", "Pay", "Jum", "Shan", "Yak"]);
    expect(screen.getByRole("button", { name: "Chorshanba, 4-noyabr" }).getAttribute("aria-pressed")).toBe("true");
    // Today is marked, and days before the first allowed one can't be picked.
    const today = screen.getByRole("button", { name: "Dushanba, 2-noyabr" }) as HTMLButtonElement;
    expect(today.getAttribute("aria-current")).toBe("date");
    expect(today.disabled).toBe(true);
    // The chosen day has focus, for keys and screen readers.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Chorshanba, 4-noyabr" }));

    fireEvent.click(screen.getByRole("button", { name: "Payshanba, 5-noyabr" }));
    expect(onChange).toHaveBeenLastCalledWith("2026-11-05");
    expect(screen.queryByRole("grid")).toBeNull();
    expect(field.textContent).toBe("Pay, 5-noy");
    expect(document.activeElement).toBe(field);
  });

  it("says the year of a day in another year, so a year from today doesn't read as today", () => {
    render(<DateHost start="2027-11-02" max="2028-12-31" />);
    const field = screen.getByRole("button", { name: "Kun: seshanba, 2027-yil 2-noyabr" });
    expect(field.textContent).toBe("Sesh, 2027-yil 2-noyabr");
    cleanup();
    render(<DateHost start="2027-11-02" max="2028-12-31" lang="en" />);
    expect(screen.getByRole("button", { name: /^Kun: / }).textContent).toBe("Tue, 2 November 2027");
  });

  it("names months and weekdays in Russian and English too", () => {
    render(<DateHost lang="ru" />);
    fireEvent.click(screen.getByRole("button", { name: /^Kun: / }));
    const grid = screen.getByRole("grid", { name: "Ноябрь 2026 г." });
    expect([...grid.querySelectorAll("th")].map((head) => head.textContent)).toEqual(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]);
    cleanup();
    render(<DateHost lang="en" />);
    fireEvent.click(screen.getByRole("button", { name: /^Kun: / }));
    expect(screen.getByRole("grid", { name: "November 2026" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Wednesday, 4 November" })).toBeTruthy();
  });

  it("turns the month, but not before the first allowed day's month or past the last", () => {
    render(<DateHost max="2026-12-20" />);
    fireEvent.click(screen.getByRole("button", { name: /^Kun: / }));
    const back = screen.getByRole("button", { name: "Oldingi oy" }) as HTMLButtonElement;
    const next = screen.getByRole("button", { name: "Keyingi oy" }) as HTMLButtonElement;
    expect(back.disabled).toBe(true);
    fireEvent.click(next);
    expect(screen.getByRole("grid", { name: "Dekabr 2026" })).toBeTruthy();
    expect(next.disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Dushanba, 21-dekabr" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Yakshanba, 20-dekabr" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("moves with the arrow and page keys, and Escape closes only the calendar, not the sheet", () => {
    const closed = vi.fn();
    render(
      <I18nProvider lang="uz">
        <Sheet onClose={closed} label="Muddat">
          <DateHost />
        </Sheet>
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Kun: / }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Payshanba, 5-noyabr" }));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Payshanba, 12-noyabr" }));
    fireEvent.keyDown(document.activeElement!, { key: "PageDown" });
    expect(screen.getByRole("grid", { name: "Dekabr 2026" })).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Shanba, 12-dekabr" }));
    // Never onto a day that can't be picked.
    fireEvent.keyDown(document.activeElement!, { key: "PageUp" });
    fireEvent.keyDown(document.activeElement!, { key: "PageUp" });
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Seshanba, 3-noyabr" }));

    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("grid")).toBeNull();
    expect(closed).not.toHaveBeenCalled();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(closed).toHaveBeenCalledTimes(1);
  });
});
