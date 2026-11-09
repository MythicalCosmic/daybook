// Training screens against a stubbed API: the helpers (clock, ranges strip, YouTube links), the
// resumable upload (resumes from the server's offset, retries, finishes), the overview, a course's
// steps and People tab, a lesson's "Who watched", the people grid and the Today tile.
// The registry first, as in the app (core/modules loads every module's index.ts).
import "@/core/modules";

import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type RouteRecordRaw } from "vue-router";

import { ApiError } from "@/api/http";
import { i18n, mergeModuleMessages, setLanguage } from "@/i18n";
import { useCompanyStore } from "@/stores/company";
import { useSessionStore } from "@/stores/session";
import { company, json, me } from "@/test/fixtures";
import { mountWithProviders as mountRaw } from "@/test/plugins";

import en from "../i18n/en.json";
import { clock, minutesOf, nextCertificate, segments, youtubeId } from "../lib";
import CoursePage from "../pages/CoursePage.vue";
import LessonPage from "../pages/LessonPage.vue";
import OverviewPage from "../pages/OverviewPage.vue";
import PeoplePage from "../pages/PeoplePage.vue";
import { routes } from "../routes";
import type { ChunkResult, CourseDetail, LessonDetail, Overview, PeopleGrid, Video, Viewers } from "../types";
import { sendFile, type UploadApi } from "../upload";
import ComplianceWidget from "../widgets/ComplianceWidget.vue";

vi.setConfig({ testTimeout: 20_000 });

const mounted: Array<{ unmount: () => void }> = [];
const mountWithProviders: typeof mountRaw = (component, options) => {
  const result = mountRaw(component, options);
  mounted.push(result.wrapper);
  return result;
};

interface Call {
  method: string;
  path: string;
  body: unknown;
}

class NoResize {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function stub(routesByCall: Record<string, (call: Call) => Response>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("ResizeObserver", NoResize);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^.*\/api\/v1\/owner\/companies\/1\//, "").split("?")[0]!;
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method: init?.method ?? "GET", path, body };
      calls.push(call);
      return routesByCall[`${call.method} ${path}`]?.(call) ?? json([], 200);
    }),
  );
  return calls;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) await flushPromises();
}

async function pageApp(path: string) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useSessionStore().me = me([company({ features: ["learning"] })]);
  useCompanyStore().setCurrent(1);
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/c/:companyId", children: routes.map((route) => ({ ...route, component: { render: () => null } }) as RouteRecordRaw) },
      { path: "/:any(.*)*", component: { render: () => null } },
    ],
  });
  await router.push(path);
  setLanguage("en");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { plugins: [pinia, router, i18n, [VueQueryPlugin, { queryClient: client }]] as never };
}

beforeEach(() => {
  mergeModuleMessages("learning", { en, ru: en, uz: en });
  localStorage.clear();
});

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

const person = (id: number, name: string) => ({ id, name, photo_url: null, position: "Farmatsevt", branch: "Chilonzor" });

describe("helpers", () => {
  it("formats lengths and minutes", () => {
    expect(clock(65)).toBe("1:05");
    expect(clock(3723)).toBe("1:02:03");
    expect(minutesOf(10)).toBe(1);
    expect(minutesOf(0)).toBe(0);
    expect(nextCertificate("DRX", 7, 2026)).toBe("DRX-2026-0007");
  });

  it("draws the watched ranges merged and clipped", () => {
    expect(segments([[0, 30], [20, 50], [90, 200]], 100)).toEqual([
      { left: 0, width: 50 },
      { left: 90, width: 10 },
    ]);
    expect(segments([[10, 10]], 100)).toEqual([]);
    expect(segments([[0, 10]], 0)).toEqual([]);
  });

  it("reads YouTube links like the server", () => {
    for (const link of ["https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=4", "youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"]) {
      expect(youtubeId(link)).toBe("dQw4w9WgXcQ");
    }
    for (const link of ["https://vimeo.com/1", "https://www.youtube.com/playlist?list=PL1", "javascript:alert(1)", ""]) {
      expect(youtubeId(link)).toBeNull();
    }
  });
});

