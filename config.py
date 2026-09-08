"""兼容入口：真实实现已迁移至 app/config.py。"""
from app.config import Config, config  # noqa: F401

__all__ = ["Config", "config"]
