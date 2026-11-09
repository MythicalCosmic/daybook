<script setup lang="ts">
/**
 * The organization's brand on the public pages: its logo (or Davomat's mark) with its name, and
 * the product's name under it. Before the setup wizard ran there is no organization: the mark and
 * the product name alone.
 */
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";

import { editionInfo } from "@/core/edition";

import DavomatMark from "./DavomatMark.vue";

const props = withDefaults(defineProps<{ size?: "md" | "lg" }>(), { size: "md" });

const { t } = useI18n();
const organization = computed(() => editionInfo.value.organization);
const product = computed(() => editionInfo.value.product);
const logoFailed = ref(false);
watch(() => organization.value?.logo_url, () => (logoFailed.value = false));
const mark = computed(() => (props.size === "lg" ? 48 : 40));
</script>

<template>
  <div class="flex min-w-0 items-center gap-3">
    <img
      v-if="organization?.logo_url && !logoFailed"
      :src="organization.logo_url"
      alt=""
      class="shrink-0 rounded-[12px] object-cover shadow-xs ring-1 ring-line"
      :style="{ width: `${mark}px`, height: `${mark}px` }"
      @error="logoFailed = true"
    />
    <DavomatMark v-else :size="mark" />
    <div class="min-w-0">
      <p :class="['truncate font-bold leading-tight tracking-[-0.02em] text-fg', size === 'lg' ? 'text-xl' : 'text-lg']">{{ organization?.name ?? product }}</p>
      <p class="truncate text-sm text-muted">{{ organization ? product : t("davomat.brand.tagline") }}</p>
    </div>
  </div>
</template>
