<script setup lang="ts">
import { RouterView } from "vue-router";
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <h1>校园智能问答与办事指南</h1>
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
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.app-header h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.app-main {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 16px;
}
</style>
