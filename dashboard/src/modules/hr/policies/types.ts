/**
 * Shapes of the policy endpoints (backend/apps/hr/policies/serializers.py), written by hand until
 * the lead regenerates the owner schema.
 */

export const POLICY_CATEGORIES = ["dispensing", "storage", "safety", "conduct", "other"] as const;
export type PolicyCategory = (typeof POLICY_CATEGORIES)[number];

export const SIGNATURE_STATES = ["waiting", "late", "signed"] as const;
export type SignatureState = (typeof SIGNATURE_STATES)[number];
/** Where a person stands on one of their policies (a policy asking no signature is only to read). */
export type PolicyStanding = SignatureState | "to_read";

export type PolicyView = "active" | "drafts" | "archived";
export type PolicyFileType = "pdf" | "image";

export interface PolicyNamed {
  id: number;
  name: string;
}

export interface PolicyBranch {
  id: number;
  name: string;
  code: string;
}

export interface PolicyPerson {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface PolicyTally {
  total: number;
  signed: number;
  waiting: number;
  late: number;
}

export interface PolicyVersionRef {
  id: number;
  number: number;
  published_at: string | null;
  asks_again: boolean;
}

export interface PolicyDraftRef {
  id: number;
  number: number;
  updated_at: string;
}

export interface Policy {
  id: number;
  title: string;
  category: PolicyCategory;
  requires_ack: boolean;
  ack_within_days: number;
  is_active: boolean;
  positions: PolicyNamed[];
  branches: PolicyBranch[];
  /** The version in force. */
  version: PolicyVersionRef | null;
  /** The version signatures are asked for (a small edit after it keeps them). */
  ack_number: number | null;
  draft: PolicyDraftRef | null;
  /** Among the people in the viewer's scope; null while nobody is asked. */
  tally: PolicyTally | null;
  /** The deadline of those asked when that version came out. */
  due_on: string | null;
  can_change: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyVersion {
  id: number;
  number: number;
  change_note: string;
  asks_again: boolean;
  published_at: string | null;
  published_by: string | null;
  is_draft: boolean;
  has_file: boolean;
  file_type: PolicyFileType | null;
  created_at: string;
  updated_at: string;
}

export interface PolicyVersionDetail extends PolicyVersion {
  body: string;
  body_text: string;
  /** A signed link, valid for minutes. */
  file_url: string | null;
}

export interface PolicyDetail extends Policy {
  versions: PolicyVersion[];
  audience_count: number;
  created_by: string | null;
}

export interface PolicyInput {
  title?: string;
  category?: PolicyCategory;
  position_ids?: number[];
  branch_ids?: number[];
  requires_ack?: boolean;
  ack_within_days?: number;
  is_active?: boolean;
  body?: string;
  change_note?: string;
}

export interface DraftInput {
  body?: string;
  change_note?: string;
  file?: File | null;
  remove_file?: boolean;
}

export interface PublishInput {
  asks_again: boolean;
  change_note?: string;
}

export interface Signature {
  member: PolicyPerson;
  position: PolicyNamed | null;
  branch: PolicyBranch | null;
  state: SignatureState;
  asked_at: string;
  due_on: string;
  signed_at: string | null;
  signed_number: number | null;
  reminded_at: string | null;
  /** When they signed an earlier version, if they did. */
  earlier_signed_at: string | null;
}

export interface SignatureParams {
  state?: SignatureState;
  q?: string;
  branch?: number[];
  page?: number;
  page_size?: number;
}

export interface PolicyAudience {
  count: number;
  people: PolicyPerson[];
}

export interface PolicyRef {
  id: number;
  title: string;
  category: PolicyCategory;
}

export interface PersonPolicyStanding {
  policy: PolicyRef;
  number: number;
  state: PolicyStanding;
  due_on: string | null;
  signed_at: string | null;
  signed_number: number | null;
}

export interface PersonPastSignature {
  policy: PolicyRef;
  number: number;
  signed_number: number | null;
  signed_at: string;
}

export interface PersonPolicies {
  current: PersonPolicyStanding[];
  history: PersonPastSignature[];
}
