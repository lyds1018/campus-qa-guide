<script setup lang="ts">
import { ElMessage } from "element-plus";
import { onMounted, ref } from "vue";

import { ops, type DocRow, type ReviewRow } from "../../api/ops";

const rows = ref<ReviewRow[]>([]);
const docs = ref<DocRow[]>([]);
const query = ref("");
const loading = ref(false);
const versions = ref<DocRow[]>([]);
const versionDialog = ref(false);

async function loadReview() {
  loading.value = true;
  try {
    rows.value = await ops.review();
    docs.value = await ops.documents(query.value);
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载失败");
  } finally {
    loading.value = false;
  }
}

async function publish(id: number) {
  try {
    await ops.publish(id);
    ElMessage.success("已发布（同标题旧版已归档）");
    await loadReview();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "发布失败");
  }
}

async function archive(id: number) {
  try {
    await ops.archive(id);
    ElMessage.success("已归档");
    await loadReview();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "归档失败");
  }
}

async function embed(id: number) {
  try {
    const result = await ops.embed(id);
    ElMessage.success(result.filled ? `已回填 ${result.filled} 块向量` : "没有待回填的块");
    await loadReview();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "回填失败");
  }
}

async function showVersions(id: number) {
  try {
    versions.value = await ops.versions(id);
    versionDialog.value = true;
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "加载版本失败");
  }
}

async function rollback(id: number) {
  try {
    await ops.rollback(id);
    ElMessage.success("已回滚到该版本");
    versionDialog.value = false;
    await loadReview();
  } catch (e) {
    ElMessage.error((e as { detail?: string }).detail ?? "回滚失败");
  }
}

onMounted(loadReview);
</script>

<template>
  <div class="tab-body">
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>待审核草稿</span>
          <el-button size="small" @click="loadReview">刷新</el-button>
        </div>
      </template>
      <el-table :data="rows" v-loading="loading" size="small" empty-text="没有待审核的草稿">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="doc_type" label="类型" width="90" />
        <el-table-column prop="dept" label="部门" width="110" />
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="块 / 已向量" width="110">
          <template #default="{ row }">{{ row.chunks }} / {{ row.embedded }}</template>
        </el-table-column>
        <el-table-column label="口径冲突" min-width="200">
          <template #default="{ row }">
            <template v-if="row.conflicts.length">
              <el-popover placement="left" width="360" trigger="click">
                <template #reference>
                  <el-tag type="warning" size="small" style="cursor: pointer">
                    {{ row.conflicts.length }} 处差异
                  </el-tag>
                </template>
                <div v-for="(c, i) in row.conflicts" :key="i" class="conflict">
                  <b>{{ c.field }}</b>：新版 {{ c.draft }} ⇄ 在版 {{ c.published }}
                  <div class="conflict-src">对照《{{ c.published_doc }}》</div>
                </div>
              </el-popover>
            </template>
            <span v-else class="muted">无</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="publish(row.id)">发布</el-button>
            <el-button size="small" @click="embed(row.id)">补向量</el-button>
            <el-button size="small" type="danger" text @click="archive(row.id)">归档</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>文档与版本</span>
          <div class="search">
            <el-input v-model="query" placeholder="按标题搜索" clearable style="width: 200px" />
            <el-button size="small" @click="loadReview">查询</el-button>
          </div>
        </div>
      </template>
      <el-table :data="docs" size="small" empty-text="没有文档">
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="status" label="状态" width="90" />
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="块 / 已向量" width="110">
          <template #default="{ row }">{{ row.chunks }} / {{ row.embedded }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="showVersions(row.id)">
              版本
            </el-button>
            <el-button size="small" text @click="embed(row.id)">补向量</el-button>
            <el-button v-if="row.status !== 'published'" size="small" text type="warning" @click="rollback(row.id)">
              回滚
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="versionDialog" title="同标题全部版本" width="720px">
      <el-table :data="versions" size="small">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="170" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'published'" size="small" type="warning" @click="rollback(row.id)">
              回滚到此版
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.search {
  display: flex;
  gap: 8px;
}
.muted {
  color: #c0c4cc;
  font-size: 12px;
}
.conflict {
  font-size: 13px;
  margin-bottom: 8px;
}
.conflict-src {
  color: #909399;
  font-size: 12px;
}
</style>
