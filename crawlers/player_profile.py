#!/usr/bin/env python3
"""
玩家个人主页资料爬虫
用于爬取玩家的详细个人信息、头衔、成就等
同时复用主爬虫的排名解析逻辑，自动更新玩家的排名数据（mode 0-9）
支持中断恢复：通过进度文件记录已爬取位置，避免重复劳动。
按下 Ctrl+C 会等待当前任务完成后输出统计报告再退出。
"""

import argparse
import hashlib
import json
import logging
import os
import pickle
import queue
import re
import signal
import struct
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from threading import Lock, Thread

import requests
from bs4 import BeautifulSoup

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 复用现有的数据库管理器和配置
from crawlers.rankings import DatabaseManager, init_database, stop_lock, COOKIES, DATA_DIR, is_stop_requested
from crawlers.ingestion import atomic, ensure_schema, is_login_page, public_record, save_record, observe, FetchList, TaskStore, now
# 复用主爬虫中的排名解析与存储函数
from crawlers.rankings import (
  parse_player_profile as parse_rankings,  # 解析个人页中的排名数据
  resolve_player_identity,  # 处理玩家身份（改名合并）
  save_player_ranking_record  # 智能保存单条排名记录
)


# 配置日志
def setup_detailed_logging(log_level=logging.INFO, log_file=None):
    """设置详细的日志配置"""

    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # 默认日志文件
    if log_file is None:
        log_file = f"logs/player_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    # 创建logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 清除现有的handler
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # 详细的日志格式
    detailed_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s'
    )

    # 简化的控制台格式
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )

    # 文件handler - 滚动日志，每个文件10MB，保留5个备份
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(detailed_formatter)
    file_handler.setLevel(log_level)

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)

    # 添加handler
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("=" * 80)
    logger.info("玩家个人主页爬虫启动")
    logger.info("日志文件: %s", log_file)
    logger.info("日志级别: %s", logging.getLevelName(log_level))
    logger.info("=" * 80)

    return logger

# 颜色支持（仅在终端可用时启用）
USE_COLOR = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()
def colorize(text, color_code):
    """为终端文本添加颜色"""
    if USE_COLOR:
        return f"\033[{color_code}m{text}\033[0m"
    return text

# Malody API配置
BASE_URL = "https://m.mugzone.net"
PLAYER_PROFILE_URL = BASE_URL + "/accounts/user/{uid}"

# 全局变量
player_queue = queue.Queue()
crawl_progress = {}
progress_lock = Lock()

MAX_SAFE_WORKERS = 8
MAX_SAFE_RPM = 120
DEFAULT_SAFE_RPM = 15
BURST_WARN_THRESHOLD_PER_SEC = 30


class GlobalRequestRateLimiter:
    """Thread-safe global limiter shared by all worker threads."""

    def __init__(self, requests_per_minute):
        self._lock = Lock()
        self._next_allowed_ts = 0.0
        self._interval = 0.0
        self._recent_request_ts = deque()
        self._last_burst_warn_ts = 0.0
        self.set_rate(requests_per_minute)

    def set_rate(self, requests_per_minute):
        rpm = float(requests_per_minute or 0)
        self._interval = (60.0 / rpm) if rpm > 0 else 0.0

    def wait_for_slot(self):
        if self._interval <= 0:
            return

        sleep_seconds = 0.0
        now = time.monotonic()
        with self._lock:
            if now < self._next_allowed_ts:
                sleep_seconds = self._next_allowed_ts - now
                self._next_allowed_ts += self._interval
            else:
                self._next_allowed_ts = now + self._interval

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    def record_request(self, logger):
        now = time.monotonic()
        with self._lock:
            self._recent_request_ts.append(now)
            one_sec_ago = now - 1.0
            while self._recent_request_ts and self._recent_request_ts[0] < one_sec_ago:
                self._recent_request_ts.popleft()

            recent_qps = len(self._recent_request_ts)
            if (
                recent_qps >= BURST_WARN_THRESHOLD_PER_SEC
                and now - self._last_burst_warn_ts >= 10.0
            ):
                self._last_burst_warn_ts = now
                logger.warning(
                    "检测到瞬时请求峰值: 近1秒请求数=%d，已启用全局限速器。",
                    recent_qps,
                )

