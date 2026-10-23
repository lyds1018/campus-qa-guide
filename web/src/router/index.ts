import { createRouter, createWebHistory } from "vue-router";

import Admin from "../views/Admin.vue";
import Chat from "../views/Chat.vue";
import Home from "../views/Home.vue";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/chat" },
    { path: "/chat", name: "chat", component: Chat },
    { path: "/admin", name: "admin", component: Admin },
    // P0 的健康检查页保留：出问题时先看它，比翻日志快
    { path: "/health", name: "health", component: Home },
  ],
});
