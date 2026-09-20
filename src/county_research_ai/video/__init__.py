"""视频生成与自动化剪辑模块。

模块架构:
- models: 音频、字幕与渲染结果模型
- tts: 基于 Edge-TTS 的语音合成与时间戳对齐
- remotion: Remotion 模板桥接与无头渲染编排
- draft_generator: 剪映/CapCut 草稿工程生成器 (作为降级或人机协同输出)
- pipeline: 视频生产流水线总入口
"""
from .draft_generator import DraftGenerator
from .models import AudioSegment, AudioTrackPackage, SubtitleItem, VideoRenderResult
from .pipeline import VideoPipeline
from .remotion import RemotionRenderer
from .tts import TTSGenerator

__all__ = [
    "AudioSegment",
    "AudioTrackPackage",
    "SubtitleItem",
    "VideoRenderResult",
    "TTSGenerator",
    "RemotionRenderer",
    "DraftGenerator",
    "VideoPipeline",
]