class ProgressTracker:
    """
    通用进度跟踪器，支持两种模式：
    - range: 连续区间，使用位图存储，占用空间极小。
    - list: 任意列表，使用集合存储，适合小规模数据。
    线程安全。
    """
    def __init__(self, mode, start=None, end=None, uid_set=None):
        self.mode = mode
        self.lock = Lock()
        if mode == 'range':
            self.start = start
            self.end = end
            self.total = end - start + 1
            self.bitmap = bytearray((self.total + 7) // 8)  # 每个比特代表一个UID，0=未完成，1=已完成
            self.next_cursor = 0  # 用于顺序遍历的游标
        elif mode == 'list':
            if uid_set is None:
                uid_set = set()
            self.remaining = set(uid_set)  # 剩余未爬取的UID集合
            self.total = len(uid_set)
        else:
            raise ValueError("mode must be 'range' or 'list'")

    def _set_bit(self, idx):
        """设置位图中指定索引的比特为1"""
        byte_idx = idx // 8
        bit_idx = idx % 8
        self.bitmap[byte_idx] |= (1 << bit_idx)

    def _test_bit(self, idx):
        """测试位图中指定索引的比特是否为1"""
        byte_idx = idx // 8
        bit_idx = idx % 8
        return (self.bitmap[byte_idx] >> bit_idx) & 1

    def get_next(self):
        """
        返回下一个待爬取的UID。
        对于range模式，按升序返回；对于list模式，顺序任意（从集合中弹出一个）。
        如果没有剩余，返回None。
        """
        with self.lock:
            if self.mode == 'range':
                # 从游标开始向后找第一个未完成的
                while self.next_cursor < self.total:
                    if not self._test_bit(self.next_cursor):
                        uid = self.start + self.next_cursor
                        self.next_cursor += 1
                        return str(uid)
                    self.next_cursor += 1
                return None
            else:  # list
                if not self.remaining:
                    return None
                # pop任意一个
                return str(self.remaining.pop())

    def mark_done(self, uid):
        """标记指定UID为已完成"""
        with self.lock:
            if self.mode == 'range':
                idx = int(uid) - self.start
                if 0 <= idx < self.total:
                    self._set_bit(idx)
                else:
                    raise ValueError(f"UID {uid} out of range [{self.start}, {self.end}]")
            else:  # list
                # 集合中可能已不存在，忽略
                self.remaining.discard(int(uid))

    def save(self, filepath):
        """将当前进度保存到文件"""
        with self.lock:
            tmp_file = filepath + '.tmp'
            if self.mode == 'range':
                # 文件格式：版本(1字节) + start(4字节) + end(4字节) + 位图数据
                with open(tmp_file, 'wb') as f:
                    f.write(b'R')  # 版本标识
                    f.write(struct.pack('<II', self.start, self.end))
                    f.write(self.bitmap)
            else:  # list
                # 使用pickle序列化剩余集合
                with open(tmp_file, 'wb') as f:
                    f.write(b'L')
                    pickle.dump(self.remaining, f)
            os.replace(tmp_file, filepath)

    @classmethod
    def load(cls, filepath, mode, start=None, end=None, uid_set=None):
        """
        从文件加载进度。
        如果文件不存在或不匹配，则根据参数创建新的跟踪器。
        """
        if not os.path.exists(filepath):
            return cls(mode, start=start, end=end, uid_set=uid_set)

        try:
            with open(filepath, 'rb') as f:
                magic = f.read(1)
                if magic == b'R' and mode == 'range':
                    # 读取范围
                    data = f.read(8)
                    if len(data) == 8:
                        saved_start, saved_end = struct.unpack('<II', data)
                        if saved_start == start and saved_end == end:
                            # 范围匹配，加载位图
                            tracker = cls('range', start=start, end=end)
                            bitmap_data = f.read()
                            if len(bitmap_data) == len(tracker.bitmap):
                                tracker.bitmap = bytearray(bitmap_data)
                                # 游标从0开始，get_next会跳过已完成
                                return tracker
                elif magic == b'L' and mode == 'list':
                    remaining = pickle.load(f)
                    tracker = cls('list', uid_set=remaining)
                    return tracker
        except Exception as e:
            logging.getLogger().warning("加载进度文件失败: %s，将从头开始", e)

        # 任何不匹配或错误，重新开始
        return cls(mode, start=start, end=end, uid_set=uid_set)

    def get_remaining_count(self):
        """返回剩余待爬取数量"""
        with self.lock:
            if self.mode == 'range':
                # 计算位图中0的个数
                remaining = self.total - sum(bin(byte).count('1') for byte in self.bitmap)
                return remaining
            else:
                return len(self.remaining)

    def get_total(self):
        return self.total

# ==================== 新增：全局位图进度跟踪器（支持动态扩展）====================
class GlobalBitmapProgress:
    """
    全局位图进度跟踪器，支持动态扩展。
    使用字节数组存储已成功爬取的 UID，位图中 1 表示已完成。
    """
    def __init__(self, filename):
        self.filename = filename
        self.lock = Lock()
        self.max_uid = 0          # 当前位图支持的最大 UID
        self.bitmap = bytearray()  # 位图数据
        self.load()

    def _ensure_capacity(self, uid):
        """确保位图能容纳 uid，若不能则扩展"""
        if uid <= self.max_uid:
            return
        new_max = max(uid, self.max_uid * 2)  # 简单倍增
        new_size = (new_max + 7) // 8
        if len(self.bitmap) < new_size:
            # 扩展字节数组
            self.bitmap.extend(b'\x00' * (new_size - len(self.bitmap)))
            self.max_uid = new_max

    def _set_bit(self, uid):
        """设置 uid 对应的位为 1"""
        idx = uid - 1  # UID 从 1 开始，bitmap 索引从 0 对应 UID=1
        byte_idx = idx // 8
        bit_idx = idx % 8
        self.bitmap[byte_idx] |= (1 << bit_idx)

    def _test_bit(self, uid):
        """测试 uid 对应的位是否为 1"""
        idx = uid - 1
        byte_idx = idx // 8
        bit_idx = idx % 8
        if byte_idx >= len(self.bitmap):
            return False
        return (self.bitmap[byte_idx] >> bit_idx) & 1

    def load(self):
        """从文件加载位图"""
        try:
            with open(self.filename, 'rb') as f:
                magic = f.read(2)
                if magic != b'GB':
                    raise ValueError("无效的全局位图文件")
                self.max_uid = struct.unpack('<I', f.read(4))[0]
                bitmap_len = struct.unpack('<I', f.read(4))[0]
                self.bitmap = bytearray(f.read(bitmap_len))
        except (FileNotFoundError, ValueError, struct.error):
            # 文件不存在或损坏，初始化为空
            self.max_uid = 0
            self.bitmap = bytearray()

    def save(self):
        """保存位图到文件（原子替换）"""
        with self.lock:
            tmp_file = self.filename + '.tmp'
            with open(tmp_file, 'wb') as f:
                f.write(b'GB')  # 魔数
                f.write(struct.pack('<I', self.max_uid))
                f.write(struct.pack('<I', len(self.bitmap)))
                f.write(self.bitmap)
            os.replace(tmp_file, self.filename)

    def mark_done(self, uid):
        """标记指定 UID 为已完成"""
        uid = int(uid)
        with self.lock:
            self._ensure_capacity(uid)
            self._set_bit(uid)

    def is_done(self, uid):
        """检查指定 UID 是否已完成"""
        uid = int(uid)
        with self.lock:
            return self._test_bit(uid)

    def get_done_count(self):
        """返回已完成的 UID 数量（遍历位图计算，较慢，仅供统计）"""
        with self.lock:
            return sum(bin(byte).count('1') for byte in self.bitmap)

class PlayerProfileCrawler:
    def __init__(self, session=None):
        self.logger = logging.getLogger("PlayerProfileCrawler")

        if session is None:
            # 创建新的session并复用认证配置
            self.session = requests.Session()
            self.session.cookies.update(COOKIES)

            # 使用与主爬虫完全相同的headers
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://m.mugzone.net/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                # Brotli is not available in the bundled requests runtime;
                # negotiate only encodings requests can decode natively.
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }

            # 添加CSRF token到headers
            if "csrftoken" in COOKIES:
                headers["X-CSRFToken"] = COOKIES["csrftoken"]
                headers["X-CSRF-Token"] = COOKIES["csrftoken"]
                headers["X-CSRFTOKEN"] = COOKIES["csrftoken"]

            self.session.headers.update(headers)

            # 使用与主爬虫相同的适配器配置
            self.session.mount(
                "https://",
                requests.adapters.HTTPAdapter(
                    max_retries=3, pool_connections=10, pool_maxsize=10
                ),
            )
        else:
            self.session = session

        self.db_manager = DatabaseManager()
        self.init_database()

        # 用于跟踪已处理的玩家（仅用于去重，与恢复逻辑分开）
        self.processed_uids = set()
        self.rate_limiter = GlobalRequestRateLimiter(DEFAULT_SAFE_RPM)

    def _sanitize_crawl_limits(self, max_workers, requests_per_minute):
        safe_workers = max(1, int(max_workers or 1))
        safe_rpm = int(requests_per_minute or 0)

        if safe_workers > MAX_SAFE_WORKERS:
            self.logger.warning(
                "max_workers=%d 超过安全阈值，已自动下调到 %d",
                safe_workers,
                MAX_SAFE_WORKERS,
            )
            safe_workers = MAX_SAFE_WORKERS

        if safe_rpm <= 0:
            self.logger.warning(
                "rpm=%d 非法或未配置，已自动回退到安全默认值 %d",
                safe_rpm,
                DEFAULT_SAFE_RPM,
            )
            safe_rpm = DEFAULT_SAFE_RPM
        elif safe_rpm > MAX_SAFE_RPM:
            self.logger.warning(
                "rpm=%d 超过安全阈值，已自动下调到 %d",
                safe_rpm,
                MAX_SAFE_RPM,
            )
            safe_rpm = MAX_SAFE_RPM

        return safe_workers, safe_rpm

    def init_database(self):
        """初始化玩家资料相关的数据库表"""
        cursor = self.db_manager.get_connection().cursor()

        # 玩家基础资料表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_profiles (
            uid TEXT PRIMARY KEY,
            current_name TEXT NOT NULL,
            avatar_url TEXT,
            join_date DATE,
            last_play_date DATE,
            total_play_time TEXT,
            gender TEXT,
            age INTEGER,
            location TEXT,
            bio TEXT,
            gold INTEGER,
            income INTEGER,
            charts_played_time TEXT,
            stable_charts INTEGER DEFAULT 0,
            unstable_charts INTEGER DEFAULT 0,
            chart_slots INTEGER DEFAULT 0,
            last_crawled TIMESTAMP NOT NULL,
            data_hash TEXT
        )
        """)

        # 玩家头衔/称号表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_titles (
            title_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            title TEXT NOT NULL,
            acquired_date DATE,
            FOREIGN KEY (uid) REFERENCES player_profiles(uid),
            UNIQUE(uid, title)
        )
        """)

        # 玩家成就徽章表 - 适配当前数据库结构（无achievement_img_url列）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_achievements (
            uid TEXT NOT NULL,
            achievement_code INTEGER NOT NULL,
            acquired_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (uid, achievement_code),
            FOREIGN KEY (uid) REFERENCES player_profiles(uid)
        )
        """)

        # 爬虫状态表（增强版）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS player_profile_crawl_status (
            uid TEXT PRIMARY KEY,
            last_crawled TIMESTAMP,
            last_success TIMESTAMP,
            crawl_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            last_error TEXT,
            data_hash TEXT,
            needs_update BOOLEAN DEFAULT 1,
            next_crawl_time TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES player_profiles(uid)
        )
        """)

        # 创建索引
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_titles_uid ON player_titles(uid)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_player_achievements_uid ON player_achievements(uid)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawl_status_last_crawled ON player_profile_crawl_status(last_crawled)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_crawl_status_needs_update ON player_profile_crawl_status(needs_update)"
        )

        ensure_schema(self.db_manager.get_connection())
        self.db_manager.get_connection().commit()
        self.logger.info("玩家资料数据库表初始化完成")

        # 确保player_identity表中有uid列
        self._ensure_uid_column()

    def _ensure_uid_column(self):
        """确保player_identity表有uid列"""
        try:
            cursor = self.db_manager.get_connection().cursor()
            cursor.execute("PRAGMA table_info(player_identity)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'uid' not in columns:
                cursor.execute('ALTER TABLE player_identity ADD COLUMN uid TEXT')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_player_identity_uid ON player_identity(uid)')
                self.logger.info("已添加uid字段到player_identity表")

            self.db_manager.get_connection().commit()
        except Exception as e:
            self.logger.warning("检查player_identity表结构时出错: %s", e)

    def generate_data_hash(self, profile_data):
        """生成玩家资料数据的哈希值"""
        # 排除动态变化的字段
        data_to_hash = {
            k: v for k, v in profile_data.items()
            if k not in ['last_crawled', 'data_hash']
        }
        data_str = json.dumps(data_to_hash, sort_keys=True, default=str)
        return hashlib.md5(data_str.encode('utf-8')).hexdigest()

    def extract_text_from_span(self, span_element):
        """从span元素中提取文本，处理&nbsp;等特殊字符"""
        if not span_element:
            return None

        text = span_element.get_text().strip()
        # 清理HTML实体和特殊字符
        text = text.replace('&nbsp;', ' ').strip()
        # 合并多个空格
        text = re.sub(r'\s+', ' ', text)
        return text if text else None

    def parse_player_profile_full(self, html, uid):
        """完整解析玩家个人主页 - 简化版本"""
        soup = BeautifulSoup(html, "html.parser")

        # 初始化profile数据
        profile = {
            "uid": uid,
            "current_name": None,
            "avatar_url": None,
            "join_date": None,
            "last_play_date": None,
            "total_play_time": None,
            "gender": None,
            "age": None,
            "location": None,
            "bio": None,
            "gold": None,
            "income": None,
            "charts_played_time": None,
            "stable_charts": None,
            "unstable_charts": None,
            "chart_slots": None,
            "titles": [],
            "achievements": [],
        }

        known_nulls = []
        parse_errors = []
        try:
            # 1. 提取用户名
            name_tag = soup.select_one("div.user_head .name span")
            if name_tag:
                profile["current_name"] = self.extract_text_from_span(name_tag)
                self.logger.debug("提取用户名: %s", profile["current_name"])
            else:
                # 备用方法：从meta标签提取
                og_title = soup.select_one("meta[property='og:title']")
                if og_title and og_title.get("content"):
                    profile["current_name"] = og_title.get("content").strip()
                    self.logger.debug("从meta标签提取用户名: %s", profile["current_name"])

            # 如果没有用户名，返回None
            if (
                not profile["current_name"]
                or not soup.select_one("div.user_head .right")
                or not profile["join_date"]
                and not soup.select_one("div.user_head .right p")
            ):
                self.logger.warning("玩家 %s 没有用户名，可能页面无效", uid)
                return None

            # 2. 提取头像URL
            avatar_img = soup.select_one("div.user_head .coverb img")
            if avatar_img and "src" in avatar_img.attrs:
                actual_uid = re.search(r"/avatar/(\d+)", avatar_img["src"])
                if actual_uid and int(actual_uid[1]) not in (0, int(uid)):
                    return None
                profile["avatar_url"] = avatar_img["src"]
                self.logger.debug("提取头像URL: %s", profile["avatar_url"])

            # 3. 直接根据HTML结构提取信息
            user_head = soup.select_one("div.user_head .right")
            if user_head:
                # 获取所有段落
                paragraphs = user_head.find_all("p")

                for p in paragraphs:
                    # 每个段落可能有多个span，直接提取所有span
                    spans = p.find_all("span")

                    for span in spans:
                        span_text = self.extract_text_from_span(span)
                        if not span_text:
                            continue

                        # 根据内容判断是什么字段
                        if span_text.startswith("Joined since:"):
                            date_str = span_text.replace("Joined since:", "").strip()
                            try:
                                profile["join_date"] = datetime.strptime(
                                    date_str, "%Y-%m-%d"
                                ).date()
                            except ValueError:
                                parse_errors.append("join_date")
                        elif span_text.startswith("Last play:"):
                            date_str = span_text.replace("Last play:", "").strip()
                            if date_str.lower() == "never":
                                known_nulls.append("last_play_date")
                            else:
                                try:
                                    profile["last_play_date"] = datetime.strptime(
                                        date_str, "%Y-%m-%d"
                                    ).date()
                                except ValueError:
                                    parse_errors.append("last_play_date")
                        elif span_text.startswith("Played:"):
                            profile["total_play_time"] = span_text.replace(
                                "Played:", ""
                            ).strip()
                        elif span_text.startswith("Gender:"):
                            profile["gender"] = span_text.replace("Gender:", "").strip()
                        elif span_text.startswith("Age:"):
                            age_text = span_text.replace("Age:", "").strip()
                            if age_text.isdigit():
                                profile["age"] = int(age_text)
                        elif span_text.startswith("Location:"):
                            profile["location"] = span_text.replace("Location:", "").strip()
                        elif span_text.startswith("Gold:"):
                            gold_text = (
                                span_text.replace("Gold:", "").replace(",", "").strip()
                            )
                            if gold_text.isdigit():
                                profile["gold"] = int(gold_text)
                        elif span_text.startswith("Income:"):
                            income_text = (
                                span_text.replace("Income:", "").replace(",", "").strip()
                            )
                            if income_text.isdigit():
                                profile["income"] = int(income_text)
                        elif span_text.startswith("Charts been played:"):
                            profile["charts_played_time"] = span_text.replace(
                                "Charts been played:", ""
                            ).strip()
                        elif span_text.startswith("Stable charts:"):
                            stable_text = span_text.replace("Stable charts:", "").strip()
                            if stable_text.isdigit():
                                profile["stable_charts"] = int(stable_text)
                        elif span_text.startswith("Unstable charts:"):
                            unstable_text = span_text.replace(
                                "Unstable charts:", ""
                            ).strip()
                            if unstable_text.isdigit():
                                profile["unstable_charts"] = int(unstable_text)
                        elif span_text.startswith("Chart slot:"):
                            slot_text = span_text.replace("Chart slot:", "").strip()
                            if slot_text.isdigit():
                                profile["chart_slots"] = int(slot_text)

            # 4. 提取头衔（使用em标签）
            title_ems = soup.select("div.user_head .name em")
            for em in title_ems:
                title = em.get_text().strip()
                if title and title not in profile["titles"]:
                    profile["titles"].append(title)
                    self.logger.debug("提取头衔: %s", title)

            # 5. 提取成就徽章 - 仅保存成就代码，不保存图片URL
            achievement_imgs = soup.select("div.ach img[src*='achieve']")
            for img in achievement_imgs:
                src = img.get("src", "")
                if not src:
                    continue

                # 过滤占位图
                if "justfyHold" in img.get("class", []):
                    continue

                # 从URL中提取成就代码
                match = re.search(r"/achieve/(\d+)", src)
                if match:
                    achievement_code = int(match.group(1))
                    # 检查是否已存在
                    existing = [
                        a
                        for a in profile["achievements"]
                        if a.get("code") == achievement_code
                    ]
                    if not existing:
                        profile["achievements"].append(
                            {"code": achievement_code, "image_url": src}
                        )
                        self.logger.debug("提取成就: %d", achievement_code)

            # 6. 提取个人简介
            wiki_div = soup.select_one("div.wiki.g_rblock.curr")
            if wiki_div:
                bio_text = wiki_div.get_text().strip()
                if wiki_div is not None:
                    # 清理文本
                    bio_text = re.sub(r"\s+", " ", bio_text)  # 合并空白字符
                    profile["bio"] = bio_text
                    self.logger.debug("提取个人简介，长度: %d", len(bio_text))

            self.logger.info(
                "解析完成 - UID: %s, 用户名: %s, 头衔: %d个, 成就: %d个",
                uid,
                profile["current_name"],
                len(profile["titles"]),
                len(profile["achievements"]),
            )

            profile["_source"] = "page_profile"
            profile["_observed_at"] = now()
            profile["_present"] = [
                k
                for k, v in profile.items()
                if not k.startswith("_")
                and v is not None
                and k
                not in (
                    "titles",
                    "achievements",
                    "stable_charts",
                    "unstable_charts",
                    "chart_slots",
                )
            ]
            profile["_present"] += known_nulls
            for field in ("gender", "location"):
                if profile[field] in ("???", "Unknown") and field in profile["_present"]:
                    profile[field] = None
                    profile["_present"].remove(field)
            for label, field in (
                ("Stable charts:", "stable_charts"),
                ("Unstable charts:", "unstable_charts"),
                ("Chart slot:", "chart_slots"),
            ):
                if profile[field] is not None:
                    profile["_present"].append(field)
            profile["_complete_groups"] = (
                ["titles"]
                if profile.get("join_date") and soup.select_one("div.rank")
                else []
            )
            if soup.select_one("div.ach"):
                profile["_complete_groups"].append("achievements")
            profile["_complete"] = (
                bool(profile.get("join_date"))
                and bool(soup.select_one("div.rank"))
                and not parse_errors
            )
            return profile

        except Exception as e:
            self.logger.error("解析玩家 %s 个人主页失败: %s", uid, e, exc_info=True)

            # 即使部分失败，也返回已提取的数据
            return None

    def fetch_player_profile(self, uid):
        """获取玩家个人主页HTML - 简化版本"""
        url = PLAYER_PROFILE_URL.format(uid=uid)
        self.last_fetch_state = "retry"

        try:
            self.logger.debug("请求玩家主页: %s", url)
            self.rate_limiter.wait_for_slot()
            response = self.session.get(url, timeout=30)
            self.rate_limiter.record_request(self.logger)

            # 检查状态码
            if (
                response.status_code == 404
                and "Page Not Found" in response.text
                and not is_login_page(response.text, response.url)
            ):
                self.last_fetch_state = "not_found"
                self.logger.info("玩家 %s 不存在 (404)", uid)
                return None
            elif response.status_code != 200:
                self.logger.warning("玩家 %s 返回状态码: %d", uid, response.status_code)
                return None

            # 检查页面内容是否有效
            if len(response.content) < 100:
                self.logger.warning("玩家 %s 页面内容过短，可能无效", uid)
                return None

            # 直接返回HTML，让解析函数处理
            if is_login_page(response.text, getattr(response, "url", "")):
                self.last_fetch_state = "auth_required"
                self.auth_required_detected = True
                self.logger.error("玩家页面返回登录页，请更新本地凭据")
                return None
            self.last_fetch_state = "fetched"
            return response.text

        except requests.exceptions.RequestException as e:
            self.logger.error("请求失败获取玩家 %s: %s", uid, e)
            return None
        except Exception as e:
            self.logger.error("获取玩家 %s 数据时出错: %s", uid, e)
            return None

    def save_player_profile(self, profile_data):
        if not profile_data or not profile_data.get("current_name"):
            return None
        conn = self.db_manager.get_connection()
        uid = str(profile_data["uid"])
        stamp = datetime.now()
        try:
            with atomic(conn):
                ensure_schema(conn)
                from crawlers.ingestion import time_text

                prior = conn.execute(
                    "SELECT observed_at FROM crawl_observations WHERE entity='player_profiles' AND object_id=? AND section='record'",
                    (uid,),
                ).fetchone()
                if prior and time_text(
                    profile_data.get("_observed_at") or stamp
                ) < time_text(prior[0]):
                    return "unchanged"
                if conn.execute(
                    "SELECT 1 FROM player_profiles WHERE current_name=? AND uid!=?",
                    (profile_data["current_name"], uid),
                ).fetchone():
                    raise ValueError("Current name conflicts with a different UID")
                old = conn.execute(
                    "SELECT data_hash FROM player_profiles WHERE uid=?", (uid,)
                ).fetchone()
                incoming = dict(profile_data)
                incoming["uid"] = uid
                incoming["last_crawled"] = stamp
                incoming["data_hash"] = self.generate_data_hash(public_record(profile_data))
                if "_present" in incoming:
                    incoming["_present"] = list(incoming["_present"]) + [
                        "last_crawled",
                        "data_hash",
                    ]
                allowed = {r[1] for r in conn.execute("PRAGMA table_info(player_profiles)")}
                merged, changed = save_record(
                    conn, "player_profiles", "uid", uid, incoming, allowed
                )
                groups = set(profile_data.get("_complete_groups", ()))
                for group, table, key in (
                    ("titles", "player_titles", "title"),
                    ("achievements", "player_achievements", "achievement_code"),
                ):
                    values = profile_data.get(group, [])
                    if (
                        group == "achievements"
                        and conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE name='achievement_catalog'"
                        ).fetchone()
                    ):
                        for achievement in values:
                            if achievement.get("image_url"):
                                conn.execute(
                                    "INSERT INTO achievement_catalog(code,img_url) VALUES(?,?) ON CONFLICT(code) DO UPDATE SET img_url=excluded.img_url",
                                    (achievement["code"], achievement["image_url"]),
                                )
                    values = [v if group == "titles" else v.get("code") for v in values]
                    values = [v for v in values if v is not None]
                    if group in groups:
                        if values:
                            placeholders = ",".join("?" for _ in values)
                            conn.execute(
                                f"DELETE FROM {table} WHERE uid=? AND {key} NOT IN ({placeholders})",
                                (uid, *values),
                            )
                        else:
                            conn.execute(f"DELETE FROM {table} WHERE uid=?", (uid,))
                    for value in values:
                        conn.execute(
                            f"INSERT OR IGNORE INTO {table}(uid,{key},acquired_date,first_observed_at) VALUES(?,?,NULL,?)",
                            (uid, value, stamp.isoformat()),
                        )
                    observe(
                        conn, "player_profiles", uid, group, "page_profile", group in groups
                    )
                complete = bool(profile_data.get("_complete", True))
                conn.execute(
                    """INSERT INTO player_profile_crawl_status(uid,last_crawled,last_success,crawl_count,success_count,error_count,needs_update,next_crawl_time,data_hash)
                    VALUES(?,?,?,1,1,0,?,?,?) ON CONFLICT(uid) DO UPDATE SET
                    last_crawled=excluded.last_crawled,last_success=excluded.last_success,
                    crawl_count=crawl_count+1,success_count=success_count+1,last_error=NULL,
                    needs_update=excluded.needs_update,next_crawl_time=excluded.next_crawl_time,data_hash=excluded.data_hash""",
                    (
                        uid,
                        stamp,
                        stamp,
                        int(not complete),
                        (
                            stamp + timedelta(days=30)
                            if complete
                            else stamp + timedelta(hours=6)
                        ),
                        incoming["data_hash"],
                    ),
                )
            return "new" if not old else "updated" if changed else "unchanged"
        except Exception as exc:
            self.logger.error("Profile save rolled back for UID %s: %s", uid, exc)
            # The business transaction has already rolled back before this commit.
            with atomic(conn):
                observe(
                    conn,
                    "player_profiles",
                    uid,
                    "failure",
                    "page_profile",
                    False,
                    detail={"error": str(exc)},
                )
                (
                    conn.execute(
                        """INSERT INTO player_profile_crawl_status(uid,last_crawled,crawl_count,error_count,needs_update,next_crawl_time,last_error)
                    VALUES(?,?,1,1,1,?,?) ON CONFLICT(uid) DO UPDATE SET last_crawled=excluded.last_crawled,
                    crawl_count=crawl_count+1,error_count=error_count+1,needs_update=1,next_crawl_time=excluded.next_crawl_time,last_error=excluded.last_error""",
                        (uid, stamp, stamp + timedelta(hours=6), str(exc)),
                    )
                    if conn.execute(
                        "SELECT 1 FROM player_profiles WHERE uid=?", (uid,)
                    ).fetchone()
                    else None
                )
            return None

    def crawl_player_profile(self, uid, print_only=False, stats=None, stats_lock=None):
        uid = str(uid)
        if not print_only and uid in self.processed_uids:
            return True
        html = self.fetch_player_profile(uid)
        if not html:
            return False
        data = self.parse_player_profile_full(html, uid)
        if not data:
            return False
        if print_only:
            self.print_profile_data(data)
            return True
        ranks = parse_rankings(html, uid)
        observed_at = (
            datetime.fromisoformat(data["_observed_at"])
            if data.get("_observed_at")
            else datetime.now()
        )
        conn = self.db_manager.get_connection()
        rank_stats = dict.fromkeys(
            ("new", "diff_insert", "same_insert", "update", "update_fill"), 0
        )
        try:
            with atomic(conn):
                op = self.save_player_profile(data)
                if op is None:
                    raise ValueError("Profile save failed")
                player_id = resolve_player_identity(data["current_name"], observed_at, uid)
                if player_id is None:
                    raise ValueError("Identity conflict")
                for row in ranks:
                    result = save_player_ranking_record(
                        player_id,
                        uid,
                        row["mode"],
                        row["rank"],
                        row["name"],
                        row.get("lv"),
                        row.get("exp"),
                        row.get("acc"),
                        row.get("combo"),
                        row.get("pc"),
                        observed_at,
                        "page_profile",
                    )
                    if result in rank_stats:
                        rank_stats[result] += 1
                complete = bool(data.get("_complete", True)) and bool(
                    getattr(ranks, "complete", True)
                )
                observe(
                    conn,
                    "player_profiles",
                    uid,
                    "ranks",
                    "page_profile",
                    bool(getattr(ranks, "complete", True)),
                )
                if not complete:
                    conn.execute(
                        "UPDATE player_profile_crawl_status SET needs_update=1,next_crawl_time=?,last_error=? WHERE uid=?",
                        (
                            datetime.now() + timedelta(hours=6),
                            "partial profile or rankings",
                            uid,
                        ),
                    )
            if stats is not None and stats_lock is not None:
                with stats_lock:
                    key = "profile_" + op
                    if key in stats:
                        stats[key] += 1
                    for key, value in rank_stats.items():
                        if "rank_" + key in stats:
                            stats["rank_" + key] += value
            if complete:
                self.processed_uids.add(uid)
            return complete
        except Exception as exc:
            self.logger.error("Player UID %s transaction rolled back: %s", uid, exc)
            with atomic(conn):
                observe(
                    conn,
                    "player_profiles",
                    uid,
                    "failure",
                    "page_profile",
                    False,
                    detail={"error": str(exc)},
                )
                conn.execute(
                    "UPDATE player_profile_crawl_status SET needs_update=1,next_crawl_time=?,last_error=? WHERE uid=?",
                    (datetime.now() + timedelta(hours=6), str(exc), uid),
                )
            return False

    def print_profile_data(self, profile_data):
        """在终端打印解析出的玩家数据"""
        print("\n" + "="*80)
        print("玩家资料解析结果 (仅打印，不保存)")
        print("="*80)

        # 基本信息
        print(f"UID: {profile_data.get('uid', 'N/A')}")
        print(f"用户名: {profile_data.get('current_name', 'N/A')}")
        print(f"头像URL: {profile_data.get('avatar_url', 'N/A')[:50]}..." if profile_data.get('avatar_url') else "头像URL: N/A")

        # 日期信息
        print(f"\n时间信息:")
        print(f"  加入日期: {profile_data.get('join_date', 'N/A')}")
        print(f"  最后游玩: {profile_data.get('last_play_date', 'N/A')}")
        print(f"  总游玩时长: {profile_data.get('total_play_time', 'N/A')}")

        # 个人信息
        print(f"\n个人信息:")
        print(f"  性别: {profile_data.get('gender', 'N/A')}")
        print(f"  年龄: {profile_data.get('age', 'N/A')}")
        print(f"  地区: {profile_data.get('location', 'N/A')}")

        # 游戏数据
        print(f"\n游戏数据:")
        print(f"  金币: {profile_data.get('gold', 'N/A')}")
        print(f"  收入: {profile_data.get('income', 'N/A')}")
        print(f"  谱面游玩时长: {profile_data.get('charts_played_time', 'N/A')}")
        print(f"  稳定谱面: {profile_data.get('stable_charts', 'N/A')}")
        print(f"  不稳定谱面: {profile_data.get('unstable_charts', 'N/A')}")
        print(f"  谱面槽位: {profile_data.get('chart_slots', 'N/A')}")

        # 头衔
        titles = profile_data.get('titles', [])
        if titles:
            print(f"\n头衔 ({len(titles)} 个):")
            for i, title in enumerate(titles, 1):
                print(f"  {i}. {title}")
        else:
            print(f"\n头衔: 无")

        # 成就 - 只显示成就代码，无图片URL
        achievements = profile_data.get('achievements', [])
        if achievements:
            print(f"\n成就徽章 ({len(achievements)} 个):")
            for i, achievement in enumerate(achievements, 1):
                print(f"  {i}. 成就代码: {achievement.get('code', 'N/A')}")
        else:
            print(f"\n成就徽章: 无")

        # 个人简介
        bio = profile_data.get('bio', '')
        if bio:
            print(f"\n个人简介 (长度: {len(bio)}):")
            # 限制显示长度
            if len(bio) > 500:
                print(f"  {bio[:500]}...")
            else:
                print(f"  {bio}")
        else:
            print(f"\n个人简介: 无")

        # 数据哈希
        data_hash = self.generate_data_hash(profile_data)
        print(f"\n数据哈希: {data_hash[:16]}...")

        print("\n" + "="*80)

        return True

    def test_parse_and_print(self, uid):
        """测试解析并打印单个玩家的数据"""
        self.logger.info("测试解析玩家: %s", uid)

        # 获取HTML页面
        html = self.fetch_player_profile(uid)
        if not html:
            self.logger.error("获取玩家 %s 页面失败或无数据", uid)
            return False

        # 解析HTML
        profile_data = self.parse_player_profile_full(html, uid)
        if not profile_data:
            self.logger.error("解析玩家 %s 数据失败", uid)
            return False

        # 打印数据
        self.print_profile_data(profile_data)
        return True



    # ========== 新增：全局位图范围爬取方法 ==========
    def crawl_players_batch(
        self, uid_list, max_workers=3, requests_per_minute=15, print_only=False
    ):
        from concurrent.futures import ThreadPoolExecutor

        workers, rpm = self._sanitize_crawl_limits(max_workers, requests_per_minute)
        self.rate_limiter.set_rate(rpm)
        unique = list(
            dict.fromkeys(
                str(uid).strip() for uid in uid_list if str(uid).strip().isdigit()
            )
        )
        store = (
            TaskStore(
                self.db_manager.get_connection(),
                getattr(self, "_batch_scope", "profiles:explicit"),
            )
            if not print_only
            else None
        )
        if store:
            with atomic(store.conn):
                for uid in unique:
                    store.add("player", uid)
                    due = store.conn.execute(
                        "SELECT next_crawl_time FROM player_profile_crawl_status WHERE uid=?",
                        (uid,),
                    ).fetchone()
                    if not due or due[0] is None or str(due[0]) <= str(datetime.now()):
                        store.conn.execute(
                            "UPDATE crawl_tasks SET state='pending',next_attempt=NULL WHERE scope=? AND kind='player' AND object_id=? AND state IN ('done','not_found')",
                            (store.scope, uid),
                        )
            unique = [
                object_id
                for _, object_id, _ in store.claim(
                    len(unique), kind="player", object_ids=unique
                )
            ]
            self.processed_uids.difference_update(unique)

        def work(uid):
            if is_stop_requested():
                return uid, None
            try:
                return uid, self.crawl_player_profile(uid, print_only=print_only)
            except Exception as exc:
                self.logger.error("UID %s failed: %s", uid, exc)
                return uid, False

        good = bad = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for uid, result in executor.map(work, unique):
                if result:
                    good += 1
                elif result is False:
                    bad += 1
                if store:
                    store.finish(
                        "player",
                        uid,
                        state=(
                            "done" if result else "retry" if result is False else "pending"
                        ),
                        error=None if result else "not complete",
                        retry_seconds=6 * 3600,
                    )
        return good, bad

    def crawl_uid_range(
        self,
        start_uid,
        end_uid,
        resume_file=os.path.join(DATA_DIR, "global_progress.bin"),
        save_interval=10,
        max_workers=3,
        requests_per_minute=15,
        print_only=False,
    ):
        """Refresh due records; a legacy discovery bitmap is not a freshness claim."""
        if start_uid < 1 or end_uid < start_uid:
            raise ValueError("Invalid UID range")
        # Bounded chunks avoid constructing a list containing millions of UIDs.
        total_ok = total_fail = 0
        for start in range(start_uid, end_uid + 1, 1000):
            if is_stop_requested():
                break
            ids = (str(uid) for uid in range(start, min(start + 1000, end_uid + 1)))
            ok, failed = self.crawl_players_batch(
                ids,
                max_workers=max_workers,
                requests_per_minute=requests_per_minute,
                print_only=print_only,
            )
            total_ok += ok
            total_fail += failed
        return total_ok, total_fail

    def _print_stats(self, stats, total_players, success, failed):
        """输出详细的统计报告（彩色）"""
        print("\n" + "="*70)
        print(colorize("                    爬取统计报告", "1;36"))
        print("="*70)

        # 玩家处理概况
        print(f"总计玩家: {total_players}")
        print(f"成功: {colorize(str(success), '92')} | 失败: {colorize(str(failed), '91')}")
        print("-"*70)

        # 资料统计
        print(colorize("玩家资料变动详情:", "1;33"))
        total_profile = stats['profile_new'] + stats['profile_updated'] + stats['profile_unchanged']
        print(f"  首次插入: {colorize(str(stats['profile_new']), '92')} (新增资料)")
        print(f"  数据更新: {colorize(str(stats['profile_updated']), '93')} (已有资料变化)")
        print(f"  未变化:   {colorize(str(stats['profile_unchanged']), '94')} (仅更新时间)")
        print(f"  失败:     {colorize(str(stats['profile_failed']), '91')}")
        print()

        # 排名记录统计
        print(colorize("玩家排名记录变动详情:", "1;33"))
        print(f"  首次插入:   {colorize(str(stats['rank_new']), '92')} (新模式首次记录)")
        print(f"  变化插入:   {colorize(str(stats['rank_diff_insert']), '93')} (数据变化)")
        print(f"  相同插入:   {colorize(str(stats['rank_same_insert']), '94')} (相同数据第二行)")
        print(f"  时间更新:   {colorize(str(stats['rank_update']), '95')} (连续相同数据更新时间)")
        print(f"  LV填充:     {colorize(str(stats['rank_update_fill']), '96')} (填充缺失等级)")
        total_rank = stats['rank_new'] + stats['rank_diff_insert'] + stats['rank_same_insert'] + stats['rank_update'] + stats['rank_update_fill']
        print(f"  总计操作:   {total_rank} 条")
        print("="*70)

    def crawl_from_database(self, limit=None, days_since_last_crawl=30):
        conn = self.db_manager.get_connection()
        cutoff = datetime.now() - timedelta(days=days_since_last_crawl)
        query = """WITH known(uid) AS (
            SELECT uid FROM player_profiles UNION SELECT uid FROM player_identity WHERE uid IS NOT NULL
            UNION SELECT uid FROM player_profile_crawl_status
            UNION SELECT player_identifier FROM player_config WHERE is_active=1
            UNION SELECT uid FROM player_rankings WHERE uid IS NOT NULL
            UNION SELECT uid FROM player_rankings_mm WHERE uid IS NOT NULL
            UNION SELECT uid FROM player_mmr_samples WHERE uid IS NOT NULL)
            SELECT k.uid FROM known k LEFT JOIN player_profile_crawl_status s ON k.uid=s.uid
            WHERE k.uid IS NOT NULL AND k.uid!='' AND
            (s.uid IS NULL OR ((s.next_crawl_time IS NULL OR s.next_crawl_time<=?) AND
            (s.needs_update=1 OR s.last_success IS NULL OR s.last_success<?)))
            ORDER BY COALESCE(s.last_success,''),k.uid"""
        params = [datetime.now(), cutoff]
        query += " LIMIT ?"
        params.append(limit if limit is not None else 1000)
        return [row[0] for row in conn.execute(query, params)]

    def crawl_from_leaderboard(self, mode=0, limit=100):
        from crawlers.rankings import crawl_mode_player

        frame = crawl_mode_player(self.session, mode, limit)
        result = FetchList(
            frame["player_id"].tolist() if not frame.empty else [],
            complete=frame.attrs.get("complete", False),
        )
        return result

    def crawl_by_uid_range(self, start_uid, end_uid, step=1, print_only=False):
        if step < 1 or start_uid < 1 or end_uid < start_uid:
            raise ValueError("Invalid UID range")
        if step == 1:
            return self.crawl_uid_range(start_uid, end_uid, print_only=print_only)
        from itertools import islice

        values = iter(range(start_uid, end_uid + 1, step))
        good = bad = 0
        while not is_stop_requested():
            chunk = list(islice(values, 1000))
            if not chunk:
                break
            ok, failed = self.crawl_players_batch(chunk, print_only=print_only)
            good += ok
            bad += failed
        return good, bad

    def get_progress_status(self):
        store = TaskStore(
            self.db_manager.get_connection(),
            getattr(self, "_batch_scope", "profiles:explicit"),
        )
        return "玩家持久任务状态: " + json.dumps(store.counts(), ensure_ascii=False)

    def test_connection(self):
        """测试连接"""
        test_uid = "858752"  # 使用之前成功的UID作为测试
        self.logger.info("测试连接，爬取玩家: %s", test_uid)

        success = self.crawl_player_profile(test_uid)
        if success:
            self.logger.info("连接测试成功")
            return True
        else:
            self.logger.error("连接测试失败")
            return False

