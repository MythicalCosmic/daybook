/**
 * Whether Claude's helper walks with the person on every page (BuddyCompanion.vue): on by
 * default, kept per browser. Off from the switch on AI › Agents, the palette, or a long press on
 * the helper itself (it waves goodbye); on again from the same switch or the palette.
 */
import { ref, watch } from "vue";

import { isBoolean, readStored, writeStored } from "@/lib/storage";

const KEY = "aiBuddyEverywhere";

export const buddyEverywhere = ref(readStored(KEY, true, isBoolean));
watch(buddyEverywhere, (value) => writeStored(KEY, value));
