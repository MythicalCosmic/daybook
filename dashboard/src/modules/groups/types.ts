/** Shapes of `GET/PATCH O groups/` (`apps.groups.owner_api`), written by hand from the serializers. */
import type { CompanyFeature } from "@/core/features";

export type GroupEventKey =
  | "daily_done"
  | "tasks_done"
  | "late"
  | "members"
  | "morning"
  | "evening"
  | "attendance"
  | "shifts"
  | "cash"
  | "sales"
  | "celebrations"
  | "kudos";

export interface GroupEvent {
  key: GroupEventKey;
  label: string;
  /** The module the event belongs to, or null for the task events. */
  feature: CompanyFeature | null;
  on: boolean;
  /** False while its module is switched off (it can still be switched off, not on). */
  available: boolean;
}

export interface Ref {
  id: number;
  name: string;
}

export interface TelegramGroup {
  id: number;
  title: string;
  chat_id: number;
  is_active: boolean;
  events: GroupEvent[];
  /** Empty: news about everyone. */
  positions: Ref[];
  /** Empty: news from every branch. */
  branches: Ref[];
  linked_by: Ref | null;
  connected_at: string;
  updated_at: string;
}

export interface GroupsList {
  results: TelegramGroup[];
  /** Telegram's "add this bot to a group" link; empty without a bot username. */
  connect_link: string;
  bot_username: string;
  /** Events about one person, which a positions filter narrows. */
  person_events: GroupEventKey[];
  options: { positions: Ref[]; branches: Ref[] };
}

export interface GroupPatch {
  events?: GroupEventKey[];
  position_ids?: number[];
  branch_ids?: number[];
}
