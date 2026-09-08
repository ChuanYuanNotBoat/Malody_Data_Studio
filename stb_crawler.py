"""兼容入口：真实实现已迁移至 crawlers/stb.py。"""
import os
import runpy
import sys

if __name__ == "__main__":
    _target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawlers", "stb.py")
    runpy.run_path(_target, run_name="__main__")
else:
    raise ImportError("stb_crawler has moved to crawlers.stb; import malody_api.crawlers.stb instead")
