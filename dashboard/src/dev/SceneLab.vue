<script setup lang="ts">
/**
 * Development only, at /dashboard/_scene: an agent's room (AgentScene) as its page shows it.
 * ?variant=hr|claude|voice|morning|deadline|photo ?state=working|idle|asleep ?night=1 ?theme=dark
 * ?all=1 shows every agent in each state.
 */
import { computed, onMounted } from "vue";
import { useRoute } from "vue-router";

import AgentScene from "@/modules/ai/components/AgentScene.vue";
import type { SceneState } from "@/modules/ai/scene";

const route = useRoute();
const variant = computed(() => String(route.query.variant ?? "hr"));
const state = computed(() => (["working", "idle", "asleep"].includes(String(route.query.state)) ? String(route.query.state) : "working") as SceneState);
const night = computed(() => route.query.night === "1");
const all = computed(() => route.query.all === "1");
const LINES = [
  "Hujjatlar: 3 ta muddati yaqin",
  "Shartnoma: Jasur, 21 kun qoldi",
  "Sinov muddati: Kamola, 5 kun",
  "Ertalabki xulosa yuborildi",
  "Ish haqi: oktabr tayyor",
];

onMounted(() => {
  document.documentElement.dataset.theme = route.query.theme === "dark" ? "dark" : "light";
});
</script>

<template>
  <main class="min-h-screen bg-bg p-4 md:p-8">
    <div v-if="all" class="grid gap-4 md:grid-cols-3">
      <template v-for="kind in ['working', 'idle', 'asleep'] as const" :key="kind">
        <AgentScene v-for="name in ['hr', 'voice', 'morning', 'deadline', 'photo', 'claude']" :key="`${kind}-${name}`" :variant="name" :state="kind" :night="night" :lines="LINES" :label="`${name} ${kind}`" class="!h-[220px]" />
      </template>
    </div>
    <AgentScene v-else :variant="variant" :state="state" :night="night" :lines="LINES" :label="`${variant} ${state}`" />
  </main>
</template>
