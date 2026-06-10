/** 前端配置文件 */

// 后端 API 地址（开发环境使用动态主机名，生产环境改为实际 IP）
const API_HOST = import.meta.env.VITE_API_HOST || window.location.hostname;
const API_PORT = import.meta.env.VITE_API_PORT || 2222;

export const API_BASE = `http://${API_HOST}:${API_PORT}`;
