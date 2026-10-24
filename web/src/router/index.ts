import { createRouter, createWebHistory } from "vue-router";

// 按页面拆包：管理后台与状态页不该拖慢首屏问答
const Chat = () => import("../views/Chat.vue");
const Admin = () => import("../views/Admin.vue");
const Home = () => import("../views/Home.vue");

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
