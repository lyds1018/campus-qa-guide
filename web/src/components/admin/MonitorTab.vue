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
    <el-row :gutter="12">
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ board?.documents.published ?? 0 }}</div>
          <div class="metric-label">在版文档 / 总 {{ board?.documents.total ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ board?.chunks.embedded ?? 0 }}</div>
          <div class="metric-label">已向量块 / 总 {{ board?.chunks.total ?? 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ board?.qa_24h.turns ?? 0 }}</div>
          <div class="metric-label">
            近 24h 问答 / 拒答 {{ board?.qa_24h.refused ?? 0 }}（{{
              board?.qa_24h.refusal_rate ?? 0
            }}%）
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="never">
          <div class="metric">{{ board?.qa_24h.p50_ms ?? 0 }}ms</div>
          <div class="metric-label">P50 延迟 / P95 {{ board?.qa_24h.p95_ms ?? 0 }}ms</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>
            事项 {{ board?.matters ?? 0 }} · 步骤 {{ board?.flows ?? 0 }} · 词典
            {{ board?.terms ?? 0 }} · 队列 {{ board?.queue_depth ?? 0 }}
          </span>
          <el-button size="small" @click="load">刷新</el-button>
        </div>
      </template>
      <div class="jobs">
        <el-tag v-for="(n, s) in board?.jobs ?? {}" :key="s" size="small" class="job-tag">
          {{ s }}：{{ n }}
        </el-tag>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header>模型槽位（改 base_url / model，密钥仍从 .env 读）</template>
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
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.metric {
  font-size: 26px;
  font-weight: 600;
  color: #303133;
}
.metric-label {
  margin-top: 4px;
  font-size: 12px;
  color: #909399;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.jobs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.job-tag {
  font-size: 12px;
}
</style>
