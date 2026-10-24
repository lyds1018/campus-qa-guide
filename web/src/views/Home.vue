<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { get, type ApiError } from "../api/http";
import AppIcon from "../components/AppIcon.vue";

interface Check {
  ok: boolean;
  detail: string;
}

interface Health {
  status: string;
  checks: Record<string, Check>;
  version: string;
}

type State = "loading" | "ready" | "degraded" | "unreachable";

const LABELS: Record<string, string> = {
  db: "PostgreSQL",
  redis: "Redis",
  storage: "MinIO",
};

const HINTS: Record<string, string> = {
  db: "业务数据与知识库",
  redis: "会话热态与队列",
  storage: "原件与解析结果",
};

const state = ref<State>("loading");
const health = ref<Health | null>(null);
const reason = ref("");

const rows = computed(() =>
  Object.entries(health.value?.checks ?? {}).map(([key, c]) => ({
    key,
    name: LABELS[key] ?? key,
    hint: HINTS[key] ?? "基础依赖",
    ok: c.ok,
    detail: c.detail,
  })),
);

const healthyCount = computed(() => rows.value.filter((row) => row.ok).length);

const summary = computed(() => {
  if (state.value === "loading") return "正在检测依赖";
  if (state.value === "ready") return "全部服务运行正常";
  if (state.value === "degraded") return "部分依赖不可用";
  return "后端服务不可达";
});

async function probe() {
  state.value = "loading";
  health.value = null;
  reason.value = "";

  try {
    const body = await get<Health>("/health");
    health.value = body;
    state.value = body.status === "ok" ? "ready" : "degraded";
  } catch (e) {
    const err = e as ApiError;
    // 503 时响应体仍是完整 HealthOut，取其中的 checks 列失败项
    const body = err.data as Health | undefined;
    if (err.status === 503 && body?.checks) {
      health.value = body;
      state.value = "degraded";
      return;
    }
    state.value = "unreachable";
    reason.value = err.detail;
  }
}

onMounted(probe);
</script>

<template>
  <div class="status-page">
    <div class="status-shell">
      <header class="status-head">
        <div>
          <p class="eyebrow">运行检查</p>
          <h1 class="serif">系统状态</h1>
          <p class="head-lead">数据库、缓存与文件存储的实时连通性。问答异常时，先从这里排查。</p>
        </div>
        <button type="button" class="refresh-button" :disabled="state === 'loading'" @click="probe">
          <AppIcon name="refresh" :size="15" :class="{ spinning: state === 'loading' }" />
          {{ state === "loading" ? "检测中" : "重新检测" }}
        </button>
      </header>

      <section class="status-summary" :class="state">
        <div class="summary-mark">
          <span class="status-dot" />
        </div>
        <div class="summary-copy">
          <p>{{ summary }}</p>
          <span v-if="state !== 'unreachable'">
            {{ healthyCount }} / {{ rows.length || 3 }} 项依赖正常
            <template v-if="health?.version"> · 版本 {{ health.version }}</template>
          </span>
          <span v-else>{{ reason || "未能连接到接口服务" }}</span>
        </div>
        <AppIcon
          :name="state === 'unreachable' ? 'alert' : state === 'degraded' ? 'alert' : 'check'"
          :size="22"
        />
      </section>

      <section v-if="state === 'loading'" class="service-list" aria-label="正在检测">
        <div v-for="i in 3" :key="i" class="service-row skeleton">
          <span class="service-index">0{{ i }}</span>
          <div class="skeleton-copy">
            <span />
            <span />
          </div>
        </div>
      </section>

      <section v-else-if="state !== 'unreachable'" class="service-list" aria-label="服务状态">
        <div v-for="(row, index) in rows" :key="row.key" class="service-row">
          <span class="service-index">{{ String(index + 1).padStart(2, "0") }}</span>
          <div class="service-name">
            <AppIcon name="database" :size="17" />
            <div>
              <strong>{{ row.name }}</strong>
              <small>{{ row.hint }}</small>
            </div>
          </div>
          <p class="service-detail">{{ row.detail }}</p>
          <span class="service-state" :class="{ ok: row.ok }">
            <i />
            {{ row.ok ? "正常" : "异常" }}
          </span>
        </div>
      </section>

      <section v-else class="offline-panel">
        <span class="offline-icon"><AppIcon name="alert" :size="23" /></span>
        <h2 class="serif">没有收到后端响应</h2>
        <p>请确认服务已启动，并检查本地端口与代理配置。</p>
        <code>uv run uvicorn config.asgi:application --reload --port 8000</code>
        <button type="button" class="retry-link" @click="probe">启动后再检测一次</button>
      </section>

      <footer class="status-foot">
        <span>健康检查同时覆盖 PostgreSQL、Redis 与 MinIO。</span>
        <span class="foot-note">接口异常时返回 503，本页仍会展示逐项结果。</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.status-page {
  min-height: calc(100dvh - var(--header-h));
  padding: 48px 28px 68px;
}

