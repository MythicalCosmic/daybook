import { afterEach, describe, expect, it, vi } from "vitest";

import { toast } from "@/components/useToast";
import { csvCell, dataUrlBlob, downloadFile, guardFormula, safeFilename, toCsv } from "@/lib/csv";

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

  it("turns a data: URL into a Blob without fetch", async () => {
    const blob = dataUrlBlob("data:image/png;base64,iVBORw==");
    expect(blob.type).toBe("image/png");
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([0x89, 0x50, 0x4e, 0x47]);
  });
});

describe("downloadFile inside Telegram", () => {
  afterEach(() => {
    delete window.Telegram;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("hands the file to the phone's share sheet (the webview ignores <a download>)", () => {
    window.Telegram = { WebApp: { initData: "query_id=1" } as never };
    const share = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, canShare: () => true, share });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    downloadFile("Kassa.csv", "a,b\r\n");
    expect(share).toHaveBeenCalledTimes(1);
    const sent = (share.mock.calls[0] as unknown as [{ files: File[] }])[0].files[0]!;
    expect(sent.name).toBe("Kassa.csv");
    expect(click).not.toHaveBeenCalled();
  });

  it("says so when the phone has no share sheet (Android's webview)", () => {
    window.Telegram = { WebApp: { initData: "query_id=1" } as never };
    vi.stubGlobal("navigator", { ...navigator, canShare: undefined, share: undefined });
    const warning = vi.spyOn(toast, "warning");
    downloadFile("QR.png", new Blob(["x"], { type: "image/png" }));
    expect(warning).toHaveBeenCalledTimes(1);
  });
});
