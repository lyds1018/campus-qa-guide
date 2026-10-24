<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { me } from "../api/chat";
import type { Me } from "../api/types";
import AppIcon from "../components/AppIcon.vue";
import CatalogTab from "../components/admin/CatalogTab.vue";
import MetricsTab from "../components/admin/MetricsTab.vue";
import MonitorTab from "../components/admin/MonitorTab.vue";
import ReviewTab from "../components/admin/ReviewTab.vue";
import UploadTab from "../components/admin/UploadTab.vue";

const route = useRoute();
const router = useRouter();

const TABS = [
  { key: "upload", label: "入库与任务", brief: "上传、解析、重试", icon: "inbox", component: UploadTab },
  { key: "review", label: "审核与版本", brief: "发布、回滚、补向量", icon: "file", component: ReviewTab },
  { key: "catalog", label: "事项与词典", brief: "事项匹配、别名改写", icon: "book", component: CatalogTab },
  { key: "monitor", label: "看板与模型", brief: "运行指标、模型槽位", icon: "chart", component: MonitorTab },
  { key: "metrics", label: "评测与反馈", brief: "回归档案、学生反馈", icon: "shield", component: MetricsTab },
] as const;

const initial = TABS.some((item) => item.key === route.query.tab) ? String(route.query.tab) : "upload";
const tab = ref(initial);
const identity = ref<Me | null>(null);
const error = ref("");
const checking = ref(true);

const current = computed(() => TABS.find((item) => item.key === tab.value) ?? TABS[0]);
const denied = computed(() => Boolean(error.value) || (identity.value && identity.value.role !== "admin"));

function changeTab(key: string) {
  tab.value = key;
  // 深链便于把某个运营页直接发给同事
  void router.replace({ query: { ...route.query, tab: key } });
}

// 浏览器前进/后退时地址栏与页签保持一致
watch(
  () => route.query.tab,
  (value) => {
    if (typeof value === "string" && TABS.some((item) => item.key === value)) {
      tab.value = value;
    }
  },
);

onMounted(async () => {
  try {
    identity.value = await me();
  } catch (e) {
    error.value = (e as { detail?: string }).detail ?? "无法获取身份";
  } finally {
    checking.value = false;
  }
});
</script>

<template>
  <div class="admin-page">
    <div class="admin-shell">
      <header class="admin-head">
        <div>
          <p class="eyebrow">资料维护 · 发布管理</p>
          <h1 class="serif">知识运营</h1>
          <p class="head-lead">维护入库文档、发布版本与问答口径。所有变更仅影响当前演示环境。</p>
        </div>
        <div v-if="identity?.role === 'admin'" class="access-badge">
          <AppIcon name="shield" :size="17" />
          <div>
            <strong>管理员权限</strong>
            <small>写操作已开放</small>
          </div>
        </div>
      </header>

      <div v-if="checking" class="admin-loading">
        <span class="pending-dots"><i /><i /><i /></span>
        <span>正在验证访问权限</span>
      </div>

      <section v-else-if="denied" class="access-state">
        <span class="access-icon"><AppIcon name="shield" :size="24" /></span>
        <p class="eyebrow">访问受限</p>
        <h2 class="serif">这里需要管理员身份</h2>
        <p>
          {{
            identity?.role === "student"
              ? "当前以学生身份访问，运营接口不会返回数据。"
              : error || "未能确认当前账号的运营权限。"
          }}
        </p>
        <div class="access-actions">
          <RouterLink to="/chat" class="plain-link">返回问答</RouterLink>
          <span>可在右上角切换为「管理员」后重新进入。</span>
        </div>
      </section>

      <template v-else>
        <nav class="admin-tabs" aria-label="运营功能">
          <button
            v-for="(item, index) in TABS"
            :key="item.key"
            type="button"
            class="admin-tab"
            :class="{ active: tab === item.key }"
            :aria-current="tab === item.key ? 'page' : undefined"
            @click="changeTab(item.key)"
          >
            <span class="tab-index">{{ String(index + 1).padStart(2, "0") }}</span>
            <span class="tab-copy">
              <strong>{{ item.label }}</strong>
              <small>{{ item.brief }}</small>
            </span>
          </button>
        </nav>

        <div class="tab-heading">
          <div>
            <h2 class="serif">{{ current.label }}</h2>
            <p>{{ current.brief }}</p>
          </div>
          <span class="tab-rule" />
          <span class="tab-count">{{ String(TABS.indexOf(current) + 1).padStart(2, "0") }} / 05</span>
        </div>

        <main class="admin-body">
          <KeepAlive>
            <component :is="current.component" />
          </KeepAlive>
        </main>
      </template>
    </div>
  </div>
