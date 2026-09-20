"""TTS 语音合成与字幕对齐单元测试。"""
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from county_research_ai.models import ScriptSegment, VideoScript
from county_research_ai.video.models import AudioTrackPackage, SubtitleItem
from county_research_ai.video.tts import TTSGenerator


@pytest.fixture
def sample_script() -> VideoScript:
    """提供测试用 5 段式短视频脚本。"""
    segments = [
        ScriptSegment(
            segment_id="hook",
            time_range="0-5s",
            narration="赣深高铁穿境而过，信丰的年轻人却依然在流向广东。",
            on_screen="信丰 · 交通悖论",
            visual_hint="高铁飞驰与冷清街道",
        ),
        ScriptSegment(
            segment_id="origin",
            time_range="5-20s",
            narration="信丰自古因赣粤驿道而兴，是南北商贸的必经之地。",
            on_screen="赣粤驿道",
            visual_hint="古代驿道地图",
        ),
        ScriptSegment(
            segment_id="growth",
            time_range="20-40s",
            narration="新世纪以来高速高铁完善，但户籍与常住人口差额达5到8万人。",
            on_screen="人口差额 5-8 万",
            visual_hint="人口外流趋势图",
        ),
        ScriptSegment(
            segment_id="decline",
            time_range="40-55s",
            narration="县城单极集中，嘉定镇占全县人口37%以上，乡镇空心化明显。",
            on_screen="单极集中 37%+",
            visual_hint="乡镇空心化对比",
        ),
        ScriptSegment(
            segment_id="takeaway",
            time_range="55-60s",
            narration="区位优势若没有产业承接就只是过路经济，交通是通道不是终点。",
            on_screen="过路经济 vs 落地经济",
            visual_hint="站台人流匆匆",
        ),
    ]
    return VideoScript(
        angle_id="test-angle",
        title="信丰的交通悖论",
        duration_seconds=60,
        segments=segments,
        total_word_count=180,
    )


class TestTTSGenerator:
    """TTS 生成器测试。"""

    def test_render_srt(self) -> None:
        """测试 SRT 格式生成正确性。"""
        subs = [
            SubtitleItem(
                index=1,
                segment_id="hook",
                text="第一句测试",
                start_ms=100,
                end_ms=2500,
            ),
            SubtitleItem(
                index=2,
                segment_id="hook",
                text="第二句测试",
                start_ms=2600,
                end_ms=5000,
            ),
        ]
        srt = TTSGenerator._render_srt(subs)
        assert "1\n00:00:00,100 --> 00:00:02,500\n第一句测试" in srt
        assert "2\n00:00:02,600 --> 00:00:05,000\n第二句测试" in srt

    def test_fallback_audio_generation(self, tmp_path: Path) -> None:
        """测试 TTS 失败时的静音降级机制。"""
        generator = TTSGenerator()
        seg = ScriptSegment(
            segment_id="hook",
            time_range="0-5s",
            narration="这是一段测试降级生成的文本内容。",
        )
        target = tmp_path / "fallback.wav"
        data, duration_ms = generator._generate_fallback_audio(segment=seg, target_file=target)

        assert target.exists()
        assert len(data) > 0
        assert duration_ms > 1000

    def test_generate_with_mocked_tts(self, tmp_path: Path, sample_script: VideoScript) -> None:
        """在 Mock 环境下测试完整音频流水线。"""
        generator = TTSGenerator()

        async def fake_synthesize(*args, **kwargs):
            target = kwargs["target_file"]
            target.write_bytes(b"mock_audio_data")
            sub = SubtitleItem(
                index=1,
                segment_id=kwargs["segment"].segment_id,
                text=kwargs["segment"].narration,
                start_ms=0,
                end_ms=3000,
            )
            return b"mock_audio_data", 3000, [sub]

        with patch.object(generator, "_synthesize_segment", side_effect=fake_synthesize):
            pkg = generator.generate(
                county="信丰县",
                script=sample_script,
                output_dir=tmp_path / "audio",
            )

            assert isinstance(pkg, AudioTrackPackage)
            assert pkg.county == "信丰县"
            assert len(pkg.segments) == 5
            assert pkg.total_duration_ms == 15000  # 5 * 3000ms
            assert (tmp_path / "audio" / "narration.mp3").exists()
            assert (tmp_path / "audio" / "subtitles.json").exists()
            assert (tmp_path / "audio" / "subtitles.srt").exists()
            assert len(pkg.subtitles) == 5
