import { describe, expect, it } from "vitest";

import { csvCell, guardFormula, safeFilename, toCsv } from "@/lib/csv";

describe("csv", () => {
  it("escapes delimiters, quotes and new lines", () => {
    expect(csvCell("plain")).toBe("plain");
    expect(csvCell("a,b")).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell("line\nbreak")).toBe('"line\nbreak"');
    expect(csvCell(null)).toBe("");
    expect(csvCell(12.5)).toBe("12.5");
  });

  it("stops cells from running as Excel formulas but keeps negative numbers", () => {
    expect(guardFormula("=SUM(A1:A3)")).toBe("'=SUM(A1:A3)");
    expect(guardFormula("+998901234567x")).toBe("'+998901234567x");
    expect(guardFormula("@cmd")).toBe("'@cmd");
    expect(guardFormula("-15000.00")).toBe("-15000.00");
    expect(guardFormula("+5")).toBe("+5");
  });

  it("builds a UTF-8 file Excel opens, with a BOM", () => {
    const text = toCsv(
      [
        { key: "name", label: "Ism" },
        { key: "amount", label: "Summa", value: (row: { name: string; amount: string }) => row.amount },
      ],
      [
        { name: "Dilnoza", amount: "1250000.00" },
        { name: "O‘g‘il, Aziz", amount: "-15000.00" },
      ],
    );
    expect(text.startsWith("﻿")).toBe(true);
    expect(text).toBe('﻿Ism,Summa\r\nDilnoza,1250000.00\r\n"O‘g‘il, Aziz",-15000.00\r\n');
    expect(toCsv([{ key: "a", label: "A" }], [], { bom: false, delimiter: ";" })).toBe("A\r\n");
  });

  it("makes safe file names", () => {
    expect(safeFilename("Sales: Oct/Nov", "xlsx")).toBe("Sales- Oct-Nov.xlsx");
    expect(safeFilename("   ", ".csv")).toBe("export.csv");
  });
});
