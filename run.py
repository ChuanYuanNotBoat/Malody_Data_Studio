"""兼容入口：真实实现已迁移至 app/main.py。"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.main import main  # noqa: E402,F401

if __name__ == "__main__":
    main()
