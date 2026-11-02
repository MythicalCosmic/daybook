/**
 * What happens in the company, turned into the helpers' reactions on the Agents page (buddyBus):
 * - a voice note being written down: the voice tasks chibi listens (sound waves) and is pleased
 *   when it became tasks (the newest notes, every 5 s while the page is open);
 * - a task gone late (the pulse's late count went up): the deadline watcher's clock rings;
 * - a task finished (the tasks changed and today's done count went up): everyone cheers;
 * - agent activity as it arrives (a late task told to someone: the clock rings and Claude goes to
 *   see; a checked photo; a morning plan sent).
 * Nothing reacts to what happened before the page opened. Only while `enabled` (AI on).
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, onScopeDispose, toValue, watch, type MaybeRefOrGetter } from "vue";

import type { Pulse } from "@/api/types";
import { pulse } from "@/core/pulse";

import { aiApi, aiKeys, useActivityFeed, useCompanyId } from "../api";
import { activityReactions, draftCues, pulseCues } from "../lib";
import type { DraftStatus } from "../types";
import { cue } from "./buddyBus";

export const BUDDY_DRAFTS_POLL_MS = 5000;

export function useBuddyCues(enabled: MaybeRefOrGetter<boolean>): void {
  const cid = useCompanyId();
  const on = computed(() => toValue(enabled) && cid.value > 0);

  // Voice notes.
  const drafts = useQuery({
    queryKey: computed(() => [...aiKeys.drafts(cid.value, { page_size: 8 }), "buddy"]),
    queryFn: ({ signal }) => aiApi.drafts(cid.value, { page_size: 8 }, signal),
    enabled: on,
    refetchInterval: BUDDY_DRAFTS_POLL_MS,
  });
  let seen: Map<number, DraftStatus> | null = null;
  watch(
    () => drafts.data.value,
    (page) => {
      if (!page) return;
      const next = draftCues(seen, page.results);
      seen = next.seen;
      if (next.done) cue("voice_tasks", "hearts");
      else if (next.listen) cue("voice_tasks", "listen");
    },
  );

  // Late and finished tasks, from the pulse the shell already polls.
  let previous: Pick<Pulse, "counters" | "versions"> | null = null;
  let doneToday: number | null = null;
  const controller = new AbortController();
  onScopeDispose(() => controller.abort());
  async function countDone(): Promise<number | null> {
    try {
      return (await aiApi.tasksDoneToday(cid.value, controller.signal)).done_today;
    } catch {
      return null; // no permission, or offline: no cheering
    }
  }
  watch(
    [pulse, on],
    async ([next, active]) => {
      const cues = pulseCues(previous, next);
      previous = next;
      if (!active) return;
      if (cues.late) cue("deadline_watcher", "ring");
      if (doneToday === null || cues.tasksChanged) {
        const count = await countDone();
        if (count !== null && doneToday !== null && count > doneToday) cue("", "cheer");
        if (count !== null) doneToday = count;
      }
    },
    { immediate: true },
  );

  // Agent activity as it arrives.
  const feed = useActivityFeed(() => null, { limit: 10, live: on });
  watch(feed.fresh, (ids) => {
    if (!toValue(on) || !ids.length) return;
    const arrived = feed.items.value.filter((item) => ids.includes(item.id));
    for (const reaction of activityReactions(arrived)) cue(reaction.key, reaction.action, reaction.visit ?? false);
  });
}
