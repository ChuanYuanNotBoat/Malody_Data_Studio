# malody_api/routers/page_parser.py
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import aiohttp
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query, HTTPException
from malody_api.core.database import get_db_connection
from malody_api.core.models import APIResponse
from malody_api.utils.crawler_manager import crawler_manager

router = APIRouter(prefix="/page-parser", tags=["page-parser"])
logger = logging.getLogger(__name__)

# 冷却时间跟踪（内存中）
crawler_cooldown = {}

# 谱面状态映射
STATUS_MAP = {
    "Stable": 2,
    "Beta": 1,
    "Alpha": 0
}

# 模式映射
MODE_MAP = {
    0: "Key",
    1: "Step",
    2: "DJ",
    3: "Catch",
    4: "Pad",
    5: "Taiko",
    6: "Ring",
    7: "Slide",
    8: "Live",
    9: "Cube"
}

# 加载Mod映射配置（占位符）
MOD_MAPPING = {}
try:
    mod_mapping_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'mod_mapping.json')
    with open(mod_mapping_path, 'r', encoding='utf-8') as f:
        MOD_MAPPING = json.load(f)
    logger.info("Loaded mod mapping entries: %s", len(MOD_MAPPING))
except Exception as e:
    logger.warning("Failed to load mod mapping: %s; using fallback mapping", e)
    # 创建占位符映射
    MOD_MAPPING = {f"g_mod_{i}": f"mod_{i}" for i in range(20)}