.status-shell {
  width: min(880px, 100%);
  margin: 0 auto;
}

.status-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--line-strong);
}

.status-head h1 {
  margin: 0;
  font-size: clamp(32px, 4vw, 44px);
  line-height: 1.2;
}

.head-lead {
  max-width: 560px;
  margin: 10px 0 0;
  color: var(--ink-muted);
  font-size: 12.5px;
  line-height: 1.75;
}

.refresh-button {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  background: var(--surface-raised);
  color: var(--ink-soft);
  font-size: 11px;
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease;
}

.refresh-button:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.refresh-button:disabled {
  cursor: wait;
  opacity: 0.6;
}

.spinning {
  animation: rotate 1s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

.status-summary {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 26px;
  padding: 19px 20px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-raised);
}

.status-summary.ready {
  border-color: #ccd9cf;
}

.status-summary.degraded {
  border-color: #e2d2b9;
  background: #fcf8f1;
}

.status-summary.unreachable {
  border-color: #e3cbc5;
  background: #fcf4f1;
}

.summary-mark {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 50%;
  background: var(--surface);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.status-summary.ready .status-dot {
  background: var(--success);
  box-shadow: 0 0 0 4px rgb(61 102 83 / 10%);
}

.status-summary.degraded .status-dot {
  background: var(--warning);
}

.status-summary.unreachable .status-dot {
  background: var(--danger);
}

.summary-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}

.summary-copy p {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
  font-weight: 600;
}

.summary-copy span {
  color: var(--ink-muted);
  font-size: 10.5px;
}

.status-summary > svg {
  color: var(--ink-faint);
}

.status-summary.ready > svg {
  color: var(--success);
}

.status-summary.degraded > svg,
.status-summary.unreachable > svg {
  color: var(--warning);
}

.service-list {
  margin-top: 26px;
  border-top: 1px solid var(--line);
}

.service-row {
  display: grid;
  grid-template-columns: 28px 1fr minmax(0, 1.15fr) 76px;
  gap: 16px;
  align-items: center;
  min-height: 72px;
  padding: 12px 4px;
  border-bottom: 1px solid var(--line);
}

.service-index {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
}

.service-name {
  display: flex;
  align-items: center;
  gap: 9px;
  color: var(--primary);
}

.service-name div {
  display: flex;
  flex-direction: column;
}

.service-name strong {
  color: var(--ink-soft);
  font-size: 12.5px;
  font-weight: 600;
}

.service-name small {
  color: var(--ink-faint);
  font-size: 9.5px;
}

.service-detail {
  margin: 0;
  color: var(--ink-muted);
  font-size: 10.5px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.service-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  justify-self: end;
  color: var(--danger);
  font-size: 10px;
}

.service-state i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentcolor;
}

.service-state.ok {
  color: var(--success);
}

.skeleton {
  opacity: 0.55;
}

.skeleton-copy {
  grid-column: 2 / span 2;
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.skeleton-copy span {
  display: block;
  width: 38%;
  height: 9px;
  border-radius: 3px;
  background: var(--line);
  animation: pulse 1.4s ease-in-out infinite;
}

.skeleton-copy span + span {
  width: 62%;
  animation-delay: 0.15s;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.5;
  }

  50% {
    opacity: 1;
  }
}

.offline-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 26px;
  padding: 44px 28px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-raised);
  text-align: center;
}

.offline-icon {
  display: grid;
  width: 46px;
  height: 46px;
  place-items: center;
  border: 1px solid #e3cbc5;
  border-radius: 50%;
  color: var(--danger);
}

.offline-panel h2 {
  margin: 16px 0 0;
  font-size: 23px;
}

.offline-panel p {
  margin: 7px 0 16px;
  color: var(--ink-muted);
  font-size: 11.5px;
}

.offline-panel code {
  max-width: 100%;
  padding: 9px 13px;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink-soft);
  font-family: var(--mono);
  font-size: 10px;
  white-space: nowrap;
}

.retry-link {
  margin-top: 18px;
  padding: 0;
  border: 0;
  border-bottom: 1px solid var(--line-strong);
  background: transparent;
  color: var(--primary);
  font-size: 10.5px;
  cursor: pointer;
}

.status-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 20px;
  color: var(--ink-faint);
  font-size: 9.5px;
}

.foot-note {
  text-align: right;
}

@media (max-width: 860px) {
  .status-page {
    min-height: calc(100dvh - 60px - 58px);
    padding: 28px 16px 36px;
  }

  .status-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
    padding-bottom: 20px;
  }

  .status-head h1 {
    font-size: 31px;
  }

  .service-row {
    grid-template-columns: 22px 1fr 62px;
    gap: 10px;
    padding: 14px 2px;
  }

  .service-detail {
    grid-column: 2 / span 2;
    padding-bottom: 2px;
    font-size: 10px;
  }

  .status-foot {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .foot-note {
    text-align: left;
  }

  .offline-panel {
    padding: 34px 16px;
  }
}
</style>
