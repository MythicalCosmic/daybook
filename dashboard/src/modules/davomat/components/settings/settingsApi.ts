/**
 * Queries the settings panels need beyond api.ts, sharing its keys (so a write that refreshes
 * `davomat` refreshes these too).
 */
import { useQuery } from "@tanstack/vue-query";
import { computed, toValue, type MaybeRefOrGetter } from "vue";

import { useCompanyId } from "@/stores/company";

import { davomatKeys, listUsers } from "../../api";

/** The users list only when the caller may read it (Telegram's "your own Telegram" for an admin). */
export function useUsersWhen(enabled: MaybeRefOrGetter<boolean>) {
  const cid = useCompanyId();
  return useQuery({
    queryKey: computed(() => davomatKeys.users(cid.value)),
    queryFn: ({ signal }) => listUsers(cid.value, signal),
    enabled: computed(() => cid.value > 0 && toValue(enabled)),
  });
}
