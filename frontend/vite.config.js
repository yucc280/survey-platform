import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 浏览器只请求同源 /api，由开发服务器转发到已有后端。
const proxy = { '/api': { target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true } }

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
  preview: { host: '127.0.0.1', port: 5174, strictPort: true, proxy },
})
