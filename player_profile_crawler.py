"""兼容入口：真实实现已迁移至 crawlers/player_profile.py。"""
import os
import runpy
import sys

if __name__ == "__main__":
    _target = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawlers", "player_profile.py")
    runpy.run_path(_target, run_name="__main__")
else:
    raise ImportError("player_profile_crawler has moved to crawlers.player_profile; import malody_api.crawlers.player_profile instead")
