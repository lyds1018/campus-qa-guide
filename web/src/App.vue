<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { getToken, setToken } from "./api/http";
import AppIcon from "./components/AppIcon.vue";

const route = useRoute();
const router = useRouter();

/** 演示身份：两枚 token 对应两套权限，切换即换人（真实系统里是登录态）。 */
const role = ref<"student" | "admin">(getToken() === "admin-demo" ? "admin" : "student");

const NAV = [
  { path: "/chat", label: "问答", icon: "message" },
  { path: "/admin", label: "知识运营", icon: "database" },
  { path: "/health", label: "系统状态", icon: "shield" },
] as const;

function switchIdentity(value: string) {
  role.value = value === "admin" ? "admin" : "student";
  setToken(role.value === "admin" ? "admin-demo" : "student-demo");
  // 管理页需要管理员身份，切回学生时自动离开，避免停在 403 上
  if (role.value === "student" && route.path.startsWith("/admin")) router.push("/chat");
  if (role.value === "admin" && route.path.startsWith("/chat")) router.push("/admin");
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <RouterLink to="/chat" class="brand" aria-label="返回问答首页">
        <span class="brand-mark serif">问</span>
        <span class="brand-copy">
          <strong>校务问答</strong>
          <small>校园办事指南</small>
        </span>
      </RouterLink>

      <nav class="top-nav" aria-label="主导航">
        <RouterLink
          v-for="item in NAV"
          :key="item.path"
          :to="item.path"
          class="nav-link"
          :class="{ active: route.path.startsWith(item.path) }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div class="header-actions">
        <span class="edition">演示环境</span>
        <el-dropdown trigger="click" @command="switchIdentity">
          <button type="button" class="identity-trigger" aria-label="切换演示身份">
            <span class="identity-avatar">{{ role === "admin" ? "管" : "学" }}</span>
            <span class="identity-copy">
              <strong>{{ role === "admin" ? "管理员" : "学生" }}</strong>
              <small>演示身份</small>
            </span>
            <AppIcon name="chevron-down" :size="15" />
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="student" :disabled="role === 'student'">
                学生身份
              </el-dropdown-item>
              <el-dropdown-item command="admin" :disabled="role === 'admin'">
                管理员身份
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <main class="app-main">
      <RouterView :key="role" />
    </main>

    <nav class="mobile-nav" aria-label="移动端主导航">
      <RouterLink
        v-for="item in NAV"
        :key="item.path"
        :to="item.path"
        class="mobile-nav-link"
        :class="{ active: route.path.startsWith(item.path) }"
      >
        <AppIcon :name="item.icon" :size="19" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100dvh;
  background:
    linear-gradient(var(--line) 1px, transparent 1px) 0 0 / 100% 120px,
    var(--paper);
}

.app-header {
  position: sticky;
  z-index: 30;
  top: 0;
  display: flex;
  align-items: center;
  gap: 36px;
  height: var(--header-h);
  padding: 0 28px;
  border-bottom: 1px solid var(--line);
  background: rgb(244 241 234 / 94%);
  backdrop-filter: blur(12px);
}

.brand {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  color: var(--ink);
  text-decoration: none;
}

.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid var(--primary);
  border-radius: 2px;
  background: var(--primary);
  color: #f7f4ec;
  font-size: 19px;
  line-height: 1;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}

.brand-copy strong {
  font-family: var(--serif);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.brand-copy small {
  margin-top: 3px;
  color: var(--ink-muted);
  font-size: 10px;
  letter-spacing: 0.12em;
}

.top-nav {
  display: flex;
  align-self: stretch;
  gap: 26px;
}

.nav-link {
  position: relative;
  display: flex;
  align-items: center;
  color: var(--ink-muted);
  font-size: 13px;
  text-decoration: none;
  transition: color 160ms ease;
}

.nav-link:hover {
  color: var(--ink);
}

.nav-link.active {
  color: var(--ink);
  font-weight: 600;
}

.nav-link.active::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--primary);
  content: "";
}

.header-actions {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: flex-end;
  gap: 16px;
}

.edition {
  padding: 3px 7px;
  border: 1px solid var(--line-strong);
  border-radius: 3px;
  color: var(--ink-muted);
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.12em;
}

.identity-trigger {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 4px 7px 4px 4px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  cursor: pointer;
  transition: background-color 160ms ease, border-color 160ms ease;
}

.identity-trigger:hover {
  border-color: var(--line);
  background: var(--surface);
}

.identity-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--line-strong);
  border-radius: 50%;
  background: var(--surface-raised);
  color: var(--primary);
  font-family: var(--serif);
  font-size: 13px;
}

.identity-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  line-height: 1.25;
}

.identity-copy strong {
  font-size: 12px;
  font-weight: 600;
}

.identity-copy small {
  color: var(--ink-muted);
  font-size: 10px;
}

.app-main {
  min-height: calc(100dvh - var(--header-h));
}

.mobile-nav {
  display: none;
}

@media (max-width: 860px) {
  .app-header {
    gap: 16px;
    height: 60px;
    padding: 0 16px;
  }

  .brand-copy small,
  .top-nav,
  .edition,
  .identity-copy small {
    display: none;
  }

  .brand-mark {
    width: 30px;
    height: 30px;
    font-size: 17px;
  }

  .header-actions {
    gap: 8px;
  }

  .app-main {
    min-height: calc(100dvh - 60px - 58px);
    padding-bottom: 58px;
  }

  .mobile-nav {
    position: fixed;
    z-index: 40;
    right: 0;
    bottom: 0;
    left: 0;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    height: 58px;
    padding-bottom: env(safe-area-inset-bottom);
    border-top: 1px solid var(--line);
    background: rgb(251 250 246 / 96%);
    backdrop-filter: blur(12px);
  }

  .mobile-nav-link {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    color: var(--ink-muted);
    font-size: 10px;
    text-decoration: none;
  }

  .mobile-nav-link.active {
    color: var(--primary);
    font-weight: 600;
  }
}

@media (max-width: 420px) {
  .brand-copy strong {
    font-size: 15px;
  }

  .identity-avatar {
    width: 28px;
    height: 28px;
  }
}
</style>
