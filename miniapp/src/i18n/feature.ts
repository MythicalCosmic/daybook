/**
 * Translations that live in a feature folder.
 *
 * A feature writes its strings once, in English, Russian and Uzbek, next to its screens:
 *
 *   // features/wallet/messages.ts
 *   export const messages = defineMessages({
 *     en: { "title": "Pay", "payslips_one": "{count} payslip", "payslips_other": "{count} payslips" },
 *     ru: { "title": "Зарплата", "payslips_one": "…", "payslips_few": "…", "payslips_many": "…", "payslips_other": "…" },
 *     uz: { "title": "Maosh", "payslips_one": "…", "payslips_other": "…" },
 *   });
 *
 *   // in a component
 *   const t = useFeatureT(messages);   // or useFeatureT(walletFeature)
 *   t("payslips", { count: 3 });       // typed: the feature's keys plus the app's own
 *
 * Lookups go feature (person's language) → feature English → app dictionary → app English, so
 * shared words such as "common.retry" need no copy. `src/i18n/parity.test.ts` checks that every
 * feature has the same keys and placeholders in all three languages.
 */

import { useMemo } from "react";

import { DICTIONARIES, translateFrom, useI18n, type Key, type Lang, type PluralBase, type PluralKey, type Vars } from ".";

type RussianExtra<K extends string> = `${PluralBase<K>}_${"few" | "many"}`;

export type FeatureMessages<K extends string> = {
  en: Record<K, string>;
  /** Russian also needs the _few and _many forms of every plural key. */
  ru: Record<NoInfer<K>, string> & Partial<Record<RussianExtra<NoInfer<K>>, string>>;
  uz: Record<NoInfer<K>, string>;
};

/** Typing helper: checks that Russian and Uzbek have exactly the English keys. */
export function defineMessages<K extends string>(messages: FeatureMessages<K>): FeatureMessages<K> {
  return messages;
}

export type FeatureTranslate<K extends string> = (key: K | PluralBase<K> | Key | PluralKey, vars?: Vars) => string;

type MessageSource<K extends string> = FeatureMessages<K> | { messages: FeatureMessages<K> };

const messagesOf = <K extends string>(source: MessageSource<K>): FeatureMessages<K> =>
  "messages" in source ? source.messages : source;

/** A translator for one feature in one language (outside React, for tests and builders). */
export function featureTranslator<K extends string>(source: MessageSource<K>, lang: Lang): FeatureTranslate<K> {
  const messages = messagesOf(source);
  const chain = [messages[lang], messages.en, DICTIONARIES[lang], DICTIONARIES.en] as Partial<Record<string, string>>[];
  return (key, vars) => translateFrom(chain, lang, key, vars);
}

/** One string from a feature's dictionaries when the keys aren't known statically (registry hosts). */
export function featureText(
  messages: { en: Partial<Record<string, string>>; ru: Partial<Record<string, string>>; uz: Partial<Record<string, string>> },
  lang: Lang,
  key: string,
  vars?: Vars,
): string {
  return translateFrom([messages[lang], messages.en, DICTIONARIES[lang], DICTIONARIES.en], lang, key, vars);
}

/** The feature's translator in the person's language. */
export function useFeatureT<K extends string>(source: MessageSource<K>): FeatureTranslate<K> {
  const { lang } = useI18n();
  const messages = messagesOf(source);
  return useMemo(() => featureTranslator(messages, lang), [messages, lang]);
}
