"""兼容入口：真实实现已迁移至 crawlers/rankings.py。

直接运行本文件等价于运行 crawlers/rankings.py；
作为模块导入时请改用 `malody_api.crawlers.rankings`。
"""
import os
import runpy
import sys

if __name__ == "__main__":
    _target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawlers", "rankings.py")
    runpy.run_path(_target, run_name="__main__")
else:
    raise ImportError("malody_rankings has moved to crawlers.rankings; import malody_api.crawlers.rankings instead")
