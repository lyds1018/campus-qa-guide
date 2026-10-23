<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { getToken, setToken } from "./api/http";

const route = useRoute();
const router = useRouter();

/** 演示身份：两枚 token 对应两套权限，切换即换人（真实系统里是登录态）。 */
const identity = ref(getToken() === "admin-demo" ? "admin" : "student");

function switchIdentity(value: string) {
  identity.value = value;
  setToken(value === "admin" ? "admin-demo" : "student-demo");
  // 管理页需要管理员身份，切回学生时自动离开，避免停在 403 上
  if (value === "student" && route.path.startsWith("/admin")) router.push("/chat");
  if (value === "admin" && route.path.startsWith("/chat")) router.push("/admin");
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>校园智能问答与办事指南</h1>
      <nav class="nav">
        <RouterLink to="/chat" :class="{ active: route.path.startsWith('/chat') }">问答</RouterLink>
        <RouterLink to="/admin" :class="{ active: route.path.startsWith('/admin') }">
          知识运营
        </RouterLink>
        <RouterLink to="/health" :class="{ active: route.path.startsWith('/health') }">状态</RouterLink>
      </nav>
      <div class="identity">
        <span class="label">身份</span>
        <el-select v-model="identity" size="small" style="width: 110px" @change="switchIdentity">
          <el-option label="学生" value="student" />
          <el-option label="管理员" value="admin" />
        </el-select>
      </div>
    </header>
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: #f5f7fa;
  color: #303133;
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
}

.app-shell {
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.app-header h1 {
  margin: 0;
  font-size: 17px;
  white-space: nowrap;
}

.nav {
  display: flex;
  gap: 6px;
  flex: 1;
}

.nav a {
  padding: 6px 14px;
  border-radius: 6px;
  color: #606266;
  text-decoration: none;
  font-size: 14px;
}

.nav a.active {
  background: #ecf5ff;
  color: #409eff;
  font-weight: 600;
}

.identity {
  display: flex;
  align-items: center;
  gap: 6px;
}

.identity .label {
  font-size: 12px;
  color: #909399;
}

/* 对话页要占满宽度，状态页仍是居中窄栏：各自在组件里控制宽度 */
.app-main {
  min-height: calc(100vh - 52px);
}
</style>
