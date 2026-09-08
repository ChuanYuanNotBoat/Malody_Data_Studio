# malody_api/run.py
#!/usr/bin/env python3
"""
Malody API启动脚本 - 主入口文件
"""
import os
import sys

# 确保 API 内部模块（routers/core/utils）可导入
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import colorama
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

try:
    from app.config import config
except ImportError:  # pragma: no cover - 兼容直接脚本运行
    from config import config


def create_app():
    """创建FastAPI应用"""
    # 初始化colorama以修复Windows PowerShell颜色显示
    colorama.init()

    # 创建FastAPI应用
    app = FastAPI(
        title="Malody数据API",
        description="""
        Malody玩家和谱面数据查询API - 提供完整的排行榜、统计和分析功能

        ## 功能特性

        - **玩家数据**: 查询玩家排名、详细信息、历史记录、个人资料
        - **谱面数据**: 获取谱面统计、热门谱面、创作者信息、稳定者分析
        - **页面解析**: 实时解析Malody页面，获取最新排行榜数据
        - **数据分析**: 趋势分析、模式比较、数据统计
        - **高级查询**: 灵活的自定义查询功能
        - **爬虫控制**: 触发爬虫更新、查看爬虫进度
        - **灵活筛选**: 支持模式、难度、时间范围、状态等多种筛选条件

        ## 数据来源

        数据来自Malody游戏服务器，通过爬虫定期更新。
        """,
        version="1.3.0",  # 版本号升级以体现新增功能
        docs_url=None,     # 禁用默认docs，使用自定义
        redoc_url=None,    # 禁用默认redoc，使用自定义
        openapi_url="/openapi.json"
    )

    # CORS配置
    allow_origins = config.ALLOWED_ORIGINS if config.ALLOWED_ORIGINS else ["*"]
    wildcard_origins = "*" in allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=not wildcard_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 创建静态文件目录（如果不存在）
    static_dir = "static"
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)

    # 挂载静态文件
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    return app

def register_routers(app):
    """注册所有路由"""
    # 添加当前目录到 Python 路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

    # 导入路由
    try:
        from routers.players import router as players_router
        from routers.charts import router as charts_router
        from routers.analytics import router as analytics_router
        from routers.system import router as system_router
        from routers.query import router as query_router
        from routers.page_parser import router as page_parser_router
        from routers.crawler import router as crawler_router   # 新增爬虫控制路由
        from routers.official_api import router as official_api_router
        from routers.quality import router as quality_router
        from routers.plugins import router as plugins_router

        # 注册路由
        app.include_router(players_router)
        app.include_router(charts_router)
        app.include_router(analytics_router)
        app.include_router(system_router)
        app.include_router(query_router)
        app.include_router(page_parser_router)
        app.include_router(crawler_router)                     # 新增
        app.include_router(official_api_router)
        app.include_router(quality_router)
        app.include_router(plugins_router)

        print("All routers registered successfully.")

    except ImportError as e:
        print(f"Failed to import routers: {e}")
        print("Please ensure all router files exist under the routers directory.")
        sys.exit(1)

def setup_routes(app):
    """设置基础路由和文档"""

    # 自定义文档路由
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js",
            swagger_css_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css",
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html():
        return get_redoc_html(
            openapi_url="/openapi.json",
            title=app.title + " - ReDoc",
            redoc_js_url="https://unpkg.com/redoc@next/bundles/redoc.standalone.js",
        )

    @app.get("/swagger-ui-assets/{path:path}", include_in_schema=False)
    async def swagger_assets(path: str):
        return FileResponse(f"static/{path}")

    # OAuth2重定向路由（Swagger UI需要）
    @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect():
        return {}

    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        from datetime import datetime
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": f"服务器内部错误: {str(exc)}",
                "timestamp": datetime.now().isoformat()
            }
        )

    # 根路由
    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "message": "Malody数据API服务运行中",
            "version": "1.3.0",
            "documentation": "/docs",
            "endpoints": {
                "players": "/players/",
                "charts": "/charts/",
                "analytics": "/analytics/",
                "system": "/system/",
                "query": "/query/",
                "page_parser": "/page-parser/",
                "crawler": "/crawler/",
                "official_api": "/official-api/",
                "quality": "/quality/",
                "plugins": "/plugins/"
            }
        }

    # 健康检查
    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "healthy"}

    # OpenAPI JSON路由
    @app.get("/openapi.json", include_in_schema=False)
    async def get_openapi_json():
        return custom_openapi(app)

    # 自定义OpenAPI文档
    def custom_openapi(app):
        if app.openapi_schema:
            return app.openapi_schema

        openapi_schema = get_openapi(
            title="Malody数据API",
            version="1.3.0",
            description="""
            ## Malody数据API

            提供完整的Malody游戏数据查询和分析功能。

            ### 主要功能

            - **玩家数据**: 查询玩家排名、详细信息、历史记录、个人资料（头衔、成就）
            - **谱面数据**: 获取谱面统计、热门谱面、创作者信息、稳定者分析
            - **页面解析**: 实时解析谱面页面，获取排行榜数据
            - **数据分析**: 趋势分析、模式比较、数据统计
            - **高级查询**: 灵活的自定义查询功能
            - **爬虫控制**: 触发爬虫更新、查看爬虫进度

            ### 使用说明

            所有API均返回统一格式的JSON响应：
            ```json
            {
                "success": true,
                "data": {...},
                "message": "操作成功",
                "error": null,
                "timestamp": "2024-01-01T00:00:00Z"
            }
            ```
            """,
            routes=app.routes,
        )

        # 添加服务器信息
        openapi_schema["servers"] = [
            {
                "url": "http://localhost:8000",
                "description": "开发服务器"
            }
        ]

        app.openapi_schema = openapi_schema
        return app.openapi_schema

    # 设置自定义OpenAPI
    app.openapi = lambda: custom_openapi(app)

def main():
    """启动API服务器"""
    # 获取当前目录和父目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)

    # 将父目录添加到Python路径，这样malody_api可以作为包导入
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    # 检查数据库文件是否存在
    db_path = config.DATABASE_PATH
    if not os.path.exists(db_path):
        print(f"Error: database file not found: {db_path}")
        print("Please ensure malody_rankings.db exists in current directory.")
        sys.exit(1)

    # 创建静态文件目录
    static_dir = os.path.join(current_dir, "static")
    if not os.path.exists(static_dir):
        os.makedirs(static_dir)
        print(f"Created static directory: {static_dir}")

    print("Starting Malody API server...")
    print(f"Database: {db_path}")
    print(f"Docs: http://{config.HOST}:{config.PORT}/docs")
    print(f"API: http://{config.HOST}:{config.PORT}")
    print("Press Ctrl+C to stop.")
    print("-" * 50)

    # 创建并配置应用
    app = create_app()
    register_routers(app)
    setup_routes(app)

    # 启动服务器
    uvicorn.run(
        app,  # 直接传递app实例，而不是字符串模块路径
        host=config.HOST,
        port=config.PORT,
        reload=False,
        log_level=config.LOG_LEVEL,
        access_log=True
    )

if __name__ == "__main__":
    main()
