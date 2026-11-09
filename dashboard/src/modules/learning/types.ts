/**
 * Shapes of the learning owner API (backend/apps/learning/owner_api_courses.py), hand-written
 * until the lead regenerates the schema types. Times are ISO strings; dates `YYYY-MM-DD`.
 */

export type Status = "draft" | "published" | "archived";
export type AssignmentState = "assigned" | "in_progress" | "completed" | "exempt" | "cancelled";
export type AssignmentSource = "audience" | "manual" | "tutor" | "self" | "renewal";
export type StepKind = "lesson" | "page" | "quiz";
export type LessonSource = "upload" | "youtube";
export type VideoState = "uploading" | "processing" | "ready" | "failed";
export type ViewerState = "never" | "watching" | "watched";
/** A course's People tab filter. */
export type PeopleBucket = "open" | "late" | "completed" | "closed";

export interface Ref {
  id: number;
  name: string;
}

export interface PersonRef {
  id: number;
  name: string;
  photo_url: string | null;
  position: string | null;
  branch: string | null;
}

export interface TopicRef {
  id: number;
  name: string;
  color: string;
}

export interface Stats {
  people: number;
  completed: number;
  in_progress: number;
  overdue: number;
  percent: number;
}

export interface CourseRow {
  id: number;
  title: string;
  emoji: string;
  color: string;
  status: Status;
  mandatory: boolean;
  steps: number;
  minutes: number;
  due_days: number | null;
  renew_months: number | null;
  updated_at: string;
  stats: Stats;
}

export interface StepTarget {
  id: number;
  title: string;
  emoji: string;
  status: Status;
  minutes: number | null;
}

export interface CourseStep {
  id: number;
  kind: StepKind;
  position: number;
  required: boolean;
  target: StepTarget;
}

export interface CourseDetail extends CourseRow {
  description: string;
  audience_all: boolean;
  positions: Ref[];
  branches: Ref[];
  sequential: boolean;
  certificate: boolean;
  published_at: string | null;
  archived_at: string | null;
  step_list: CourseStep[];
}

export interface CourseInput {
  title?: string;
  emoji?: string;
  color?: string;
  description?: string;
  mandatory?: boolean;
  audience_all?: boolean;
  position_ids?: number[];
  branch_ids?: number[];
  due_days?: number | null;
  renew_months?: number | null;
  sequential?: boolean;
  certificate?: boolean;
}

export interface AssignmentRow {
  id: number;
  state: AssignmentState;
  source: AssignmentSource;
  cycle: number;
  percent: number;
  steps_done: number;
  steps_total: number;
  assigned_at: string;
  due_at: string | null;
  late: boolean;
  days_late: number;
  started_at: string | null;
  last_activity_at: string | null;
  completed_at: string | null;
  certificate_no: string;
  expires_at: string | null;
  exempt_reason: string;
}

export interface CoursePerson {
  assignment: AssignmentRow;
  member: PersonRef;
}

export interface CoursePeople {
  counts: Record<PeopleBucket, number>;
  results: CoursePerson[];
}

export interface Candidate extends PersonRef {
  assigned: boolean;
}

export interface Pick {
  id: number;
  title: string;
  emoji: string;
  status: Status;
}

export interface Video {
  id: number;
  state: VideoState;
  error: string;
  original_name: string;
  original_bytes: number;
  received_bytes: number;
  chunk_bytes: number;
  size_bytes: number;
  duration_seconds: number;
  width: number;
  height: number;
  url: string | null;
  poster_url: string | null;
  upload_expires_at: string | null;
  created_at: string;
  lessons: Ref[];
}

export interface ChunkResult {
  id: number;
  state: VideoState;
  received_bytes: number;
  original_bytes: number;
}

export interface LessonRow {
  id: number;
  title: string;
  emoji: string;
  status: Status;
  source: LessonSource;
  duration_seconds: number;
  video_state: VideoState | null;
  topics: TopicRef[];
  viewers: { watched: number; watching: number };
  updated_at: string;
  published_at: string | null;
}

/** Why a video can't be written down now ("" when it can). */
export type TranscriptionBlock = "" | "no_video" | "too_long" | "ai_off" | "no_speech";

/** Writing the uploaded video down (the speech service, a piece at a time). */
export interface Transcription {
  state: "" | "working" | "failed";
  done: number;
  total: number;
  /** The failure's code: no_video, no_sound, nothing_heard, audio_unreadable, speech_unavailable, … */
  error: string;
  unavailable: TranscriptionBlock;
}

export interface LessonDetail extends LessonRow {
  summary: string;
  notes: string;
  youtube_id: string;
  video: Video | null;
  transcript: string;
  transcription: Transcription;
  audience_all: boolean;
  positions: Ref[];
  archived_at: string | null;
  courses: Ref[];
}

export interface LessonInput {
  title?: string;
  emoji?: string;
  summary?: string;
  notes?: string;
  source?: LessonSource;
  video_id?: number | null;
  youtube?: string;
  topic_ids?: number[];
  audience_all?: boolean;
  position_ids?: number[];
  transcript?: string;
}

export interface Viewer {
  member: PersonRef;
  state: ViewerState;
  percent: number;
  ranges: [number, number][];
  watched_seconds: number;
  spent_seconds: number;
  sessions: number;
  first_at: string | null;
  last_at: string | null;
  completed_at: string | null;
}

export interface Viewers {
  counts: Record<ViewerState, number>;
  duration_seconds: number;
  results: Viewer[];
}

export interface Overview {
  compliance: { people: number; completed: number; overdue_people: number; percent: number };
  late: { member: PersonRef; course: { id: number; title: string }; due_at: string; days_late: number }[];
  watched_week_seconds: number;
  activity: { day: string; seconds: number; lessons: number; courses: number }[];
  courses: (Stats & { id: number; title: string; emoji: string; color: string; mandatory: boolean })[];
  counts: { courses: number; published_courses: number; lessons: number; published_lessons: number; processing_videos: number };
}

export interface GridCell {
  assignment_id: number;
  state: AssignmentState;
  percent: number;
  due_at: string | null;
  late: boolean;
}

export interface PeopleGrid {
  courses: { id: number; title: string; emoji: string; color: string }[];
  rows: { member: PersonRef; cells: Record<string, GridCell | null>; done: number; total: number; late: number }[];
}

export interface PersonPage {
  member: PersonRef;
  summary: { open: number; completed: number; late: number; certificates: number; watched_seconds: number; lessons_watched: number };
  assignments: (AssignmentRow & { course: { id: number; title: string; emoji: string; mandatory: boolean } })[];
  lessons: {
    lesson: { id: number; title: string; emoji: string };
    percent: number;
    ranges: [number, number][];
    completed_at: string | null;
    last_at: string;
    spent_seconds: number;
    sessions: number;
  }[];
  pages: { page: { id: number; title: string; emoji: string }; visits: number; seconds: number; scrolled: number; version: number; last_at: string }[];
}

export interface LearningSettings {
  completion_percent: number;
  max_speed_percent: number;
  remind_before_days: number;
  escalate_after_days: number;
  certificates: boolean;
  certificate_prefix: string;
  next_certificate_number: number;
  catalog_for_staff: boolean;
  storage_limit_mb: number;
  storage_used_bytes: number;
}

export interface FileLink {
  url: string;
  name: string;
  expires_in: number;
}

/** knowledge/topics/ (the lead's endpoint), for the topic pickers. */
export interface Topic {
  id: number;
  name: string;
  color: string;
  description: string;
  position: number;
  archived: boolean;
  page_count: number;
  lesson_count: number;
  question_count: number;
}
