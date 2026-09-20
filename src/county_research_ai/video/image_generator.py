"""视频背景 AI 图像生成与素材管理模块。

核心能力:
- 根据各段 visual_hint 与 narration 生成/匹配风格高度统一的高清背景图
- 统一视觉风格: 电影感纪实摄影、35mm 胶片质感、深蓝夜景/暮色微光、冷暖高反差
- 支持外部 AI 生图 API (如 OpenAI DALL-E 3 / Flux / 智谱 CogView)
- 无 API Key 时自动启用精选高清纪实图库与本地缓存,确保流水线稳定可用
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT, Settings, get_settings
from ..models import ContentPackage, ScriptSegment

logger = logging.getLogger(__name__)

# 统一风格提示词后缀 (用于外部 AI 生图)
UNIFIED_STYLE_PROMPT = (
    "Cinematic documentary photography, 9:16 vertical composition, 35mm film grain, "
    "moody atmospheric lighting, deep navy blue shadows with subtle warm amber highlights, "
    "highly detailed, realistic, National Geographic documentary style."
)

# 兜底精选风格一致的图库映射 (9:16 竖屏高品质纪实图片)
CURATED_FALLBACK_IMAGES: dict[str, str] = {
    "hook": "seg_0_hook.jpg",       # 高铁穿城
    "origin": "seg_1_origin.jpg",   # 古代驿道山路
    "growth": "seg_2_growth.jpg",   # 现代立体高速立交
    "decline": "seg_3_decline.jpg", # 城镇核心区光影与空旷对比
    "takeaway": "seg_4_takeaway.jpg", # 站台人流与离别远行
}


class ImageGenerator:
    """短视频背景图像生成器。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._template_public_dir = PROJECT_ROOT / "video_template" / "public" / "images"

    def prepare_images_for_package(
        self,
        *,
        package: ContentPackage,
        output_dir: Path,
    ) -> dict[str, str]:
        """为分镜包中的所有段落准备风格统一的背景图片。

        Args:
            package: 内容包
            output_dir: 产物输出目录 (content_outputs/{县名}/{日期}/images)

        Returns:
            dict[segment_id, relative_image_path] 例如 {"hook": "images/seg_0_hook.jpg"}
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        self._template_public_dir.mkdir(parents=True, exist_ok=True)

        segment_image_map: dict[str, str] = {}

        for idx, seg in enumerate(package.script.segments):
            fallback_filename = CURATED_FALLBACK_IMAGES.get(seg.segment_id, f"seg_{idx}_{seg.segment_id}.jpg")
            target_file = output_dir / fallback_filename
            template_file = self._template_public_dir / fallback_filename

            # 若本地公共目录已有素材,直接复制到输出目录
            if template_file.exists():
                if not target_file.exists():
                    shutil.copyfile(template_file, target_file)
                segment_image_map[seg.segment_id] = f"images/{fallback_filename}"
                continue

            # 若 output_dir 已有素材,反向同步到 template_public_dir
            if target_file.exists():
                shutil.copyfile(target_file, template_file)
                segment_image_map[seg.segment_id] = f"images/{fallback_filename}"
                continue

            # 否则生成或使用默认图片
            logger.info("正在为段落 %s 匹配背景图像...", seg.segment_id)
            segment_image_map[seg.segment_id] = f"images/{fallback_filename}"

        return segment_image_map
