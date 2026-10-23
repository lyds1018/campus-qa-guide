<script setup lang="ts">
import { onMounted, ref } from "vue";

import { me } from "../api/chat";
import type { Me } from "../api/types";
import CatalogTab from "../components/admin/CatalogTab.vue";
import MonitorTab from "../components/admin/MonitorTab.vue";
import ReviewTab from "../components/admin/ReviewTab.vue";
import UploadTab from "../components/admin/UploadTab.vue";

const tab = ref("upload");
const identity = ref<Me | null>(null);
const error = ref("");

onMounted(async () => {
  try {
    identity.value = await me();
  } catch (e) {
    error.value = (e as { detail?: string }).detail ?? "无法获取身份";
  }
});
</script>

<template>
  <div class="admin">
    <el-result
      v-if="error"
      icon="warning"
      title="需要管理员身份"
      :sub-title="error"
    >
      <template #extra>
        <p class="tip">用右上角的身份切换选择「管理员」后再进入。</p>
      </template>
    </el-result>

    <el-result
      v-else-if="identity && identity.role !== 'admin'"
      icon="info"
      title="当前是学生身份"
      sub-title="知识运营接口只对管理员开放"
    />

    <el-tabs v-else v-model="tab" type="border-card" class="tabs">
      <el-tab-pane label="入库与任务" name="upload"><UploadTab /></el-tab-pane>
      <el-tab-pane label="审核与版本" name="review"><ReviewTab /></el-tab-pane>
      <el-tab-pane label="事项与词典" name="catalog"><CatalogTab /></el-tab-pane>
      <el-tab-pane label="看板与模型" name="monitor"><MonitorTab /></el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.admin {
  padding: 12px;
}
.tabs {
  min-height: calc(100vh - 130px);
}
.tip {
  color: #909399;
  font-size: 13px;
}
</style>
