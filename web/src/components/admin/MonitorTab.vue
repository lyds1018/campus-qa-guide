<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, reactive, ref } from "vue";

import { ops, type Dashboard, type ModelRow } from "../../api/ops";

const board = ref<Dashboard | null>(null);
const models = ref<ModelRow[]>([]);
const dialog = ref(false);
const editing = ref<ModelRow | null>(null);
const form = reactive({ base_url: "", model: "", enabled: true, note: "" });

async function load() {
  try {
    board.value = await ops.dashboard();
    models.value = await ops.models();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载看板失败");
  }
}

function edit(row: ModelRow) {
  editing.value = row;
  form.base_url = row.base_url;
  form.model = row.model;
  form.enabled = row.enabled;
  form.note = row.note;
  dialog.value = true;
}

async function save() {
  if (!editing.value) return;
  try {
    await ops.saveModel(editing.value.slot, { ...form });
    ElMessage.success("已保存，30 秒内全进程生效（密钥仍取 .env）");
    dialog.value = false;
    await load();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "保存失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="tab-body">
    <div class="metric-grid">
      <article class="metric-card">
        <span class="metric-kicker">在版文档</span>
        <strong>{{ board?.documents.published ?? 0 }}</strong>
        <p>共 {{ board?.documents.total ?? 0 }} 份 · 草稿 {{ board?.documents.draft ?? 0 }}</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">已向量块</span>
        <strong>{{ board?.chunks.embedded ?? 0 }}</strong>
        <p>共 {{ board?.chunks.total ?? 0 }} 块，未回填会漏召回</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">近 24h 问答</span>
        <strong>{{ board?.qa_24h.turns ?? 0 }}</strong>
        <p>拒答 {{ board?.qa_24h.refused ?? 0 }} 次 · {{ board?.qa_24h.refusal_rate ?? 0 }}%</p>
      </article>
      <article class="metric-card">
        <span class="metric-kicker">P50 响应</span>
        <strong>{{ board?.qa_24h.p50_ms ?? 0 }}<small>ms</small></strong>
        <p>P95 {{ board?.qa_24h.p95_ms ?? 0 }}ms · 冷启动会更高</p>
      </article>
    </div>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>知识概览</span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <div class="catalog-strip">
        <div class="catalog-item">
          <span>事项</span>
          <strong>{{ board?.matters ?? 0 }}</strong>
        </div>
        <div class="catalog-item">
          <span>步骤</span>
          <strong>{{ board?.flows ?? 0 }}</strong>
        </div>
        <div class="catalog-item">
          <span>词典</span>
          <strong>{{ board?.terms ?? 0 }}</strong>
        </div>
        <div class="catalog-item">
          <span>队列</span>
          <strong>{{ board?.queue_depth ?? 0 }}</strong>
        </div>
      </div>
      <div class="jobs">
        <span class="jobs-label">入库任务</span>
        <template v-if="Object.keys(board?.jobs ?? {}).length">
          <el-tag v-for="(n, s) in board?.jobs ?? {}" :key="s" size="small" class="job-tag">
            {{ s }} {{ n }}
          </el-tag>
        </template>
        <span v-else class="jobs-empty">暂无任务记录</span>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>模型槽位</span>
          <span class="table-note">可覆盖 base_url 与模型名，密钥仍从 .env 读取</span>
        </div>
      </template>
      <el-table :data="models" size="small">
        <el-table-column prop="slot" label="槽位" width="100" />
        <el-table-column prop="model" label="模型" min-width="180" />
        <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
        <el-table-column label="密钥" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.has_key ? 'success' : 'info'">
              {{ row.has_key ? "已配" : "空" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.overridden ? 'warning' : 'info'">
              {{ row.overridden ? "运营覆盖" : ".env" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="edit(row)">修改</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialog" :title="`修改槽位 ${editing?.slot ?? ''}`" width="520px">
      <el-form label-width="80px">
        <el-form-item label="模型"><el-input v-model="form.model" /></el-form-item>
        <el-form-item label="Base URL">
          <el-input v-model="form.base_url" placeholder="留空则沿用 .env" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.metric-card {
  min-width: 0;
  padding: 18px 18px 16px;
  border-right: 1px solid var(--line);
}

.metric-card:last-child {
  border-right: 0;
}

.metric-kicker {
  display: block;
  color: var(--ink-muted);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.08em;
}

.metric-card strong {
  display: block;
  margin-top: 10px;
  color: var(--ink);
  font-family: var(--serif);
  font-size: 30px;
  font-weight: 600;
  line-height: 1;
}

.metric-card strong small {
  margin-left: 3px;
  color: var(--ink-muted);
  font-family: var(--sans);
  font-size: 10px;
  font-weight: 400;
}

.metric-card p {
  margin: 8px 0 0;
  color: var(--ink-faint);
  font-size: 9.5px;
  line-height: 1.55;
}

.catalog-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
}

.catalog-item {
  display: flex;
  align-items: baseline;
  gap: 7px;
  padding: 4px 14px;
  border-right: 1px solid var(--line);
}

.catalog-item:first-child {
  padding-left: 0;
}

.catalog-item:last-child {
  border-right: 0;
}

.catalog-item span {
  color: var(--ink-muted);
  font-size: 10px;
}

.catalog-item strong {
  color: var(--ink-soft);
  font-family: var(--serif);
  font-size: 19px;
  font-weight: 600;
}

.jobs {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-top: 16px;
  padding-top: 13px;
  border-top: 1px solid var(--line);
}

.jobs-label,
.table-note,
.jobs-empty {
  color: var(--ink-faint);
  font-size: 9.5px;
}

.table-note {
  font-weight: 400;
}

.job-tag {
  font-size: 10px;
}

@media (max-width: 1080px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metric-card:nth-child(2) {
    border-right: 0;
  }

  .metric-card:nth-child(-n + 2) {
    border-bottom: 1px solid var(--line);
  }

  .table-note {
    display: none;
  }
}

@media (max-width: 620px) {
  .catalog-strip {
    grid-template-columns: repeat(2, 1fr);
    gap: 10px 0;
  }

  .catalog-item:nth-child(2) {
    border-right: 0;
  }

  .catalog-item:nth-child(3) {
    padding-left: 0;
  }
}
</style>
