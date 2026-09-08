# malody_api/config.py
import os


class Config:
    """应用配置"""

    # 数据库配置
    DATABASE_PATH: str = os.getenv("MALODY_DB_PATH", os.path.join("data", "malody_rankings.db"))

    # 服务器配置
    HOST: str = os.getenv("MALODY_API_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("MALODY_API_PORT", "8000"))

    # 调试模式
    DEBUG: bool = os.getenv("MALODY_DEBUG", "false").lower() == "true"

    # CORS配置
    ALLOWED_ORIGINS: list = os.getenv("MALODY_ALLOWED_ORIGINS", "*").split(",")

    # 日志配置
    LOG_LEVEL: str = os.getenv("MALODY_LOG_LEVEL", "info")

    # 静态文件配置
    STATIC_DIR: str = os.getenv("MALODY_STATIC_DIR", "static")

    @classmethod
    def validate(cls):
        """验证配置"""
        if not os.path.exists(cls.DATABASE_PATH):
            raise FileNotFoundError(f"数据库文件不存在: {cls.DATABASE_PATH}")

        if not (1 <= cls.PORT <= 65535):
            raise ValueError(f"端口号必须在1-65535之间: {cls.PORT}")

        # 确保静态文件目录存在
        if not os.path.exists(cls.STATIC_DIR):
            os.makedirs(cls.STATIC_DIR)

# 创建配置实例
config = Config()