describe("the upload", () => {
  const video = (overrides: Partial<Video> = {}): Video => ({
    id: 4,
    state: "uploading",
    error: "",
    original_name: "dars.mp4",
    original_bytes: 25,
    received_bytes: 0,
    chunk_bytes: 10,
    size_bytes: 0,
    duration_seconds: 0,
    width: 0,
    height: 0,
    url: null,
    poster_url: null,
    upload_expires_at: null,
    created_at: "2026-11-09T10:00:00Z",
    lessons: [],
    ...overrides,
  });

  it("sends the pieces in order, resumes from where the server stands and finishes", async () => {
    const offsets: number[] = [];
    let server = 0;
    let failedOnce = false;
    const api: UploadApi = {
      startUpload: async () => video(),
      chunk: async (_id, offset, piece): Promise<ChunkResult> => {
        offsets.push(offset);
        if (offset === 10 && !failedOnce) {
          failedOnce = true;
          server = 20; // the piece arrived, but the answer was lost
          throw new ApiError(0, null);
        }
        if (offset !== server) throw new ApiError(409, { received_bytes: server });
        server = offset + piece.size;
        return { id: 4, state: "uploading", received_bytes: server, original_bytes: 25 };
      },
      video: async () => video({ received_bytes: server }),
      finishUpload: async () => video({ state: "processing", received_bytes: 25 }),
    };
    const progress: number[] = [];
    const file = new File([new Uint8Array(25)], "dars.mp4", { type: "video/mp4" });
    const done = await sendFile(api, video(), file, { backoff: 1, onProgress: (p) => progress.push(p.percent) });
    expect(done.state).toBe("processing");
    expect(offsets).toEqual([0, 10, 20]);
    expect(progress.at(-1)).toBe(100);
  });

  it("gives up after a few failures", async () => {
    const api: UploadApi = {
      startUpload: async () => video(),
      chunk: async () => {
        throw new ApiError(0, null);
      },
      video: async () => video(),
      finishUpload: async () => video({ state: "processing" }),
    };
    const file = new File([new Uint8Array(5)], "dars.mp4");
    await expect(sendFile(api, video(), file, { retries: 2, backoff: 1 })).rejects.toBeInstanceOf(ApiError);
  });
});

const overview = (): Overview => ({
  compliance: { people: 6, completed: 4, overdue_people: 1, percent: 66 },
  late: [{ member: person(3, "Alisher Valiyev"), course: { id: 2, title: "Sovuq zanjir" }, due_at: "2026-11-01T18:59:59Z", days_late: 8 }],
  watched_week_seconds: 5400,
  activity: Array.from({ length: 14 }, (_, index) => ({ day: `2026-10-${String(27 + (index % 4)).padStart(2, "0")}`, seconds: index * 60, lessons: 0, courses: 0 })),
  courses: [{ id: 2, title: "Sovuq zanjir", emoji: "🧊", color: "sky", mandatory: true, people: 6, completed: 4, in_progress: 1, overdue: 1, percent: 66 }],
  counts: { courses: 4, published_courses: 4, lessons: 4, published_lessons: 4, processing_videos: 0 },
});