class PageParserService:
    """页面解析服务 - 专注于排行榜解析"""

    def __init__(self):
        self.base_url = "https://m.mugzone.net"
        self.session = None

    async def get_session(self):
        """获取aiohttp会话"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session

    async def close_session(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
            self.session = None

    async def parse_chart_page(self, cid: int) -> Dict[str, Any]:
        """解析谱面页面 - 专注于排行榜数据"""
        session = await self.get_session()
        url = f"{self.base_url}/chart/{cid}"

        try:
            async with session.get(url) as response:
                if response.status == 404:
                    return {"error": f"谱面不存在: {cid}"}
                elif response.status != 200:
                    return {"error": f"页面获取失败: {response.status}"}

                html = await response.text()
                return await self._parse_chart_html(html, cid)

        except aiohttp.ClientError as e:
            return {"error": f"网络请求失败: {str(e)}"}
        except Exception as e:
            return {"error": f"解析失败: {str(e)}"}
        finally:
            await self.close_session()

    async def _parse_chart_html(self, html: str, cid: int) -> Dict[str, Any]:
        """解析谱面页面HTML - 专注于排行榜数据"""
        soup = BeautifulSoup(html, 'html.parser')

        # 解析基础谱面信息（仅用于上下文）
        chart_info = await self._parse_basic_chart_info(soup, cid)

        # 解析排行榜数据（核心功能）
        ranking_data = await self._parse_ranking_data(soup)

        return {
            "chart_info": chart_info,
            "ranking": ranking_data,
            "parsed_at": datetime.now().isoformat(),
            "total_rankings": len(ranking_data)
        }

    async def _parse_basic_chart_info(self, soup, cid: int) -> Dict[str, Any]:
        """解析基础谱面信息（仅用于上下文）"""
        song_title_div = soup.find('div', class_='song_title')
        if not song_title_div:
            return {"cid": cid, "error": "无法找到谱面信息"}

        # 只提取最基础的信息用于上下文
        right_div = song_title_div.find('div', class_='right')
        title_h3 = right_div.find('h3', class_='textfix') if right_div else None
        title_h2 = right_div.find('h2', class_='textfix title') if right_div else None

        title_en = title_h3.get_text(strip=True) if title_h3 else None
        title_jp = title_h2.get_text(strip=True) if title_h2 else None

        # 提取SID（用于关联数据库）
        sub_h2 = right_div.find('h2', class_='sub') if right_div else None
        sid = None
        if sub_h2:
            sub_text = sub_h2.get_text()
            id_match = re.search(r'ID:c?(\d+)', sub_text)
            sid = int(id_match.group(1)) if id_match else None

        return {
            "cid": cid,
            "sid": sid,
            "title_en": title_en,
            "title_jp": title_jp
        }

    async def _parse_ranking_data(self, soup) -> List[Dict[str, Any]]:
        """解析排行榜数据 - 核心功能"""
        ranking_list = soup.find('ul', class_='list')
        if not ranking_list:
            return []

        rankings = []
        current_judge = self._get_current_judge(soup)

        for item in ranking_list.find_all('li'):
            ranking_data = await self._parse_ranking_item(item, current_judge)
            if ranking_data:
                rankings.append(ranking_data)

        return rankings

    def _get_current_judge(self, soup) -> str:
        """获取当前判定难度"""
        judge_select = soup.find('select', id='g_judge')
        if judge_select:
            selected_option = judge_select.find('option', selected=True)
            if selected_option:
                return selected_option.get_text(strip=True)
        return "All"

    async def _parse_ranking_item(self, item, judge: str) -> Dict[str, Any]:
        """解析单个排行榜项目"""
        try:
            # 排名信息
            rank = self._parse_rank(item)

            # 玩家信息
            player_info = self._parse_player_info(item)

            # 分数和统计信息
            score_info = self._parse_score_info(item)

            # 准确率信息
            accuracy_info = self._parse_accuracy_info(item)

            # Mod信息
            mods = self._parse_mods(item)

            # 时间信息
            achieved_time = self._parse_time_info(item)

            # 打击统计
            hit_stats = self._parse_hit_stats(item)

            return {
                "rank": rank,
                "player": player_info,
                **score_info,
                **accuracy_info,
                "mods": mods,
                "achieved_time": achieved_time,
                "judge": judge,
                "hit_stats": hit_stats
            }
        except Exception as e:
            logger.warning("Failed to parse ranking item: %s", e)
            return None

    def _parse_rank(self, item) -> Optional[int]:
        """解析排名 - 支持前3名和后续排名"""
        # 先尝试从 i.label 类中提取前3名
        rank_label = item.find('i', class_=re.compile(r'label top-\d+'))
        if rank_label:
            class_name = ' '.join(rank_label.get('class', []))
            rank_match = re.search(r'top-(\d+)', class_name)
            if rank_match:
                return int(rank_match.group(1))

        # 否则尝试从 span.rank 中提取
        rank_span = item.find('span', class_='rank')
        if rank_span:
            rank_text = rank_span.get_text(strip=True)
            # 可能包含 # 号，如 "#4"
            if rank_text.startswith('#'):
                rank_text = rank_text[1:]
            try:
                return int(rank_text)
            except ValueError:
                pass

        return None

    def _parse_player_info(self, item) -> Dict[str, Any]:
        """解析玩家信息"""
        rank_span = item.find('span', class_='rank')
        rank_img = rank_span.find('img') if rank_span else None

        name_span = item.find('span', class_='name')
        name_link = name_span.find('a') if name_span else None

        player_uid = self._extract_uid_from_url(name_link.get('href', '')) if name_link else None
        player_name = name_link.get_text(strip=True) if name_link else None
        player_avatar = rank_img.get('src') if rank_img else None

        return {
            "uid": player_uid,
            "name": player_name,
            "avatar": player_avatar
        }

    def _parse_score_info(self, item) -> Dict[str, Any]:
        """解析分数信息"""
        score_span = item.find('span', class_='score')
        combo_span = item.find('span', class_='combo')

        score = None
        combo = None

        if score_span and score_span.get_text(strip=True):
            try:
                score = int(score_span.get_text(strip=True))
            except ValueError:
                pass

        if combo_span and combo_span.get_text(strip=True):
            try:
                combo = int(combo_span.get_text(strip=True))
            except ValueError:
                pass

        return {
            "score": score,
            "combo": combo
        }

    def _parse_accuracy_info(self, item) -> Dict[str, Any]:
        """解析准确率信息"""
        acc_span = item.find('span', class_='acc')
        if not acc_span:
            return {}

        acc_round = acc_span.find('i', class_='g_round')
        acc_text = acc_span.find('em')

        accuracy_percent = None
        accuracy_width = None
        accuracy_color = None

        if acc_round:
            style = acc_round.get('style', '')
            if 'width:' in style:
                accuracy_width = style.split('width:')[-1].split(';')[0].strip()
            accuracy_color = ' '.join([c for c in acc_round.get('class', []) if c.startswith('color-')])

        if acc_text:
            accuracy_text = acc_text.get_text(strip=True).replace('%', '')
            try:
                accuracy_percent = float(accuracy_text)
            except ValueError:
                pass

        return {
            "accuracy": accuracy_percent,
            "accuracy_percentage": f"{accuracy_percent}%" if accuracy_percent else None,
            "accuracy_width": accuracy_width,
            "accuracy_color": accuracy_color
        }

    def _parse_mods(self, item) -> List[str]:
        """解析Mods - 使用占位符映射"""
        mod_span = item.find('span', class_='mod')
        if not mod_span:
            return []

        mods = []
        mod_icons = mod_span.find_all('i', class_=re.compile('g_mod'))
        for icon in mod_icons:
            mod_class = ' '.join(icon.get('class', []))
            # 使用占位符映射
            mod_name = MOD_MAPPING.get(mod_class, mod_class)
            mods.append(mod_name)

        return mods

    def _parse_time_info(self, item) -> Optional[str]:
        """解析时间信息"""
        time_span = item.find('span', class_='time')
        return time_span.get_text(strip=True) if time_span else None

    def _parse_hit_stats(self, item) -> Dict[str, int]:
        """解析打击统计"""
        title = item.get('title', '')
        if not title or '/' not in title:
            return {"perfect": 0, "good": 0, "miss": 0, "unknown": 0}

        parts = title.split('/')
        return {
            "perfect": int(parts[0]) if parts[0] else 0,
            "good": int(parts[1]) if len(parts) > 1 and parts[1] else 0,
            "miss": int(parts[2]) if len(parts) > 2 and parts[2] else 0,
            "unknown": int(parts[3]) if len(parts) > 3 and parts[3] else 0
        }

    def _extract_uid_from_url(self, url: str) -> Optional[int]:
        """从URL中提取UID"""
        if not url:
            return None
        match = re.search(r'/accounts/user/(\d+)', url)
        return int(match.group(1)) if match else None

@router.get("/chart/{cid}", response_model=APIResponse)
async def parse_chart_page(cid: int):
    """解析谱面页面 - 专注于排行榜数据"""
    try:
        # 检查冷却时间
        current_time = datetime.now()
        if cid in crawler_cooldown:
            last_update = crawler_cooldown[cid]
            if current_time - last_update < timedelta(minutes=5):
                return APIResponse(
                    success=False,
                    error=f"CID {cid} 最近已解析，请5分钟后再试",
                    timestamp=current_time
                )

        service = PageParserService()
        result = await service.parse_chart_page(cid)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        # 更新冷却时间
        crawler_cooldown[cid] = current_time

        return APIResponse(
            success=True,
            data=result,
            message=f"成功解析谱面排行榜，找到 {result.get('total_rankings', 0)} 条记录",
            timestamp=current_time
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

@router.get("/chart/{cid}/ranking")
async def get_chart_ranking_only(cid: int):
    """仅获取谱面排行榜数据（不包含谱面信息）"""
    try:
        service = PageParserService()
        result = await service.parse_chart_page(cid)

        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])

        # 只返回排行榜数据
        ranking_data = {
            "ranking": result.get("ranking", []),
            "total_rankings": result.get("total_rankings", 0),
            "parsed_at": result.get("parsed_at")
        }

        return APIResponse(
            success=True,
            data=ranking_data,
            message=f"成功获取排行榜数据，共 {ranking_data['total_rankings']} 条记录",
            timestamp=datetime.now()
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )

# 保留其他必要的API端点（搜索歌曲、获取歌曲详情等）
@router.get("/song/search", response_model=APIResponse)
async def search_songs(
    query: str = Query(..., description="歌曲名或艺术家名"),
    limit: int = Query(20, description="返回数量", ge=1, le=50)
):
    """搜索歌曲（从数据库）"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        search_query = f"%{query}%"
        cursor.execute("""
            SELECT s.sid, s.title, s.artist,
                   COUNT(DISTINCT c.cid) as chart_count,
                   COUNT(DISTINCT CASE WHEN c.status = 2 THEN c.cid END) as stable_count,
                   GROUP_CONCAT(DISTINCT c.mode) as modes
            FROM songs s
            LEFT JOIN charts c ON s.sid = c.sid
            WHERE s.title LIKE ? OR s.artist LIKE ?
            GROUP BY s.sid, s.title, s.artist
            ORDER BY stable_count DESC, chart_count DESC
            LIMIT ?
        """, (search_query, search_query, limit))

        results = cursor.fetchall()
        conn.close()

        if not results:
            return APIResponse(
                success=False,
                error=f"未找到匹配的歌曲: {query}",
                timestamp=datetime.now()
            )

        songs = [
            {
                "sid": row[0],
                "title": row[1],
                "artist": row[2],
                "chart_count": row[3],
                "stable_count": row[4],
                "modes": [int(m) for m in row[5].split(',')] if row[5] else []
            } for row in results
        ]

        return APIResponse(
            success=True,
            data=songs,
            message=f"找到 {len(songs)} 个匹配的歌曲",
            timestamp=datetime.now()
        )

    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )


@router.get("/song/{sid}", response_model=APIResponse)
async def get_song_details(
    sid: int,
    include_charts: bool = Query(True, description="是否返回谱面列表")
):
    """获取歌曲详情及其关联谱面统计（数据库）"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT s.sid, s.title, s.artist
            FROM songs s
            WHERE s.sid = ?
            """,
            (sid,)
        )
        song_row = cursor.fetchone()
        if not song_row:
            raise HTTPException(status_code=404, detail=f"未找到 SID={sid} 的歌曲")

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_charts,
                COUNT(CASE WHEN c.status = 2 THEN 1 END) AS stable_count,
                COUNT(CASE WHEN c.status = 1 THEN 1 END) AS beta_count,
                COUNT(CASE WHEN c.status = 0 THEN 1 END) AS alpha_count,
                COUNT(DISTINCT c.mode) AS mode_count,
                AVG(CASE WHEN c.level IS NOT NULL AND c.level != '' THEN CAST(c.level AS REAL) END) AS avg_level,
                MAX(c.heat) AS max_heat,
                MAX(c.last_updated) AS latest_update
            FROM charts c
            WHERE c.sid = ?
            """,
            (sid,)
        )
        stats_row = cursor.fetchone()

        charts = []
        if include_charts:
            cursor.execute(
                """
                SELECT
                    c.cid, c.mode, c.level, c.status, c.version,
                    c.creator_name, c.stabled_by_name, c.heat,
                    c.play_count, c.donate_count, c.last_updated
                FROM charts c
                WHERE c.sid = ?
                ORDER BY c.mode ASC, c.status DESC, c.heat DESC, c.cid ASC
                """,
                (sid,)
            )
            chart_rows = cursor.fetchall()
            charts = [
                {
                    "cid": row[0],
                    "mode": row[1],
                    "level": row[2],
                    "status": row[3],
                    "version": row[4],
                    "creator_name": row[5],
                    "stabled_by_name": row[6],
                    "heat": row[7],
                    "play_count": row[8],
                    "donate_count": row[9],
                    "last_updated": row[10],
                }
                for row in chart_rows
            ]

        data = {
            "song": {
                "sid": song_row[0],
                "title": song_row[1],
                "artist": song_row[2],
            },
            "stats": {
                "total_charts": stats_row[0] or 0,
                "stable_count": stats_row[1] or 0,
                "beta_count": stats_row[2] or 0,
                "alpha_count": stats_row[3] or 0,
                "mode_count": stats_row[4] or 0,
                "avg_level": float(stats_row[5]) if stats_row[5] is not None else None,
                "max_heat": stats_row[6],
                "latest_update": stats_row[7],
            },
            "charts": charts if include_charts else None,
        }

        return APIResponse(
            success=True,
            data=data,
            timestamp=datetime.now()
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(
            success=False,
            error=str(e),
            timestamp=datetime.now()
        )
    finally:
        if conn is not None:
            conn.close()

async def trigger_sid_update(sid: int) -> Dict[str, Any]:
    """触发SID更新"""
    try:
        current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        crawler_script = os.path.join(current_dir, "crawlers", "stb.py")

        if not os.path.exists(crawler_script):
            return {
                "success": False,
                "error": f"爬虫脚本不存在: {crawler_script}"
            }

        cmd = [
            "python", crawler_script,
            "--sid", str(sid),
            "--log-level", "INFO",
            "--skip-test"
        ]

        logger.info("Running crawler command: %s", " ".join(cmd))

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=current_dir
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            process.terminate()
            return {
                "success": False,
                "error": "爬虫执行超时（10分钟）"
            }

        result = {
            "success": process.returncode == 0,
            "stdout": stdout.decode('utf-8', errors='ignore') if stdout else "",
            "stderr": stderr.decode('utf-8', errors='ignore') if stderr else "",
            "returncode": process.returncode
        }

        if result["success"]:
            logger.info("SID %s crawler finished successfully", sid)
        else:
            logger.warning("SID %s crawler failed: %s", sid, result["stderr"][:200])

        return result

    except Exception as e:
        error_msg = f"Failed to execute crawler: {str(e)}"
        logger.exception(error_msg)
        return {
            "success": False,
            "error": error_msg
        }
