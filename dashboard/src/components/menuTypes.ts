/** The entries of a DropdownMenu: actions, checkboxes, radio groups, submenus, separators, labels. */
import type { Component } from "vue";

export interface MenuAction {
  type?: "item";
  label: string;
  description?: string;
  icon?: Component;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}
export interface MenuCheckbox {
  type: "checkbox";
  label: string;
  icon?: Component;
  checked: boolean;
  disabled?: boolean;
  onToggle: (checked: boolean) => void;
}
export interface MenuRadio {
  type: "radio";
  value: string;
  options: Array<{ value: string; label: string; icon?: Component }>;
  onChange: (value: string) => void;
}
export interface MenuSub {
  type: "sub";
  label: string;
  icon?: Component;
  hint?: string;
  items: MenuEntry[];
}
export type MenuEntry = MenuAction | MenuCheckbox | MenuRadio | MenuSub | { type: "separator" } | { type: "label"; label: string };
