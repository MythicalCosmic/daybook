/**
 * Shapes of the knowledge base endpoints (`apps.knowledge.owner_api`, `serializers.py`), written by
 * hand like every module's types: dates are ISO strings, page bodies are HTML the server already
 * cleaned against its allow-list.
 */

export interface KbPerson {
  id: number;
  name: string;
  photo_url: string | null;
}

export interface KbRef {
  id: number;
  name: string;
}

export interface SpaceRef {
  id: number;
  name: string;
  icon: string;
}

export interface Space extends SpaceRef {
  archived_at?: string | null;
  description: string;
  audience_all: boolean;
  positions: KbRef[];
  position: number;
  archived: boolean;
  counts: { pages: number; published: number; drafts: number };
  created_at: string;
  updated_at: string;
}

export interface SpaceInput {
  name: string;
  icon: string;
  description: string;
  audience_all: boolean;
  position_ids: number[];
}

export interface TreeNodeData {
  id: number;
  title: string;
  emoji: string;
  published: boolean;
  require_ack: boolean;
  position: number;
  children: TreeNodeData[];
}

export interface ReadCount {
  read: number;
  total: number;
}

export interface PageRow {
  archived_at?: string | null;
  id: number;
  title: string;
  emoji: string;
  space: SpaceRef;
  parent_id: number | null;
  published: boolean;
  published_at: string | null;
  require_ack: boolean;
  version: number;
  archived: boolean;
  updated_at: string;
  updated_by: KbPerson | null;
  excerpt: string;
  /** Topics the page is about (docs/PLAN-LEARNING.md §2.5). */
  topics?: { id: number; name: string; color: string }[];
  /** People who opened it (managers' lists only), else null. */
  opened?: number | null;
  /** Who read the current version, out of the people it is for (managers only, published pages). */
  read: ReadCount | null;
}

export type LinkTarget = "task" | "routine";

export interface PageLink {
  id: number;
  target_type: LinkTarget;
  target_id: number;
  target_title: string;
  page: { id: number; title: string; emoji: string; space: SpaceRef };
  created_at: string;
}

export interface Crumb {
  id: number;
  title: string;
  emoji: string;
}

export interface PageDetail extends PageRow {
  body: string;
  ack_version: number;
  breadcrumbs: Crumb[];
  children: Array<Crumb & { published: boolean }>;
  links: PageLink[];
  my_ack: { version: number; at: string; current: boolean } | null;
  created_at: string;
  created_by: KbPerson | null;
  can_edit: boolean;
}

export interface PageCreateInput {
  space: number;
  parent?: number | null;
  title: string;
  emoji?: string;
  body?: string;
  require_ack?: boolean;
  publish?: boolean;
  notify?: boolean;
  topic_ids?: number[];
}

export interface PageSaveInput {
  title?: string;
  emoji?: string;
  body?: string;
  require_ack?: boolean;
  note?: string;
  base_version?: number | null;
  reread?: boolean;
  notify?: boolean;
  topic_ids?: number[];
}

export interface PageVersion {
  version: number;
  title: string;
  emoji: string;
  note: string;
  created_by: KbPerson | null;
  created_at: string;
  current: boolean;
}

export interface PageVersionDetail extends PageVersion {
  body: string;
}

export type ReaderStatus = "read" | "outdated" | "unread";

/** How someone read a page (docs/PLAN-LEARNING.md §4.1): visits, time, how far down. */
export interface ReaderView {
  opened: boolean;
  visits: number;
  seconds: number;
  scrolled: number;
  version: number | null;
  first_at: string | null;
  last_at: string | null;
}

export interface Reader {
  member: KbPerson & { position: string | null; branch: string | null };
  status: ReaderStatus;
  version: number | null;
  at: string | null;
  view?: ReaderView;
}

export interface Readers {
  counts: Record<ReaderStatus, number> & { opened?: number };
  results: Reader[];
}

export interface Target {
  type: LinkTarget;
  id: number;
  title: string;
  subtitle: string;
}

export interface UploadedImage {
  id: number;
  url: string;
  width: number;
  height: number;
}

export interface Overview {
  counts: {
    spaces: number;
    /** Spaces everyone in the company reads. */
    spaces_everyone: number;
    pages: number;
    published: number;
    /** Published pages changed in the last seven days. */
    changed_week: number;
    drafts: number;
    require_ack: number;
    /** Pages the caller still has to confirm. */
    to_read: number;
    /** Managers: must-read pages not everyone confirmed, and the confirmations missing. */
    attention: number;
    awaiting: number;
  };
  attention: PageRow[];
  recent: PageRow[];
  to_read: PageRow[];
}

export interface KnowledgeSettings {
  notify_on_publish: boolean;
  remind_unread_after_hours: number;
}

export interface PageListParams {
  q?: string;
  space?: number | null;
  status?: "published" | "draft" | "archived" | null;
  require_ack?: boolean;
  ordering?: string;
  page?: number;
  page_size?: number;
}
