<script setup lang="ts">
/**
 * Renders what other modules registered for an extension point (plan §6.6), each isolated: a
 * component that throws is dropped (and logged) instead of breaking the page that hosts it.
 *
 *   <ExtensionSlot name="tasks.toolbar" :context="{ companyId, filters }" />
 */
import { computed, defineComponent, h, onErrorCaptured, ref, type PropType } from "vue";

import { extensionsFor } from "@/core/extensions";
import type { ExtensionPoint } from "@/core/modules";
import { useCompanyStore } from "@/stores/company";

const props = withDefaults(
  defineProps<{
    name: ExtensionPoint;
    context?: Record<string, unknown>;
    /** Wrapper element; "none" renders the components side by side with no wrapper. */
    as?: string;
  }>(),
  { context: () => ({}), as: "div" },
);

const company = useCompanyStore();
const entries = computed(() => extensionsFor(props.name, company.current));

/** One boundary per extension, so one failure hides only itself. */
const Boundary = defineComponent({
  name: "ExtensionBoundary",
  props: { label: { type: String, required: true }, render: { type: Function as PropType<() => ReturnType<typeof h>>, required: true } },
  setup(boundaryProps) {
    const failed = ref(false);
    onErrorCaptured((error) => {
      failed.value = true;
      console.error(`[extension] ${boundaryProps.label} failed`, error);
      return false;
    });
    return () => (failed.value ? null : boundaryProps.render());
  },
});
</script>

<template>
  <template v-if="entries.length">
    <template v-if="as === 'none'">
      <Boundary
        v-for="entry in entries"
        :key="entry.key"
        :label="`${name} · ${entry.moduleId}`"
        :render="() => h(entry.component, { context: props.context })"
      />
    </template>
    <component :is="as" v-else :data-extension-slot="name">
      <Boundary
        v-for="entry in entries"
        :key="entry.key"
        :label="`${name} · ${entry.moduleId}`"
        :render="() => h(entry.component, { context: props.context })"
      />
    </component>
  </template>
</template>
