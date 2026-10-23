<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { get, type ApiError } from "../api/http";

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

const state = ref<State>("loading");
const health = ref<Health | null>(null);
const reason = ref("");
const failed = ref<{ name: string; detail: string }[]>([]);

const rows = computed(() =>
  Object.entries(health.value?.checks ?? {}).map(([key, c]) => ({
    name: LABELS[key] ?? key,
    ok: c.ok,
    detail: c.detail,
  })),
);

async function probe() {
  state.value = "loading";
  health.value = null;
  reason.value = "";
  failed.value = [];

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
      failed.value = Object.entries(body.checks)
        .filter(([, c]) => !c.ok)
        .map(([key, c]) => ({ name: LABELS[key] ?? key, detail: c.detail }));
      return;
    }
    state.value = "unreachable";
    reason.value = err.detail;
  }
}

onMounted(probe);
</script>

<template>
  <el-card shadow="never">
    <template #header>
      <div class="card-head">
        <span>环境连通性自检</span>
        <el-button size="small" :loading="state === 'loading'" @click="probe">重新检测</el-button>
      </div>
    </template>

    <el-skeleton v-if="state === 'loading'" :rows="4" animated />

    <div v-else-if="state === 'ready'">
      <el-result icon="success" title="后端就绪">
        <template #sub-title>
          <span>版本 {{ health?.version }}</span>
        </template>
      </el-result>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item v-for="row in rows" :key="row.name" :label="row.name">
          <el-tag type="success" size="small">正常</el-tag>
          <span class="detail">{{ row.detail }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-else-if="state === 'degraded'">
      <el-result icon="warning" title="后端降级" sub-title="部分依赖不可用，接口返回 503">
        <template #extra>
          <el-alert type="error" :closable="false" show-icon>
            <template #title>
              <span v-for="item in failed" :key="item.name" class="fail-line">
                {{ item.name }}：{{ item.detail }}
              </span>
            </template>
          </el-alert>
        </template>
      </el-result>
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item v-for="row in rows" :key="row.name" :label="row.name">
          <el-tag :type="row.ok ? 'success' : 'danger'" size="small">
            {{ row.ok ? "正常" : "失败" }}
          </el-tag>
          <span class="detail">{{ row.detail }}</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-else>
      <el-result icon="error" title="后端不可达" :sub-title="reason">
        <template #extra>
          <el-alert type="info" :closable="false" show-icon>
            <template #title>
              请先启动后端：uv run uvicorn config.asgi:application --reload --port 8000
            </template>
          </el-alert>
        </template>
      </el-result>
    </div>
  </el-card>
</template>

<style scoped>
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.detail {
  margin-left: 8px;
  color: #606266;
  font-size: 13px;
}

.fail-line {
  display: block;
}
</style>
