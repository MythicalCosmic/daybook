/**
 * The review of a ready draft, shared by the dictate dialog and the voice note drawer: the drafts
 * as editable copies (seeded once per draft, so a poll never overwrites what the person typed),
 * what still stops "Create", and the apply call with its outcome.
 */
import { computed, ref, watch, type Ref } from "vue";

import { useNow } from "@/lib/useNow";

import { useApplyDraft } from "./api";
import { applyBlockers, toApplyPayload, toEditable, type EditableDraft } from "./lib";
import type { AiDraft, ApplyResult } from "./types";

export function useReview(draft: Ref<AiDraft | null | undefined>) {
  const edits = ref<EditableDraft[]>([]);
  const result = ref<ApplyResult | null>(null);
  const now = useNow();
  let seeded: number | null = null;

  watch(
    draft,
    (value) => {
      if (!value || value.status !== "ready" || seeded === value.id) return;
      seeded = value.id;
      edits.value = toEditable(value);
      result.value = null;
    },
    { immediate: true },
  );

  const blockers = computed(() => applyBlockers(edits.value, now.value));
  const count = computed(() => blockers.value.count);
  const canApply = computed(() => blockers.value.count > 0 && blockers.value.untitled === 0 && blockers.value.problems === 0);

  const apply = useApplyDraft();
  async function create(): Promise<ApplyResult | null> {
    const current = draft.value;
    if (!current || !canApply.value || apply.isPending.value) return null;
    try {
      result.value = await apply.mutateAsync({ id: current.id, drafts: toApplyPayload(edits.value).drafts });
      return result.value;
    } catch {
      // The reason is a toast from the HTTP layer; the drafts stay as edited.
      return null;
    }
  }

  return { edits, blockers, count, canApply, create, result, applying: apply.isPending };
}

export type Review = ReturnType<typeof useReview>;

/** "Couldn't create" lines after apply: the kept drafts' titles at the failed indexes. */
export function failedTitles(edits: readonly EditableDraft[], result: ApplyResult | null): Array<{ title: string; detail: string }> {
  if (!result?.failed.length) return [];
  const kept = edits.filter((edit) => !edit.removed);
  return result.failed.map((failure) => ({ title: kept[failure.index]?.title ?? `#${failure.index + 1}`, detail: failure.detail }));
}
