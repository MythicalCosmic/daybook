import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { defineFeature } from "../features/registry";
import { defineMessages, featureText, featureTranslator, useFeatureT } from "./feature";
import { I18nProvider } from ".";

const messages = defineMessages({
  en: { title: "Pay", "payslips_one": "{count} payslip", "payslips_other": "{count} payslips", earned: "Earned {amount}" },
  ru: {
    title: "Зарплата",
    "payslips_one": "{count} расчётный лист",
    "payslips_few": "{count} расчётных листа",
    "payslips_many": "{count} расчётных листов",
    "payslips_other": "{count} расчётного листа",
    earned: "Заработано {amount}",
  },
  uz: { title: "Maosh", "payslips_one": "{count} ta hisob-varaq", "payslips_other": "{count} ta hisob-varaq", earned: "Topilgan: {amount}" },
});

afterEach(cleanup);

describe("feature translations", () => {
  it("translate the feature's own keys with plurals and placeholders", () => {
    const ru = featureTranslator(messages, "ru");
    expect(ru("title")).toBe("Зарплата");
    expect(ru("payslips", { count: 1 })).toBe("1 расчётный лист");
    expect(ru("payslips", { count: 3 })).toBe("3 расчётных листа");
    expect(ru("payslips", { count: 11 })).toBe("11 расчётных листов");
    expect(featureTranslator(messages, "uz")("earned", { amount: "1 250 000 so‘m" })).toBe("Topilgan: 1 250 000 so‘m");
  });

  it("fall back to the app's own words, so features don't copy them", () => {
    const uz = featureTranslator(messages, "uz");
    expect(uz("common.retry")).toBe("Qayta urinish");
    expect(uz("home.late", { count: 2 })).toBe("2 ta vazifa kechikdi");
  });

  it("accept the feature itself, as the plan writes useFeatureT(feature)", () => {
    const wallet = defineFeature({ id: "wallet", messages });
    expect(featureTranslator(wallet, "en")("payslips", { count: 2 })).toBe("2 payslips");
    expect(featureText(wallet.messages, "ru", "title")).toBe("Зарплата");
  });

  it("follow the person's language inside React", () => {
    function Title() {
      const t = useFeatureT(messages);
      return <h1>{t("payslips", { count: 5 })}</h1>;
    }
    render(
      <I18nProvider lang="ru">
        <Title />
      </I18nProvider>,
    );
    expect(screen.getByRole("heading").textContent).toBe("5 расчётных листов");
  });

  it("check keys at compile time", () => {
    const en = featureTranslator(messages, "en");
    // @ts-expect-error: not a key of the feature or the app
    expect(en("no.such.key")).toBe("no.such.key");
    defineMessages({
      en: { a: "A" },
      // @ts-expect-error: Russian must have every English key
      ru: {},
      uz: { a: "A" },
    });
  });
});
