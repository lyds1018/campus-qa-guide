<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import { ops, type Job } from "../../api/ops";
import AppIcon from "../AppIcon.vue";

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

const STATUS_LABEL: Record<string, string> = {
  succeeded: "已完成",
  failed: "失败",
  running: "处理中",
  pending: "排队中",
  skipped: "已跳过",
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
    <section class="upload-panel">
      <div class="upload-intro">
        <span class="section-index">01 · 入库</span>
        <h3 class="serif">入库新文件</h3>
        <p>
          原件先进入暂存区，由后台任务完成解析、切分与向量回填。草稿不会影响正在使用的版本。
        </p>
        <span class="constraint">支持 md / pdf / txt · 单文件 ≤ 20MB · 同内容按 checksum 拒绝</span>
      </div>

      <div class="upload-work">
        <div class="upload-fields">
          <label>
            <span>文档类型</span>
            <el-select v-model="docType">
              <el-option v-for="o in TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
          </label>
          <label>
            <span>归口部门</span>
            <el-input v-model="dept" placeholder="如 教务处" />
          </label>
        </div>

        <el-upload
          class="upload-drop"
          drag
          :show-file-list="false"
          :http-request="uploadFile"
          accept=".md,.pdf,.txt"
          :disabled="uploading"
        >
          <div class="drop-content">
            <span class="drop-icon"><AppIcon name="inbox" :size="21" /></span>
            <div>
              <strong>{{ uploading ? "正在上传…" : "选择文件或拖到此区域" }}</strong>
              <small>上传后可在下方任务列表跟踪解析进度</small>
            </div>
          </div>
        </el-upload>
      </div>
    </section>

    <el-card shadow="never">
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
            <el-tag size="small" :type="STATUS_TYPE[row.status] ?? 'info'">
              {{ STATUS_LABEL[row.status] ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stage" label="阶段" width="90" />
        <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="80">
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
.upload-panel {
  display: grid;
  grid-template-columns: minmax(240px, 0.75fr) minmax(0, 1.25fr);
  gap: 28px;
  padding: 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface-raised);
}

.section-index {
  color: var(--ink-faint);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.1em;
}

.upload-intro h3 {
  margin: 9px 0 0;
  color: var(--ink);
  font-size: 23px;
  font-weight: 600;
}

.upload-intro p {
  margin: 9px 0 0;
  color: var(--ink-muted);
  font-size: 11.5px;
  line-height: 1.75;
}

.constraint {
  display: block;
  margin-top: 13px;
  padding-top: 11px;
  border-top: 1px solid var(--line);
  color: var(--ink-faint);
  font-size: 9.5px;
  line-height: 1.6;
}

.upload-work {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
}

.upload-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.upload-fields label {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 5px;
}

.upload-fields label > span {
  color: var(--ink-muted);
  font-size: 10px;
}

.upload-drop :deep(.el-upload) {
  width: 100%;
}

.upload-drop :deep(.el-upload-dragger) {
  width: 100%;
  padding: 16px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  background: var(--surface);
  transition: border-color 160ms ease, background-color 160ms ease;
}

.upload-drop :deep(.el-upload-dragger:hover) {
  border-color: var(--primary);
  background: var(--primary-soft);
}

.drop-content {
  display: flex;
  align-items: center;
  gap: 11px;
  text-align: left;
}

.drop-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-raised);
  color: var(--primary);
}

.drop-content div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.drop-content strong {
  color: var(--ink-soft);
  font-size: 12px;
  font-weight: 600;
}

.drop-content small {
  color: var(--ink-faint);
  font-size: 9.5px;
}

@media (max-width: 980px) {
  .upload-panel {
    grid-template-columns: 1fr;
    gap: 18px;
  }
}

@media (max-width: 560px) {
  .upload-panel {
    padding: 18px 16px;
  }

  .upload-fields {
    grid-template-columns: 1fr;
  }

  .drop-content small {
    display: none;
  }
}
</style>
