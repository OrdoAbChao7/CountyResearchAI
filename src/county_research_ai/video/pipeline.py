"""视频生产流水线总编排器。

串联全流程:
    ContentPackage (脚本与分镜)
        ↓
    TTSGenerator (Edge-TTS 旁白生成 + 字幕时间戳对齐)
        ↓
    RemotionRenderer (无头 Chromium 渲染 1080P MP4 视频)
        ↓ (异常时自动回退)
    DraftGenerator (剪映草稿工程输出)

落盘位置:
    content_outputs/{县名}/{日期}/
        ├── audio/
        │   ├── narration.mp3
        │   ├── subtitles.json
        │   └── subtitles.srt
        ├── video/
        │   ├── video.mp4
        │   └── remotion_props.json
        └── (可选) jianying_draft/
            ├── draft_content.json
            └── draft_meta_info.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT, Settings, get_settings
from ..content.pipeline import ContentPipeline
from ..models import ContentPackage
from .draft_generator import DraftGenerator
from .image_generator import ImageGenerator
from .models import AudioTrackPackage, VideoRenderResult
from .remotion import RemotionRenderer
from .tts import TTSGenerator

logger = logging.getLogger(__name__)


class VideoPipeline:
    """端到端视频生产流水线。

    Usage:
        pipeline = VideoPipeline()
        result = pipeline.produce_from_package(
            package_path="content_outputs/信丰县/20260806/package.json"
        )
    """

    def __init__(
        self,
        tts_generator: TTSGenerator | None = None,
        image_generator: ImageGenerator | None = None,
        remotion_renderer: RemotionRenderer | None = None,
        draft_generator: DraftGenerator | None = None,
        content_pipeline: ContentPipeline | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._tts_generator = tts_generator or TTSGenerator()
        self._image_generator = image_generator or ImageGenerator(settings=self._settings)
        self._draft_generator = draft_generator or DraftGenerator()
        self._remotion_renderer = remotion_renderer or RemotionRenderer(
            draft_generator=self._draft_generator
        )
        self._content_pipeline = content_pipeline
        self._output_root = PROJECT_ROOT / "content_outputs"

    @property
    def content_pipeline(self) -> ContentPipeline:
        """延迟加载 ContentPipeline (避免未提供 API Key 时初始化报错)。"""
        if self._content_pipeline is None:
            self._content_pipeline = ContentPipeline(settings=self._settings)
        return self._content_pipeline

    def produce_from_package(self, *, package_path: str | Path) -> VideoRenderResult:
        """从现有的 package.json 执行视频生产。"""
        p = Path(package_path)
        if not p.exists():
            raise FileNotFoundError(f"找不到指定的内容包文件: {package_path}")

        data = json.loads(p.read_text(encoding="utf-8"))
        package = ContentPackage.model_validate(data)
        out_dir = p.parent
        return self._run_pipeline(package=package, out_dir=out_dir)

    def produce_from_report(self, *, county: str, report_path: str | Path) -> VideoRenderResult:
        """从研究报告出发,先生成分镜内容包,再执行视频生产。"""
        package = self.content_pipeline.produce(county=county, report_path=str(report_path))
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        county_safe = ContentPipeline._safe_name(county)
        out_dir = self._output_root / county_safe / date_str
        return self._run_pipeline(package=package, out_dir=out_dir)

    def _run_pipeline(self, *, package: ContentPackage, out_dir: Path) -> VideoRenderResult:
        """执行具体的音视频合成。"""
        logger.info("视频流水线启动 | 县=%s | 标题=%s", package.county, package.script.title)

        # 1. 语音合成与字幕对齐 (audio/)
        audio_dir = out_dir / "audio"
        audio_package = self._tts_generator.generate(
            county=package.county,
            script=package.script,
            output_dir=audio_dir,
        )

        # 2. 图像素材准备 (images/)
        images_dir = out_dir / "images"
        image_map = self._image_generator.prepare_images_for_package(
            package=package,
            output_dir=images_dir,
        )

        # 3. 视频无头渲染 (video/)
        video_dir = out_dir / "video"
        render_result = self._remotion_renderer.render(
            package=package,
            audio_package=audio_package,
            output_dir=video_dir,
            image_map=image_map,
        )

        # 3. 记录视频生产元数据清单 (video_manifest.json)
        manifest = {
            "county": package.county,
            "title": package.script.title,
            "produced_at": datetime.now(timezone.utc).isoformat(),
            "status": render_result.status,
            "video_path": render_result.video_path,
            "draft_path": render_result.draft_path,
            "duration_seconds": render_result.duration_seconds,
            "resolution": render_result.resolution,
            "fps": render_result.fps,
            "fallback_used": audio_package.fallback_used or render_result.status != "success",
            "error_message": render_result.error_message,
        }
        (out_dir / "video_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "视频流水线完成 | 状态=%s | 输出=%s",
            render_result.status,
            render_result.video_path or render_result.draft_path,
        )
        return render_result
