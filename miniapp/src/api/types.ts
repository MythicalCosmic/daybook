import type { components } from "./schema";

type Schemas = components["schemas"];

export type Me = Schemas["Me"];
export type Membership = Schemas["Membership"];
export type Position = Schemas["Position"];
export type Task = Schemas["Task"];
export type TaskStatus = Schemas["TaskStatusEnum"];
export type TaskAction = Schemas["ActionsEnum"];
export type Comment = Schemas["Comment"];
export type Activity = Schemas["Activity"];
export type Summary = Schemas["Summary"];
export type Day = Schemas["Day"];
export type MemberBrief = Schemas["MemberBrief"];
export type Language = Schemas["LanguageEnum"];
export type Repeat = Schemas["RepeatEnum"];
export type Proof = Schemas["ProofEnum"];

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] };
