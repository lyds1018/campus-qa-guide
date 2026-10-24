import ElementPlus from "element-plus";
import "element-plus/dist/index.css";
import { createApp } from "vue";

import App from "./App.vue";
import { setToken } from "./api/http";
import router from "./router";
import "./styles/main.css";

// 演示便利：`?token=admin-demo` 可直接换身份进后台，省掉手点切换。
// 只影响 localStorage，不改任何服务端状态。
const queryToken = new URLSearchParams(location.search).get("token");
if (queryToken) setToken(queryToken);

createApp(App).use(router).use(ElementPlus).mount("#app");
