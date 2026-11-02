/**
 * Icons for what the Flows catalog names (lucide names, contract §4.3–4.5): the catalog's own name
 * first, then the trigger's or step's key, then one for its kind. Only these icons are bundled.
 */
import {
  AlarmClock,
  Bell,
  Bot,
  CalendarClock,
  Camera,
  CircleCheckBig,
  ClipboardCheck,
  ClipboardList,
  FileText,
  GitBranch,
  HandHeart,
  ListPlus,
  MessageSquare,
  MessageSquareText,
  Mic,
  Moon,
  NotebookPen,
  PenLine,
  Plane,
  Receipt,
  ScanEye,
  Send,
  Sparkles,
  Split,
  SquarePlus,
  Sunrise,
  ThermometerSnowflake,
  UserPlus,
  Wallet,
  Workflow,
  Zap,
} from "@lucide/vue";
import type { Component } from "vue";

const BY_NAME: Record<string, Component> = {
  "alarm-clock": AlarmClock,
  bell: Bell,
  bot: Bot,
  "calendar-clock": CalendarClock,
  camera: Camera,
  "circle-check": CircleCheckBig,
  "circle-check-big": CircleCheckBig,
  "check-circle": CircleCheckBig,
  "clipboard-check": ClipboardCheck,
  "clipboard-list": ClipboardList,
  "file-text": FileText,
  "git-branch": GitBranch,
  "hand-heart": HandHeart,
  "list-plus": ListPlus,
  "message-square": MessageSquare,
  "message-square-text": MessageSquareText,
  "message-square-plus": MessageSquareText,
  mic: Mic,
  moon: Moon,
  "notebook-pen": NotebookPen,
  "pen-line": PenLine,
  pencil: PenLine,
  plane: Plane,
  receipt: Receipt,
  "scan-eye": ScanEye,
  send: Send,
  sparkles: Sparkles,
  split: Split,
  "square-plus": SquarePlus,
  "plus-square": SquarePlus,
  sunrise: Sunrise,
  "thermometer-snowflake": ThermometerSnowflake,
  "user-plus": UserPlus,
  "user-round-plus": UserPlus,
  wallet: Wallet,
  workflow: Workflow,
  zap: Zap,
};

/** The contract's keys, for a catalog that names an icon this file doesn't know. */
const BY_KEY: Record<string, Component> = {
  task_overdue: AlarmClock,
  task_completed: CircleCheckBig,
  schedule: CalendarClock,
  voice_note_ready: Mic,
  member_joined: UserPlus,
  time_off_approved: Plane,
  shift_closed: Wallet,
  ai_write: PenLine,
  ai_decide: Split,
  ai_check_photo: ScanEye,
  ai_summarize: FileText,
  send_message: Send,
  create_task: SquarePlus,
  add_comment: MessageSquareText,
  late_task_nudge: AlarmClock,
  late_task_to_head: Bell,
  photo_proof_check: ScanEye,
  evening_owner_summary: Moon,
  weekly_report: CalendarClock,
  welcome_new_employee: HandHeart,
  cash_mismatch_alert: Receipt,
};

export function flowIcon(name: string | null | undefined, key?: string | null, kind?: "trigger" | "ai" | "action" | "template"): Component {
  if (name && BY_NAME[name]) return BY_NAME[name];
  if (key && BY_KEY[key]) return BY_KEY[key];
  if (kind === "ai") return Sparkles;
  if (kind === "template") return Workflow;
  return Zap;
}
