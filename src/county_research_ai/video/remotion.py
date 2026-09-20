"""Remotion 视频无头渲染器。

核心能力:
- 将 Python 侧生成的音视频元数据 (package.json + audio + subtitles) 组装为 Remotion props
- 调度 Remotion CLI (`npx remotion render`) 在无头 Chromium 环境下渲染高品质 MP4 视频
- 监控渲染进程、超时控制与异常捕获
- 失败时自动启动多级回退: 生成剪映草稿工程 (draft/)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ..config import PROJECT_ROOT
from ..models import ContentPackage
from .draft_generator import DraftGenerator
from .models import AudioTrackPackage, VideoRenderResult

logger = logging.getLogger(__name__)


class RemotionRenderer:
    """Remotion 视频渲染器。"""

    def __init__(
        self,
        template_dir: Path | None = None,
        timeout_seconds: int = 240,
        draft_generator: DraftGenerator | None = None,
    ) -> None:
        self._template_dir = template_dir or (PROJECT_ROOT / "video_template")
        self._timeout_seconds = timeout_seconds
        self._draft_generator = draft_generator or DraftGenerator()

    def render(
        self,
        *,
        package: ContentPackage,
        audio_package: AudioTrackPackage,
        output_dir: Path,
        image_map: dict[str, str] | None = None,
    ) -> VideoRenderResult:
        """执行端到端视频渲染。

        Args:
            package: 内容包 (包含 5 段分镜与标题)
            audio_package: 音频包 (包含分段时长与字幕)
            output_dir: 视频产物落盘目录
            image_map: 分段背景图片映射字典

        Returns:
            VideoRenderResult
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        video_filename = "video.mp4"
        final_video_path = output_dir / video_filename

        # 1. 准备公共静态素材目录 (video_template/public)
        public_dir = self._template_dir / "public"
        public_dir.mkdir(parents=True, exist_ok=True)
        audio_public_dir = public_dir / "audio"
        audio_public_dir.mkdir(parents=True, exist_ok=True)

        # 确保基础音效与环境 BGM 存在
        from .audio_effects import generate_ambient_cinematic_bgm, generate_sfx_impact
        bgm_file = audio_public_dir / "bgm_ambient.wav"
        if not bgm_file.exists():
            generate_ambient_cinematic_bgm(bgm_file, duration_sec=60.0)
        sfx_file = audio_public_dir / "sfx_impact.wav"
        if not sfx_file.exists():
            generate_sfx_impact(sfx_file)

        audio_src_path = Path(audio_package.full_audio_path)
        rel_audio_name = f"narration_{uuid.uuid4().hex[:8]}.mp3"
        dest_audio_path = public_dir / rel_audio_name
        if audio_src_path.exists():
            shutil.copyfile(audio_src_path, dest_audio_path)

        # 2. 构造 Remotion Props
        # 将各段的时长与时间轴偏移与 package.script 结合
        segments_props: list[dict[str, Any]] = []
        for idx, seg in enumerate(package.script.segments):
            # 找到对应的 audio segment
            matching_audio = next(
                (a for a in audio_package.segments if a.segment_id == seg.segment_id),
                None,
            )
            dur_ms = matching_audio.duration_ms if matching_audio else 5000
            start_off = matching_audio.start_offset_ms if matching_audio else 0
            end_off = matching_audio.end_offset_ms if matching_audio else dur_ms
            img_url = image_map.get(seg.segment_id, "") if image_map else ""

            segments_props.append({
                "segment_id": seg.segment_id,
                "time_range": seg.time_range,
                "narration": seg.narration,
                "on_screen": seg.on_screen,
                "visual_hint": seg.visual_hint,
                "source_refs": seg.source_refs,
                "duration_ms": dur_ms,
                "start_offset_ms": start_off,
                "end_offset_ms": end_off,
                "image_url": img_url,
            })

        remotion_props = {
            "county": package.county,
            "title": package.script.title,
            "hook": package.angle.hook,
            "perspective": package.angle.perspective,
            "total_duration_ms": audio_package.total_duration_ms,
            "audio_url": rel_audio_name,
            "bgm_url": "audio/bgm_ambient.wav",
            "sfx_url": "audio/sfx_impact.wav",
            "segments": segments_props,
            "subtitles": [s.model_dump() for s in audio_package.subtitles],
        }

        # 保存 props.json
        props_path = output_dir / "remotion_props.json"
        props_path.write_text(
            json.dumps(remotion_props, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 3. 调用 Remotion CLI 渲染
        cmd = [
            "npx",
            "remotion",
            "render",
            "src/index.ts",
            "CountyVideo",
            str(final_video_path.resolve()),
            f"--props={str(props_path.resolve())}",
        ]

        logger.info("启动 Remotion 渲染: %s", " ".join(cmd))
        try:
            res = subprocess.run(
                cmd,
                cwd=str(self._template_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
                shell=True,
            )

            # 清理临时复制的音频
            if dest_audio_path.exists():
                dest_audio_path.unlink()

            if res.returncode == 0 and final_video_path.exists():
                logger.info("Remotion 视频渲染成功: %s", final_video_path)
                return VideoRenderResult(
                    county=package.county,
                    video_path=str(final_video_path),
                    duration_seconds=audio_package.total_duration_ms / 1000.0,
                    resolution="1080x1920",
                    fps=30,
                    status="success",
                )
            else:
                err_msg = f"Remotion 渲染进程退出码异常 ({res.returncode}): {res.stderr or res.stdout}"
                logger.error(err_msg)
                return self._trigger_draft_fallback(
                    package=package,
                    audio_package=audio_package,
                    output_dir=output_dir,
                    error_message=err_msg,
                )

        except subprocess.TimeoutExpired:
            err_msg = f"Remotion 渲染超时 (超过 {self._timeout_seconds} 秒)"
            logger.error(err_msg)
            return self._trigger_draft_fallback(
                package=package,
                audio_package=audio_package,
                output_dir=output_dir,
                error_message=err_msg,
            )
        except Exception as e:
            err_msg = f"Remotion 渲染遇到未预期异常: {e}"
            logger.error(err_msg, exc_info=True)
            return self._trigger_draft_fallback(
                package=package,
                audio_package=audio_package,
                output_dir=output_dir,
                error_message=err_msg,
            )

    def _trigger_draft_fallback(
        self,
        *,
        package: ContentPackage,
        audio_package: AudioTrackPackage,
        output_dir: Path,
        error_message: str,
    ) -> VideoRenderResult:
        """触发降级回退: 自动生成剪映草稿工程。"""
        logger.warning("触发视频渲染自动回退: 正在生成剪映草稿工程...")
        draft_dir = output_dir / "jianying_draft"
        try:
            self._draft_generator.generate_draft(
                county=package.county,
                title=package.script.title,
                audio_package=audio_package,
                output_dir=draft_dir,
            )
            return VideoRenderResult(
                county=package.county,
                video_path="",
                duration_seconds=audio_package.total_duration_ms / 1000.0,
                status="fallback_draft",
                draft_path=str(draft_dir),
                error_message=error_message,
            )
        except Exception as e:
            logger.error("生成剪映草稿失败: %s", e, exc_info=True)
            return VideoRenderResult(
                county=package.county,
                video_path="",
                duration_seconds=audio_package.total_duration_ms / 1000.0,
                status="failed",
                error_message=f"{error_message}; 剪映草稿兜底亦失败: {e}",
            )
