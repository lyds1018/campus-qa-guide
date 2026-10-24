import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// 开发期前端不直连 8000，全部走代理；前端代码里不出现后端地址
export default defineConfig({
  plugins: [vue()],
  build: {
    // Element Plus 完整组件库单块约 940KB（gzip 约 300KB），压缩后仍在合理范围
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          "vendor-vue": ["vue", "vue-router", "pinia"],
          "vendor-element": ["element-plus", "@element-plus/icons-vue"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
