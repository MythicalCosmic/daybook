/** Icons the HR pages share: one per contract action, the same in menus, buttons and dialogs. */
import { BadgeCheck, CalendarPlus, CircleSlash, Clock4, FileDown, Play } from "@lucide/vue";
import type { Component } from "vue";

import type { ContractAction } from "./types";

export const ACTION_ICONS: Record<ContractAction, Component> = {
  activate: Play,
  renew: CalendarPlus,
  terminate: CircleSlash,
  "pass-probation": BadgeCheck,
  "extend-probation": Clock4,
  "generate-pdf": FileDown,
};
