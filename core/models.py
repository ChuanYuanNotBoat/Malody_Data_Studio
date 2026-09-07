# malody_api/core/models.py
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class GameMode(int, Enum):
    ALL = -1
    KEY = 0
    STEP = 1
    DJ = 2
    CATCH = 3
    PAD = 4
    TAIKO = 5
    RING = 6
    SLIDE = 7
    LIVE = 8
    CUBE = 9

class ChartStatus(int, Enum):
    ALPHA = 0
    BETA = 1
    STABLE = 2

class Player(BaseModel):
    rank: int = Field(..., description="排名")
    name: str = Field(..., description="玩家名")
    level: Optional[int] = Field(None, description="等级")
    exp: Optional[int] = Field(None, description="经验值")
    mm_value: Optional[int] = Field(None, description="MM分值")
    accuracy: Optional[float] = Field(None, description="准确率")
    combo: Optional[int] = Field(None, description="最大连击")
    play_count: Optional[int] = Field(None, description="游玩次数")
    mode: Optional[int] = Field(None, description="游戏模式")
    rank_type: Optional[str] = Field(None, description="排行榜类型(exp/mm)")

class PlayerDetail(BaseModel):
    rank: int = Field(..., description="排名")
    level: int = Field(..., description="等级")
    exp: int = Field(..., description="经验值")
    accuracy: float = Field(..., description="准确率")
    combo: int = Field(..., description="最大连击")
    play_count: int = Field(..., description="游玩次数")
    mode: int = Field(..., description="游戏模式")
    last_updated: datetime = Field(..., description="最后更新")
    aliases: Optional[List[str]] = Field(None, description="曾用名")

class PlayerHistoryPoint(BaseModel):
    date: datetime = Field(..., description="日期")
    rank: int = Field(..., description="排名")

class ChartStats(BaseModel):
    total_charts: int = Field(..., description="总谱面数（含已删除）")
    total_charts_excluding_deleted: int = Field(0, description="排除已删除后的总谱面数")
    deleted_charts: int = Field(0, description="已删除谱面数")
    unique_songs: int = Field(..., description="唯一歌曲数")
    unique_creators: int = Field(..., description="创作者数")
    status_distribution: Dict[str, int] = Field(..., description="状态分布")
    level_distribution: Dict[str, int] = Field(..., description="难度分布")
    heat_stats: Dict[str, float] = Field(..., description="热度统计")
    unique_songs_excluding_deleted: int = Field(0, description="排除已删除后的唯一歌曲数")
    unique_creators_excluding_deleted: int = Field(0, description="排除已删除后的创作者数")

class HotChart(BaseModel):
    cid: int = Field(..., description="谱面ID")
    title: str = Field(..., description="歌曲标题")
    artist: str = Field(..., description="艺术家")
    version: str = Field(..., description="谱面版本")
    level: str = Field(..., description="难度等级")
    status: int = Field(..., description="状态")
    creator_name: str = Field(..., description="创作者")
    heat: int = Field(..., description="热度")
    donate_count: int = Field(..., description="打赏数")
    deleted: bool = Field(False, description="是否已从服务器删除")

class CreatorStats(BaseModel):
    creator_name: str = Field(..., description="创作者名")
    stable_count: int = Field(..., description="Stable谱面数")
    avg_level: Optional[float] = Field(None, description="平均难度")
    avg_heat: Optional[float] = Field(None, description="平均热度")
    max_heat: Optional[int] = Field(None, description="最高热度")

class APIResponse(BaseModel):
    success: bool = Field(..., description="请求是否成功")
    data: Optional[Any] = Field(None, description="响应数据")
    message: Optional[str] = Field(None, description="消息")
    error: Optional[str] = Field(None, description="错误信息")
    timestamp: datetime = Field(..., description="时间戳")

class SelectorConfig(BaseModel):
    players: Optional[List[str]] = Field(None, description="玩家/创作者筛选")
    modes: Optional[List[int]] = Field(None, description="模式筛选")
    difficulties: Optional[str] = Field(None, description="难度范围，如 '5-10'")
    time_range: Optional[str] = Field(None, description="时间范围，如 '7d', '30d'")
    statuses: Optional[List[int]] = Field(None, description="状态筛选")
