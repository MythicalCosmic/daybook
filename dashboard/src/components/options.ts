/** The one option shape every select, combobox, multiselect, filter and picker takes. */
import type { Component } from "vue";

export type OptionValue = string | number;

export interface SelectOption<V extends OptionValue = OptionValue> {
  value: V;
  label: string;
  /** Second line under the label ("Cashier · Chilonzor"). */
  description?: string;
  icon?: Component;
  /** A colored dot before the label (status, category, label colors); any CSS color or token. */
  color?: string;
  /** A person or company avatar before the label. */
  avatar?: { name: string; src?: string | null };
  disabled?: boolean;
  /** Options with the same group are listed under that heading. */
  group?: string;
  /** Extra words the search matches (other spellings, codes). */
  keywords?: string[];
}

/** Async option source for ComboBox, MultiSelect and the pickers: called with the query (debounced). */
export type OptionSource<V extends OptionValue = OptionValue> = (query: string, signal: AbortSignal) => Promise<SelectOption<V>[]>;

/** Case- and accent-insensitive match on label, description and keywords, for client-side lists. */
export function matchOption(option: SelectOption, query: string): boolean {
  const needle = normalize(query);
  if (!needle) return true;
  const haystack = normalize([option.label, option.description ?? "", ...(option.keywords ?? [])].join(" "));
  return needle.split(/\s+/).every((word) => haystack.includes(word));
}

export function normalize(text: string): string {
  return text
    .toLocaleLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[‘’ʻʼ'`]/g, "");
}

/** Groups options under their `group` heading, keeping first-seen order. */
export function groupOptions<V extends OptionValue>(options: readonly SelectOption<V>[]): Array<{ label: string | null; options: SelectOption<V>[] }> {
  const groups: Array<{ label: string | null; options: SelectOption<V>[] }> = [];
  for (const option of options) {
    const label = option.group ?? null;
    let group = groups.find((g) => g.label === label);
    if (!group) {
      group = { label, options: [] };
      groups.push(group);
    }
    group.options.push(option);
  }
  return groups;
}
