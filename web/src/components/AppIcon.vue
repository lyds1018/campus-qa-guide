<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 18 });
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <template v-if="name === 'plus'">
      <path d="M12 5v14M5 12h14" />
    </template>
    <template v-else-if="name === 'arrow-right'">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </template>
    <template v-else-if="name === 'arrow-up-right'">
      <path d="M7 17 17 7M8 7h9v9" />
    </template>
    <template v-else-if="name === 'send'">
      <path d="m4 4 16 8-16 8 3-8-3-8Z" />
      <path d="M7 12h8" />
    </template>
    <template v-else-if="name === 'stop'">
      <rect x="7" y="7" width="10" height="10" rx="1.5" />
    </template>
    <template v-else-if="name === 'panel'">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </template>
    <template v-else-if="name === 'menu'">
      <path d="M4 7h16M4 12h16M4 17h16" />
    </template>
    <template v-else-if="name === 'close'">
      <path d="m6 6 12 12M18 6 6 18" />
    </template>
    <template v-else-if="name === 'download'">
      <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />
    </template>
    <template v-else-if="name === 'thumb-up'">
      <path d="M7 10v10H4V10h3Zm0 9h9.2a2 2 0 0 0 2-1.6l1.2-6A2 2 0 0 0 17.4 9H14l.6-3.2A2.2 2.2 0 0 0 10.4 4L7 10" />
    </template>
    <template v-else-if="name === 'thumb-down'">
      <path d="M7 14V4H4v10h3Zm0-9h9.2a2 2 0 0 1 2 1.6l1.2 6A2 2 0 0 1 17.4 15H14l.6 3.2A2.2 2.2 0 0 1 10.4 20L7 14" />
    </template>
    <template v-else-if="name === 'refresh'">
      <path d="M20 11a8 8 0 1 0-2.3 6.6M20 5v6h-6" />
    </template>
    <template v-else-if="name === 'book'">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5v-16Z" />
      <path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="m5 12 4.5 4.5L19 7" />
    </template>
    <template v-else-if="name === 'alert'">
      <path d="M12 8v5M12 17h.01" />
      <circle cx="12" cy="12" r="9" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="7" />
      <path d="m16.5 16.5 4 4" />
    </template>
    <template v-else-if="name === 'settings'">
      <path d="M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z" />
      <path d="m19 12 1.6-1.3-1.7-3-2 .7a7 7 0 0 0-2.2-1.3L14.4 5h-3.5l-.3 2.1a7 7 0 0 0-2.2 1.3l-2-.7-1.7 3L6.3 12l-1.6 1.3 1.7 3 2-.7a7 7 0 0 0 2.2 1.3l.3 2.1h3.5l.3-2.1a7 7 0 0 0 2.2-1.3l2 .7 1.7-3L19 12Z" />
    </template>
    <template v-else-if="name === 'chevron-down'">
      <path d="m6 9 6 6 6-6" />
    </template>
    <template v-else-if="name === 'history'">
      <path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" />
      <path d="M12 8v4l3 2" />
    </template>
    <template v-else-if="name === 'message'">
      <path d="M21 12a8 8 0 0 1-8 8H4l2.2-3.2A8 8 0 1 1 21 12Z" />
    </template>
    <template v-else-if="name === 'database'">
      <ellipse cx="12" cy="5.5" rx="7.5" ry="3" />
      <path d="M4.5 5.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6M4.5 11.5v6c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3v-6" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </template>
    <template v-else-if="name === 'shield'">
      <path d="M12 3 5 6v5c0 4.5 3 7.7 7 10 4-2.3 7-5.5 7-10V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </template>
    <template v-else-if="name === 'spark'">
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" />
    </template>
    <template v-else-if="name === 'file'">
      <path d="M6 3h8l4 4v14H6V3Z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </template>
    <template v-else-if="name === 'inbox'">
      <path d="M4 5h16v14H4V5Z" />
      <path d="M4 13h4l2 3h4l2-3h4" />
    </template>
    <template v-else-if="name === 'chart'">
      <path d="M4 20V4M4 20h16" />
      <path d="M8 16v-4M12 16V8M16 16v-6" />
    </template>
  </svg>
</template>
