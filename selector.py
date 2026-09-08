"""兼容入口：真实实现已迁移至 cli/selector.py。"""
from cli.selector import *  # noqa: F401,F403
from cli.selector import (  # noqa: F401
    MCSelector,
    deleted_sum_sql,
    distinct_excl_sql,
    format_dual_count,
)
