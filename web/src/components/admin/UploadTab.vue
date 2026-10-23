<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import { ops, type Job } from "../../api/ops";

const docType = ref("guide");
const dept = ref("");
const uploading = ref(false);
const jobs = ref<Job[]>([]);
const loading = ref(false);

const TYPE_OPTIONS = [
  { value: "guide", label: "办事指南" },
  { value: "policy", label: "规章制度" },
  { value: "faq", label: "常见问题" },
  { value: "notice", label: "通知公告" },
];

const STATUS_TYPE: Record<string, string> = {
  succeeded: "success",
  failed: "danger",
  running: "warning",
  pending: "info",
  skipped: "info",
};

async function loadJobs() {
  loading.value = true;
  try {
    jobs.value = await ops.jobs();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载任务失败");
  } finally {
    loading.value = false;
  }
}

async function uploadFile(options: { file: File }) {
  uploading.value = true;
  try {
    const result = await ops.upload(options.file, docType.value, dept.value);
    ElMessage.success(`已入队 job#${result.job_id}《${result.filename}》`);
    await loadJobs();
  } catch (e) {
    const err = e as { status?: number; detail?: string };
    ElMessage.error(err.detail ?? "上传失败");
  } finally {
    uploading.value = false;
  }
}

async function retry(id: number) {
  try {
    await ops.retryJob(id);
    ElMessage.success(`job#${id} 已重新入队`);
    await loadJobs();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "重试失败");
  }
}

onMounted(loadJobs);
</script>

<template>
  <div class="tab-body">
    <el-card shadow="never" class="block">
      <template #header>上传原件</template>
      <div class="form-row">
        <span class="label">类型</span>
        <el-select v-model="docType" style="width: 140px">
          <el-option v-for="o in TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <span class="label">部门</span>
        <el-input v-model="dept" placeholder="如 教务处" style="width: 180px" />
        <el-upload
          :show-file-list="false"
          :http-request="uploadFile"
          accept=".md,.pdf,.txt"
          :disabled="uploading"
        >
          <el-button type="primary" :loading="uploading">选择文件并入库</el-button>
        </el-upload>
        <span class="hint">支持 md / pdf / txt，单文件 ≤ 20MB；重复文件会按 checksum 拒绝</span>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="head">
          <span>入库任务</span>
          <el-button size="small" @click="loadJobs">刷新</el-button>
        </div>
      </template>
      <el-table :data="jobs" v-loading="loading" size="small" empty-text="还没有任务">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="source_path" label="文件" min-width="200" />
        <el-table-column prop="doc_type" label="类型" width="90" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TYPE[row.status] ?? 'info'">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stage" label="阶段" width="90" />
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="row.status !== 'running'"
              size="small"
              text
              type="primary"
              @click="retry(row.id)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.label {
  color: #606266;
  font-size: 13px;
}
.hint {
  color: #909399;
  font-size: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
