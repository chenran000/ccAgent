"""主入口模块"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import HOST, PORT, LOG_LEVEL, RELOAD
from app.routes import register_routes

# 创建 FastAPI 应用
app = FastAPI(title="TestAssistant AI API")

# 配置 CORS 跨域（局域网访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册所有路由
register_routes(app)

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL,
        reload=RELOAD
    )