</template>

<style scoped>
.admin-page {
  min-height: calc(100dvh - var(--header-h));
  padding: 38px 28px 60px;
}

.admin-shell {
  width: min(1380px, 100%);
  margin: 0 auto;
}

.admin-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 26px;
  border-bottom: 1px solid var(--line-strong);
}

.admin-head h1 {
  margin: 0;
  font-size: clamp(30px, 3vw, 40px);
  line-height: 1.2;
}

.head-lead {
  max-width: 560px;
  margin: 10px 0 0;
  color: var(--ink-muted);
  font-size: 12.5px;
  line-height: 1.75;
}

.access-badge {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-raised);
  color: var(--primary);
}

.access-badge div {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
}

.access-badge strong {
  color: var(--ink-soft);
  font-size: 11px;
  font-weight: 600;
}

.access-badge small {
  color: var(--ink-faint);
  font-size: 9px;
}

.admin-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 0;
  border-bottom: 1px solid var(--line);
}

.admin-tab {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 17px 14px 16px;
  border: 0;
  border-right: 1px solid var(--line);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color 160ms ease;
}

.admin-tab:first-child {
  border-left: 1px solid var(--line);
}

.admin-tab:hover {
  background: var(--surface);
}

.admin-tab.active {
  background: var(--primary);
}

.tab-index {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.tab-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.tab-copy strong {
  overflow: hidden;
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-copy small {
  overflow: hidden;
  color: var(--ink-faint);
  font-size: 9.5px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.admin-tab.active .tab-index {
  color: #b7c4bd;
}

.admin-tab.active .tab-copy strong {
  color: #f7f4ed;
}

.admin-tab.active .tab-copy small {
  color: #b7c4bd;
}

.tab-heading {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 26px 2px 18px;
}

.tab-heading h2 {
  margin: 0;
  font-size: 22px;
  line-height: 1.3;
}

.tab-heading p {
  margin: 3px 0 0;
  color: var(--ink-muted);
  font-size: 11px;
}

.tab-rule {
  height: 1px;
  flex: 1;
  background: var(--line);
}

.tab-count {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.admin-body {
  min-height: 400px;
}

.admin-loading {
  display: flex;
  min-height: 320px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--ink-muted);
  font-size: 12px;
}

.pending-dots {
  display: flex;
  gap: 3px;
}

.pending-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--primary);
  animation: fade 1.2s ease-in-out infinite;
}

.pending-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.pending-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes fade {
  0%,
  100% {
    opacity: 0.24;
  }

  50% {
    opacity: 1;
  }
}

.access-state {
  max-width: 560px;
  margin: 9vh auto 0;
  padding: 34px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
  text-align: center;
}

.access-icon {
  display: inline-grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  color: var(--primary);
}

.access-state .eyebrow {
  margin-top: 18px;
}

.access-state h2 {
  margin: 0;
  font-size: 25px;
}

.access-state > p:not(.eyebrow) {
  margin: 10px auto 0;
  color: var(--ink-muted);
  font-size: 12px;
}

.access-actions {
  margin-top: 22px;
  color: var(--ink-faint);
  font-size: 10.5px;
}

.plain-link {
  display: inline-block;
  margin-right: 10px;
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 3px;
}

@media (max-width: 1100px) {
  .admin-tabs {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .admin-tab:nth-child(3) {
    border-right: 0;
  }

  .admin-tab:nth-child(n + 4) {
    border-top: 1px solid var(--line);
  }

  .admin-tab:nth-child(4) {
    border-left: 1px solid var(--line);
  }
}

@media (max-width: 860px) {
  .admin-page {
    min-height: calc(100dvh - 60px - 58px);
    padding: 24px 16px 34px;
  }

  .admin-head {
    align-items: flex-start;
    flex-direction: column;
    padding-bottom: 20px;
  }

  .access-badge {
    display: none;
  }

  .admin-tabs {
    display: flex;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .admin-tabs::-webkit-scrollbar {
    display: none;
  }

  .admin-tab {
    min-width: 156px;
    flex: 0 0 auto;
    padding: 13px 12px;
    border-top: 0 !important;
    border-left: 0 !important;
  }

  .tab-copy small {
    display: none;
  }

  .tab-heading {
    padding: 20px 2px 14px;
  }

  .tab-heading h2 {
    font-size: 19px;
  }
}

@media (max-width: 560px) {
  .admin-head h1 {
    font-size: 29px;
  }

  .head-lead {
    font-size: 12px;
  }

  .access-state {
    margin-top: 5vh;
    padding: 24px 18px;
  }
}
</style>
