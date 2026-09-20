"""视频生产流水线与草稿生成器单元测试。"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from county_research_ai.models import ContentAngle, ContentPackage, FactCheckItem, FactCheckResult, ScriptSegment, VideoScript
from county_research_ai.video.draft_generator import DraftGenerator
from county_research_ai.video.models import AudioSegment, AudioTrackPackage, SubtitleItem, VideoRenderResult
from county_research_ai.video.pipeline import VideoPipeline
from county_research_ai.video.remotion import RemotionRenderer


@pytest.fixture
def sample_package() -> ContentPackage:
    """提供测试用 ContentPackage。"""
    segments = [
        ScriptSegment(
            segment_id="hook",
            time_range="0-5s",
            narration="测试旁白内容第一句",
            on_screen="测试屏幕词",
            visual_hint="测试画面建议",
        ),
        ScriptSegment(
            segment_id="takeaway",
            time_range="55-60s",
            narration="测试旁白内容结尾",
            on_screen="总结",
            visual_hint="结束画面",
        ),
    ]
    script = VideoScript(
        angle_id="angle-1",
        title="测试视频标题",
        duration_seconds=60,
        segments=segments,
        total_word_count=40,
    )
    angle = ContentAngle(
        angle_id="angle-1",
        title="测试视频标题",
        hook="测试钩子",
        perspective="测试视角",
        target_audience="测试受众",
        key_points=["要点1"],
        tone="冷静",
        source_refs=["来源1"],
    )
    fact_check = FactCheckResult(
        overall_status="ok",
        items=[FactCheckItem(segment_id="hook", claim="测试声明", verdict="supported")],
    )
    return ContentPackage(
        county="测试县",
        report_path="reports/test.md",
        angle=angle,
        script=script,
        fact_check=fact_check,
    )


@pytest.fixture
def sample_audio_package(tmp_path: Path) -> AudioTrackPackage:
    """提供测试用 AudioTrackPackage。"""
    audio_file = tmp_path / "narration.mp3"
    audio_file.write_bytes(b"mock_mp3_data")

    return AudioTrackPackage(
        county="测试县",
        voice="zh-CN-YunxiNeural",
        total_duration_ms=6000,
        full_audio_path=str(audio_file),
        segments=[
            AudioSegment(
                segment_id="hook",
                narration="测试旁白内容第一句",
                audio_path="segments/seg_0_hook.mp3",
                duration_ms=3000,
                start_offset_ms=0,
                end_offset_ms=3000,
            ),
            AudioSegment(
                segment_id="takeaway",
                narration="测试旁白内容结尾",
                audio_path="segments/seg_1_takeaway.mp3",
                duration_ms=3000,
                start_offset_ms=3000,
                end_offset_ms=6000,
            ),
        ],
        subtitles=[
            SubtitleItem(
                index=1,
                segment_id="hook",
                text="测试旁白内容第一句",
                start_ms=0,
                end_ms=3000,
            ),
            SubtitleItem(
                index=2,
                segment_id="takeaway",
                text="测试旁白内容结尾",
                start_ms=3000,
                end_ms=6000,
            ),
        ],
    )


class TestDraftGenerator:
    """剪映草稿工程生成测试。"""

    def test_generate_draft(self, tmp_path: Path, sample_audio_package: AudioTrackPackage) -> None:
        generator = DraftGenerator()
        draft_dir = tmp_path / "draft"

        out = generator.generate_draft(
            county="测试县",
            title="测试标题",
            audio_package=sample_audio_package,
            output_dir=draft_dir,
        )

        assert out.exists()
        assert (draft_dir / "draft_content.json").exists()
        assert (draft_dir / "draft_meta_info.json").exists()


class TestRemotionRenderer:
    """Remotion 渲染器与降级测试。"""

    def test_render_success(
        self,
        tmp_path: Path,
        sample_package: ContentPackage,
        sample_audio_package: AudioTrackPackage,
    ) -> None:
        renderer = RemotionRenderer(template_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

            # 模拟生成出的目标文件
            out_video = tmp_path / "video" / "video.mp4"
            out_video.parent.mkdir(parents=True, exist_ok=True)
            out_video.write_bytes(b"mock_mp4_bytes")

            res = renderer.render(
                package=sample_package,
                audio_package=sample_audio_package,
                output_dir=tmp_path / "video",
            )

            assert res.status == "success"
            assert res.video_path == str(out_video)

    def test_render_failure_triggers_draft_fallback(
        self,
        tmp_path: Path,
        sample_package: ContentPackage,
        sample_audio_package: AudioTrackPackage,
    ) -> None:
        renderer = RemotionRenderer(template_dir=tmp_path)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Node error")

            res = renderer.render(
                package=sample_package,
                audio_package=sample_audio_package,
                output_dir=tmp_path / "video",
            )

            assert res.status == "fallback_draft"
            assert res.draft_path is not None
            assert Path(res.draft_path).exists()


class TestVideoPipeline:
    """端到端流水线集成测试。"""

    def test_produce_from_package(
        self,
        tmp_path: Path,
        sample_package: ContentPackage,
        sample_audio_package: AudioTrackPackage,
    ) -> None:
        pkg_file = tmp_path / "package.json"
        pkg_file.write_text(sample_package.model_dump_json(indent=2), encoding="utf-8")

        pipeline = VideoPipeline()
        with patch.object(pipeline._tts_generator, "generate", return_value=sample_audio_package):
            with patch.object(
                pipeline._remotion_renderer,
                "render",
                return_value=VideoRenderResult(
                    county=sample_package.county,
                    video_path=str(tmp_path / "video" / "video.mp4"),
                    duration_seconds=6.0,
                    status="success",
                ),
            ):
                res = pipeline.produce_from_package(package_path=pkg_file)
                assert res.status == "success"
                assert (tmp_path / "video_manifest.json").exists()