# 修改后的信号处理器：设置标志，打印彩色消息，不直接退出
def signal_handler(sig, frame):
    """处理终止信号"""
    from crawlers import rankings

    with rankings.stop_lock:
        rankings.stop_requested = True
    # 彩色输出
    msg = "收到终止信号，正在等待当前任务完成并安全退出..."
    print(colorize(msg, "1;33"))  # 黄色加粗
    logging.getLogger().info(msg)
    # 不调用 sys.exit，让主循环检查 stop_requested 并自然退出

def read_uid_file(file_path):
    """读取UID文件，忽略空行和注释行（# 或 //）"""
    uid_list = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 忽略空行和注释行
                if not line or line.startswith('#') or line.startswith('//'):
                    continue
                uid_list.append(line)
        return uid_list
    except Exception as e:
        logging.getLogger().error("读取UID文件失败: %s", e)
        return None

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='玩家个人主页资料爬虫')

    # 爬取源选项
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument('--uid', type=str, help='单个玩家UID')
    source_group.add_argument('--uid-list', type=str, help='逗号分隔的UID列表')
    source_group.add_argument('--uid-range', type=str, help='UID范围，格式: start-end (如: 1000-2000)')
    source_group.add_argument('--uid-file', type=str, help='包含UID列表的文件，每行一个')
    source_group.add_argument('--from-db', action='store_true', help='从数据库获取需要更新的玩家')
    source_group.add_argument('--from-leaderboard', action='store_true', help='从排行榜获取玩家')
    source_group.add_argument('--leaderboard-mode', type=int, default=0, help='排行榜模式 (默认: 0)')

    # 控制选项
    parser.add_argument('--limit', type=int, help='最大爬取数量')
    parser.add_argument('--days-since-update', type=int, default=30,
                       help='多少天未更新视为需要更新 (默认: 30天)')
    parser.add_argument('--max-workers', type=int, default=3,
                       help='最大并发线程数 (默认: 3)')
    parser.add_argument('--rpm', type=int, default=15,
                       help='每分钟请求数 (默认: 15)')
    parser.add_argument('--test', action='store_true', help='测试连接')
    parser.add_argument('--print-only', action='store_true',
                       help='仅解析并打印数据，不保存到数据库')
    parser.add_argument('--status', action='store_true', help='显示数据库状态')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='日志级别 (默认: INFO)')
    parser.add_argument('--log-file', help='指定日志文件路径')
    # 新增参数：禁用默认读取players.txt
    parser.add_argument('--no-default-players', action='store_true',
                       help='不自动使用默认的players.txt文件作为UID源')

    # 中断恢复相关参数
    parser.add_argument('--resume-file', type=str, default=os.path.join(DATA_DIR, 'global_progress.bin'),
                       help='全局进度文件 (默认: global_progress.bin)')
    parser.add_argument('--save-interval', type=int, default=10,
                       help='进度保存间隔(秒) (默认: 10)')

    args = parser.parse_args()

    # 设置信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 设置日志
    log_level = getattr(logging, args.log_level)
    setup_detailed_logging(log_level=log_level, log_file=args.log_file)

    logger = logging.getLogger(__name__)
    if args.max_workers < 1:
        logger.warning("max_workers=%d 非法，已重置为 1", args.max_workers)
        args.max_workers = 1
    elif args.max_workers > MAX_SAFE_WORKERS:
        logger.warning(
            "max_workers=%d 超过安全阈值，已下调为 %d",
            args.max_workers,
            MAX_SAFE_WORKERS,
        )
        args.max_workers = MAX_SAFE_WORKERS

    if args.rpm <= 0:
        logger.warning("rpm=%d 非法，已重置为 %d", args.rpm, DEFAULT_SAFE_RPM)
        args.rpm = DEFAULT_SAFE_RPM
    elif args.rpm > MAX_SAFE_RPM:
        logger.warning("rpm=%d 超过安全阈值，已下调为 %d", args.rpm, MAX_SAFE_RPM)
        args.rpm = MAX_SAFE_RPM
    logger.info("玩家个人主页爬虫启动，参数: %s", vars(args))

    # 初始化数据库（如果需要保存的话）
    if not args.print_only:
        init_database()

    # 创建爬虫实例
    crawler = PlayerProfileCrawler()

    # 显示状态
    if args.status:
        if not args.print_only:
            cursor = crawler.db_manager.get_connection().cursor()
            cursor.execute("SELECT COUNT(*) FROM player_profiles")
            profile_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM player_titles")
            title_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM player_achievements")
            achievement_count = cursor.fetchone()[0]

            cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN needs_update = 1 THEN 1 ELSE 0 END) as need_update,
                SUM(CASE WHEN last_crawled IS NULL THEN 1 ELSE 0 END) as never_crawled
            FROM player_profile_crawl_status
            ''')
            status_result = cursor.fetchone()

            print("玩家资料数据库状态:")
            print(f"  玩家资料数: {profile_count}")
            print(f"  头衔记录数: {title_count}")
            print(f"  成就记录数: {achievement_count}")
            print(f"  爬虫状态记录: {status_result[0]}")
            print(f"  需要更新: {status_result[1]}")
            print(f"  从未爬取: {status_result[2]}")
        else:
            print("在 --print-only 模式下无法显示数据库状态")
        return

    # 测试连接
    if args.test:
        if crawler.test_connection():
            logger.info("连接测试成功")
        else:
            logger.error("连接测试失败")
        return

    # 准备UID列表
    uid_list = []

    # 检查是否指定了任何UID源
    has_source = any([
        args.uid, args.uid_list, args.uid_range,
        args.uid_file, args.from_db, args.from_leaderboard
    ])

    # 如果没有指定任何源且没有禁用默认players.txt，则自动使用默认文件
    if not has_source and not args.no_default_players:
        default_file = "players.txt"
        if os.path.exists(default_file):
            logger.info("未指定UID源，自动使用默认文件: %s", default_file)
            args.uid_file = default_file
        else:
            logger.error("未指定任何UID源，且默认文件 %s 不存在，请指定源或创建文件", default_file)
            return

    # 按优先级处理各源
    if args.uid:
        uid_list = [args.uid.strip()]
        success, fail = crawler.crawl_players_batch(
            uid_list,
            max_workers=args.max_workers,
            requests_per_minute=args.rpm,
            print_only=args.print_only
        )

    elif args.uid_list:
        uid_list = [uid.strip() for uid in args.uid_list.split(',') if uid.strip()]
        success, fail = crawler.crawl_players_batch(
            uid_list,
            max_workers=args.max_workers,
            requests_per_minute=args.rpm,
            print_only=args.print_only
        )

    elif args.uid_range:
        try:
            start_str, end_str = args.uid_range.split('-')
            start_uid = int(start_str.strip())
            end_uid = int(end_str.strip())
            # 使用范围爬取（支持中断恢复，全局位图进度文件）
            success, fail = crawler.crawl_uid_range(
                start_uid, end_uid,
                resume_file=args.resume_file,
                save_interval=args.save_interval,
                max_workers=args.max_workers,
                requests_per_minute=args.rpm,
                print_only=args.print_only
            )
        except ValueError:
            logger.error("UID范围格式错误，应为: start-end (如: 1000-2000)")
            return

    elif args.uid_file:
        # 使用增强的文件读取函数，支持注释和空行过滤
        uid_list = read_uid_file(args.uid_file)
        if uid_list is None:
            return
        success, fail = crawler.crawl_players_batch(
            uid_list,
            max_workers=args.max_workers,
            requests_per_minute=args.rpm,
            print_only=args.print_only
        )

    elif args.from_db and not args.print_only:
        # 仅当需要保存时才从数据库获取
        uid_list = crawler.crawl_from_database(
            limit=args.limit,
            days_since_last_crawl=args.days_since_update
        )
        if uid_list:
            success, fail = crawler.crawl_players_batch(
                uid_list,
                max_workers=args.max_workers,
                requests_per_minute=args.rpm,
                print_only=args.print_only
            )
        else:
            logger.info("没有需要更新的玩家")
            return

    elif args.from_leaderboard:
        uid_list = crawler.crawl_from_leaderboard(
            mode=args.leaderboard_mode,
            limit=args.limit
        )
        if uid_list:
            success, fail = crawler.crawl_players_batch(
                uid_list,
                max_workers=args.max_workers,
                requests_per_minute=args.rpm,
                print_only=args.print_only
            )
        else:
            logger.info("从排行榜未获取到有效玩家")
            return

    # 如果没有获取到任何UID，给出提示
    if not uid_list and args.uid is None and args.uid_range is None and args.uid_file is None and args.uid_list is None:
        logger.warning("没有找到需要爬取的玩家")
        return

    # 非范围源的处理已经在各分支中完成，这里只记录完成信息
    if not args.print_only and args.uid_range is None:  # 范围源已经在方法内部输出统计
        logger.info("爬取完成: 成功 %d, 失败 %d", success, fail)

        # 显示最终状态
        cursor = crawler.db_manager.get_connection().cursor()
        cursor.execute("SELECT COUNT(*) FROM player_profiles")
        total = cursor.fetchone()[0]
        logger.info("数据库中共有 %d 个玩家资料", total)

if __name__ == "__main__":
    main()
