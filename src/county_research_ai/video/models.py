"""视频生成模块数据模型。"""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field


class SubtitleItem(BaseModel):
    """字幕条目。"""
    index: int = Field(description="字幕序号(从 1 开始)")
    segment_id: str = Field(description="所属段落 ID,如 hook, origin")
    text: str = Field(description="字幕文本")
    start_ms: int = Field(description="起始时间(毫秒)")
    end_ms: int = Field(description="结束时间(毫秒)")


class AudioSegment(BaseModel):
    """单段音频生成结果。"""
    segment_id: str = Field(description="段位 ID")
    narration: str = Field(description="旁白文本")
    audio_path: str = Field(description="音频文件相对/绝对路径")
    duration_ms: int = Field(description="音频时长(毫秒)")
    start_offset_ms: int = Field(default=0, description="在整片时间轴上的起始毫秒")
    end_offset_ms: int = Field(default=0, description="在整片时间轴上的结束毫秒")


class AudioTrackPackage(BaseModel):
    """音频生产产物包。"""
    county: str = Field(description="县名")
    voice: str = Field(description="使用的音色名称")
    total_duration_ms: int = Field(description="整片音频总时长(毫秒)")
    full_audio_path: str = Field(description="整片合并音频路径")
    segments: list[AudioSegment] = Field(default_factory=list, description="分段音频列表")
    subtitles: list[SubtitleItem] = Field(default_factory=list, description="字幕时间戳列表")
    fallback_used: bool = Field(default=False, description="是否触发了降级生成")
    fallback_reason: str = Field(default="", description="降级原因")


class VideoRenderResult(BaseModel):
    """视频渲染产物。"""
    county: str
    video_path: str = Field(description="生成的 MP4 视频路径")
    duration_seconds: float = Field(description="视频总时长(秒)")
    resolution: str = Field(default="1080x1920", description="分辨率")
    fps: int = Field(default=30, description="帧率")
    status: str = Field(default="success", description="渲染状态: success / fallback_draft / failed")
    draft_path: str | None = Field(default=None, description="回退时的剪映草稿路径")
    error_message: str | None = Field(default=None, description="错误信息")
