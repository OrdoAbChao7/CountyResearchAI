"""剪映 / CapCut 草稿工程生成器 (作为降级或人机协同输出)。

能力:
- 生成标准 1080x1920 9:16 剪映草稿工程 (draft_content.json + draft_meta_info.json)
- 包含旁白音频轨、字幕文本轨与分段画面提示
- 用户可直接在剪映中打开,进行二次微调、套用滤镜和花字
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from .models import AudioTrackPackage

logger = logging.getLogger(__name__)


class DraftGenerator:
    """剪映草稿工程生成器。"""

    def generate_draft(
        self,
        *,
        county: str,
        title: str,
        audio_package: AudioTrackPackage,
        output_dir: Path,
    ) -> Path:
        """生成剪映草稿工程文件并落盘。

        Args:
            county: 县名
            title: 视频标题
            audio_package: 音频与字幕产物包
            output_dir: 草稿输出目录

        Returns:
            draft_dir: 生成的草稿目录路径
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        draft_id = str(uuid.uuid4()).upper()

        total_duration_us = audio_package.total_duration_ms * 1000  # 微秒

        # 1. 构造 materials (音频与文本素材)
        audios = [
            {
                "id": str(uuid.uuid4()).upper(),
                "name": "narration.mp3",
                "path": str(Path(audio_package.full_audio_path).resolve()),
                "duration": total_duration_us,
                "type": "extract_music",
            }
        ]

        texts: list[dict[str, Any]] = []
        text_segments: list[dict[str, Any]] = []

        for sub in audio_package.subtitles:
            text_id = str(uuid.uuid4()).upper()
            start_us = sub.start_ms * 1000
            duration_us = (sub.end_ms - sub.start_ms) * 1000

            texts.append({
                "id": text_id,
                "content": sub.text,
                "font_size": 18.0,
                "text_color": "#FFFFFF",
                "type": "subtitle",
            })

            text_segments.append({
                "id": str(uuid.uuid4()).upper(),
                "material_id": text_id,
                "target_timerange": {
                    "duration": duration_us,
                    "start": start_us,
                },
            })

        # 2. 构造 tracks
        tracks = [
            {
                "id": str(uuid.uuid4()).upper(),
                "type": "audio",
                "segments": [
                    {
                        "id": str(uuid.uuid4()).upper(),
                        "material_id": audios[0]["id"],
                        "target_timerange": {
                            "duration": total_duration_us,
                            "start": 0,
                        },
                    }
                ],
            },
            {
                "id": str(uuid.uuid4()).upper(),
                "type": "text",
                "segments": text_segments,
            },
        ]

        # 3. draft_content.json
        draft_content = {
            "id": draft_id,
            "duration": total_duration_us,
            "fps": 30.0,
            "materials": {
                "audios": audios,
                "texts": texts,
                "videos": [],
            },
            "tracks": tracks,
        }

        # 4. draft_meta_info.json
        draft_meta = {
            "draft_id": draft_id,
            "draft_name": f"{county}_{title}",
            "draft_timeline_materials_size_": 0,
            "tm_draft_create": int(uuid.uuid1().time / 10),
            "tm_draft_modified": int(uuid.uuid1().time / 10),
            "draft_canvas_config": {
                "width": 1080,
                "height": 1920,
                "ratio": "9:16",
            },
        }

        content_path = output_dir / "draft_content.json"
        meta_path = output_dir / "draft_meta_info.json"

        content_path.write_text(json.dumps(draft_content, ensure_ascii=False, indent=2), encoding="utf-8")
        meta_path.write_text(json.dumps(draft_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("剪映草稿工程生成完成: %s", output_dir)
        return output_dir