describe("the overview", () => {
  it("shows mandatory compliance, who is late and the courses", async () => {
    stub({ "GET learning/overview/": () => json(overview()) });
    const app = await pageApp("/c/1/learning");
    const { wrapper } = mountWithProviders(OverviewPage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain(en["learning.overview.compliance"]);
    expect(text).toContain("Alisher Valiyev");
    expect(text).toContain("8 days late");
    expect(text).toContain("Sovuq zanjir");
    expect(text).toContain("4 of 6");
  });

  it("puts a tile on Today with who is late, linking to each person", async () => {
    stub({ "GET learning/overview/": () => json(overview()) });
    const app = await pageApp("/c/1/learning");
    const { wrapper } = mountWithProviders(ComplianceWidget, { props: { companyId: 1 }, plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain(en["learning.overview.compliance"]);
    expect(text).toContain("4 of 6");
    expect(text).toContain("8 days late");
    expect(wrapper.find('a[href="/c/1/learning/people/3"]').text()).toBe("Alisher Valiyev");
    expect(wrapper.find('[role="progressbar"]').attributes("aria-valuenow")).toBe("66");
  });

  it("says when there is no mandatory training and when nobody is late", async () => {
    stub({ "GET learning/overview/": () => json({ ...overview(), compliance: { people: 0, completed: 0, overdue_people: 0, percent: 0 }, late: [] }) });
    const app = await pageApp("/c/1/learning");
    const { wrapper } = mountWithProviders(ComplianceWidget, { props: { companyId: 1 }, plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain(en["learning.grid.noCourses"]);

    stub({ "GET learning/overview/": () => json({ ...overview(), late: [] }) });
    const again = await pageApp("/c/1/learning");
    const second = mountWithProviders(ComplianceWidget, { props: { companyId: 1 }, plugins: again.plugins });
    await settle();
    expect(second.wrapper.text()).toContain(en["learning.overview.nobodyLate"]);
  });
});

const courseDetail = (overrides: Partial<CourseDetail> = {}): CourseDetail => ({
  id: 2,
  title: "Sovuq zanjir",
  emoji: "🧊",
  color: "sky",
  status: "published",
  mandatory: true,
  steps: 2,
  minutes: 12,
  due_days: 14,
  renew_months: 12,
  updated_at: "2026-11-09T10:00:00Z",
  stats: { people: 3, completed: 1, in_progress: 1, overdue: 1, percent: 33 },
  description: "",
  audience_all: false,
  positions: [{ id: 1, name: "Farmatsevt" }],
  branches: [],
  sequential: true,
  certificate: true,
  published_at: "2026-11-01T10:00:00Z",
  archived_at: null,
  step_list: [
    { id: 11, kind: "lesson", position: 0, required: true, target: { id: 5, title: "Muzlatgich va termometr", emoji: "🌡", status: "published", minutes: 7 } },
    { id: 12, kind: "quiz", position: 1, required: true, target: { id: 8, title: "Sovuq zanjir testi", emoji: "", status: "published", minutes: 5 } },
  ],
  ...overrides,
});

describe("a course", () => {
  it("lists its steps in order and moves one down", async () => {
    const calls = stub({
      "GET learning/courses/2/": () => json(courseDetail()),
      "POST learning/courses/2/steps/reorder/": () => json(courseDetail()),
    });
    const app = await pageApp("/c/1/learning/courses/2");
    const { wrapper } = mountWithProviders(CoursePage, { plugins: app.plugins });
    await settle();
    expect(wrapper.text()).toContain("Muzlatgich va termometr");
    expect(wrapper.text()).toContain("Sovuq zanjir testi");
    await wrapper.find(`button[aria-label="${en["learning.step.down"]}"]`).trigger("click");
    await settle();
    expect(calls.find((call) => call.path === "learning/courses/2/steps/reorder/")?.body).toEqual({ ids: [12, 11] });
  });

  it("shows its people with their progress and lateness", async () => {
    stub({
      "GET learning/courses/2/": () => json(courseDetail()),
      "GET learning/courses/2/people/": () =>
        json({
          counts: { open: 1, late: 1, completed: 1, closed: 0 },
          results: [
            {
              member: person(3, "Alisher Valiyev"),
              assignment: {
                id: 30,
                state: "in_progress",
                source: "audience",
                cycle: 1,
                percent: 50,
                steps_done: 1,
                steps_total: 2,
                assigned_at: "2026-10-18T05:00:00Z",
                due_at: "2026-11-01T18:59:59Z",
                late: true,
                days_late: 8,
                started_at: null,
                last_activity_at: null,
                completed_at: null,
                certificate_no: "",
                expires_at: null,
                exempt_reason: "",
              },
            },
          ],
        }),
    });
    const app = await pageApp("/c/1/learning/courses/2");
    const { wrapper } = mountWithProviders(CoursePage, { plugins: app.plugins });
    await settle();
    const tab = wrapper.findAll("button").find((button) => button.text().includes(en["learning.course.tabPeople"]));
    await tab!.trigger("click");
    await settle();
    expect(wrapper.text()).toContain("Alisher Valiyev");
    expect(wrapper.text()).toContain("8 days late");
    expect(wrapper.text()).toContain("1/2");
  });
});

const lessonDetail = (): LessonDetail => ({
  id: 5,
  title: "Muzlatgich va termometr",
  emoji: "🌡",
  status: "published",
  source: "youtube",
  duration_seconds: 300,
  video_state: null,
  topics: [{ id: 1, name: "Sovuq zanjir", color: "sky" }],
  viewers: { watched: 1, watching: 1 },
  updated_at: "2026-11-09T10:00:00Z",
  published_at: "2026-11-01T10:00:00Z",
  summary: "",
  notes: "<p>+2…+8</p>",
  youtube_id: "dQw4w9WgXcQ",
  video: null,
  transcript: "",
  audience_all: true,
  positions: [],
  archived_at: null,
  courses: [{ id: 2, name: "Sovuq zanjir" }],
});

describe("a lesson", () => {
  it("previews its YouTube video and shows who watched what", async () => {
    const viewers: Viewers = {
      counts: { never: 1, watching: 1, watched: 1 },
      duration_seconds: 300,
      results: [
        { member: person(3, "Nigora Azimova"), state: "watching", percent: 40, ranges: [[0, 60], [120, 180]], watched_seconds: 120, spent_seconds: 150, sessions: 2, first_at: "2026-11-08T10:00:00Z", last_at: "2026-11-08T10:05:00Z", completed_at: null },
        { member: person(4, "Jasur Tursunov"), state: "never", percent: 0, ranges: [], watched_seconds: 0, spent_seconds: 0, sessions: 0, first_at: null, last_at: null, completed_at: null },
      ],
    };
    stub({ "GET learning/lessons/5/": () => json(lessonDetail()), "GET learning/lessons/5/viewers/": () => json(viewers), "GET knowledge/topics/": () => json([]) });
    const app = await pageApp("/c/1/learning/lessons/5");
    const { wrapper } = mountWithProviders(LessonPage, { plugins: app.plugins });
    await settle();
    expect(wrapper.find("iframe").attributes("src")).toContain("youtube-nocookie.com/embed/dQw4w9WgXcQ");
    const tab = wrapper.findAll("button").find((button) => button.text().includes(en["learning.lesson.tabViewers"]));
    await tab!.trigger("click");
    await settle();
    expect(wrapper.text()).toContain("Nigora Azimova");
    expect(wrapper.text()).toContain(en["learning.watched.never"]);
    const strip = wrapper.find('[role="img"]');
    expect(strip.findAll("span")).toHaveLength(2);
  });
});

describe("the people grid", () => {
  it("shows each person's state in each mandatory course", async () => {
    const grid: PeopleGrid = {
      courses: [{ id: 2, title: "Sovuq zanjir", emoji: "🧊", color: "sky" }],
      rows: [
        { member: person(3, "Alisher Valiyev"), cells: { "2": { assignment_id: 30, state: "in_progress", percent: 50, due_at: "2026-11-01T18:59:59Z", late: true } }, done: 0, total: 1, late: 1 },
        { member: person(5, "Madina Saidova"), cells: { "2": { assignment_id: 31, state: "completed", percent: 100, due_at: null, late: false } }, done: 1, total: 1, late: 0 },
      ],
    };
    stub({ "GET learning/people/": () => json(grid) });
    const app = await pageApp("/c/1/learning/people");
    const { wrapper } = mountWithProviders(PeoplePage, { plugins: app.plugins });
    await settle();
    const text = wrapper.text();
    expect(text).toContain("Madina Saidova");
    expect(text).toContain(en["learning.grid.late"]);
    expect(text).toContain(en["learning.state.completed"]);
  });
});
