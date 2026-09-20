"""TTS 语音合成与字幕对齐模块。

核心能力:
- 基于 edge-tts 生成高拟真中文科普旁白音频
- 提取字词/句子级时间戳,生成对齐字幕 (JSON + SRT)
- 支持多级重试与自动回退降级 (离线占位/静音轨)
- 支持根据短视频目标时长自适应调节语速 (rate)
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import wave
from datetime import timedelta
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import ContentPackage, ScriptSegment, VideoScript
from .models import AudioSegment, AudioTrackPackage, SubtitleItem

logger = logging.getLogger(__name__)

# 默认配音员: 沉稳大气的科普/纪录片男声
DEFAULT_VOICE = "zh-CN-YunxiNeural"
# 中文正常语速: 每秒约 4.0 - 4.5 字
DEFAULT_CHARS_PER_SECOND = 4.2


class TTSGenerator:
    """短视频语音合成与字幕对齐生成器。

    Usage:
        generator = TTSGenerator()
        package = generator.generate(
            county="信丰县",
            script=video_script,
            output_dir=Path("content_outputs/信丰县/20260806/audio"),
        )
    """

    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        rate: str = "+0%",
        volume: str = "+0%",
        fail_fast: bool = False,
    ) -> None:
        self._voice = voice
        self._rate = rate
        self._volume = volume
        self._fail_fast = fail_fast

    @property
    def proxy(self) -> str | None:
        """从环境变量中提取可用代理。"""
        return (
            os.environ.get("ALL_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
        )

    def generate(
        self,
        *,
        county: str,
        script: VideoScript,
        output_dir: Path,
    ) -> AudioTrackPackage:
        """同步入口:为脚本中所有段位生成音频和字幕。"""
        return asyncio.run(
            self.generate_async(county=county, script=script, output_dir=output_dir)
        )

    async def generate_async(
        self,
        *,
        county: str,
        script: VideoScript,
        output_dir: Path,
    ) -> AudioTrackPackage:
        """异步执行语音合成。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        seg_audio_dir = output_dir / "segments"
        seg_audio_dir.mkdir(parents=True, exist_ok=True)

        audio_segments: list[AudioSegment] = []
        all_subtitles: list[SubtitleItem] = []
        current_offset_ms = 0
        fallback_occurred = False
        fallback_reasons: list[str] = []

        sub_index = 1
        full_audio_bytes = bytearray()

        for idx, seg in enumerate(script.segments):
            seg_filename = f"seg_{idx}_{seg.segment_id}.mp3"
            seg_file_path = seg_audio_dir / seg_filename

            # 合成单段
            audio_data, duration_ms, seg_subs = await self._synthesize_segment(
                segment=seg,
                target_file=seg_file_path,
            )

            if not audio_data:
                # 触发降级生成
                fallback_occurred = True
                fallback_reasons.append(f"段落 {seg.segment_id} 合成失败,已降级")
                audio_data, duration_ms = self._generate_fallback_audio(
                    segment=seg,
                    target_file=seg_file_path,
                )
                seg_subs = [
                    SubtitleItem(
                        index=sub_index,
                        segment_id=seg.segment_id,
                        text=seg.narration,
                        start_ms=0,
                        end_ms=duration_ms,
                    )
                ]

            full_audio_bytes.extend(audio_data)

            # 更新整体时间轴偏移
            seg_model = AudioSegment(
                segment_id=seg.segment_id,
                narration=seg.narration,
                audio_path=str(seg_file_path.relative_to(output_dir)),
                duration_ms=duration_ms,
                start_offset_ms=current_offset_ms,
                end_offset_ms=current_offset_ms + duration_ms,
            )
            audio_segments.append(seg_model)

            # 调整字幕至全局时间轴
            for sub in seg_subs:
                sub_item = SubtitleItem(
                    index=sub_index,
                    segment_id=seg.segment_id,
                    text=sub.text,
                    start_ms=current_offset_ms + sub.start_ms,
                    end_ms=current_offset_ms + sub.end_ms,
                )
                all_subtitles.append(sub_item)
                sub_index += 1

            current_offset_ms += duration_ms

        # 保存整片合并音频
        full_audio_path = output_dir / "narration.mp3"
        full_audio_path.write_bytes(full_audio_bytes)

        # 保存字幕文件 (JSON + SRT)
        subs_json_path = output_dir / "subtitles.json"
        subs_json_path.write_text(
            json.dumps([s.model_dump() for s in all_subtitles], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        subs_srt_path = output_dir / "subtitles.srt"
        subs_srt_path.write_text(self._render_srt(all_subtitles), encoding="utf-8")

        result = AudioTrackPackage(
            county=county,
            voice=self._voice,
            total_duration_ms=current_offset_ms,
            full_audio_path=str(full_audio_path),
            segments=audio_segments,
            subtitles=all_subtitles,
            fallback_used=fallback_occurred,
            fallback_reason="; ".join(fallback_reasons) if fallback_reasons else "",
        )

        logger.info(
            "TTS 合成完成 | 县=%s | 总时长=%.2fs | 段数=%d | 降级=%s",
            county,
            current_offset_ms / 1000.0,
            len(audio_segments),
            fallback_occurred,
        )
        return result

    async def _synthesize_segment(
        self,
        *,
        segment: ScriptSegment,
        target_file: Path,
    ) -> tuple[bytes, int, list[SubtitleItem]]:
        """合成单个段落并提取时间戳。"""
        import edge_tts

        text = segment.narration.strip()
        if not text:
            return b"", 0, []

        try:
            return await self._call_edge_tts(
                text=text,
                segment_id=segment.segment_id,
                target_file=target_file,
            )
        except Exception as e:
            logger.warning("Edge-TTS 合成段落 %s 失败: %s", segment.segment_id, e)
            if self._fail_fast:
                raise
            return b"", 0, []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
    async def _call_edge_tts(
        self,
        text: str,
        segment_id: str,
        target_file: Path,
    ) -> tuple[bytes, int, list[SubtitleItem]]:
        """调用 edge-tts,带重试保护。"""
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
            proxy=self.proxy,
        )

        audio_chunks: list[bytes] = []
        cues: list[tuple[int, int, str]] = []  # (start_ms, end_ms, text)

        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio_chunks.append(chunk["data"])
            elif chunk_type in ("WordBoundary", "SentenceBoundary"):
                # offset 和 duration 单位为 100ns (1ms = 10,000 units)
                offset_ms = int(chunk["offset"] / 10_000)
                dur_ms = int(chunk["duration"] / 10_000)
                text_frag = chunk["text"]
                cues.append((offset_ms, offset_ms + dur_ms, text_frag))

        full_audio = b"".join(audio_chunks)
        if not full_audio:
            raise ValueError(f"Edge-TTS 未返回音频数据: segment={segment_id}")

        target_file.write_bytes(full_audio)

        # 估算时长(从 cues 尾部或数据流大小估算,MP3 ~16-24KB/s)
        duration_ms = cues[-1][1] if cues else int(len(full_audio) / 24)
        if duration_ms <= 0:
            duration_ms = max(int(len(text) / DEFAULT_CHARS_PER_SECOND * 1000), 1000)

        # 构建段落字幕条目
        subtitles: list[SubtitleItem] = []
        if cues:
            for idx, (s_ms, e_ms, sub_text) in enumerate(cues, 1):
                subtitles.append(
                    SubtitleItem(
                        index=idx,
                        segment_id=segment_id,
                        text=sub_text,
                        start_ms=s_ms,
                        end_ms=e_ms,
                    )
                )
        else:
            subtitles.append(
                SubtitleItem(
                    index=1,
                    segment_id=segment_id,
                    text=text,
                    start_ms=0,
                    end_ms=duration_ms,
                )
            )

        return full_audio, duration_ms, subtitles

    def _generate_fallback_audio(
        self,
        *,
        segment: ScriptSegment,
        target_file: Path,
    ) -> tuple[bytes, int]:
        """降级兜底:生成静音音频并写入文件,确保视频管线可继续。"""
        # 根据文本长度计算估算时长
        char_count = len(segment.narration)
        duration_seconds = max(char_count / DEFAULT_CHARS_PER_SECOND, 2.0)
        duration_ms = int(duration_seconds * 1000)

        # 生成合法的静音 WAV 数据作为占位音频 (44.1kHz, 16bit, mono)
        sample_rate = 44100
        num_samples = int(sample_rate * duration_seconds)
        silence_bytes = b"\x00\x00" * num_samples

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(silence_bytes)

        fallback_data = wav_io.getvalue()
        target_file.write_bytes(fallback_data)
        logger.warning(
            "触发音频降级: 段位 %s 写入静音占位音频, 时长 %d ms",
            segment.segment_id,
            duration_ms,
        )
        return fallback_data, duration_ms

    @staticmethod
    def _render_srt(subtitles: list[SubtitleItem]) -> str:
        """渲染为标准 SRT 字幕格式。"""
        lines: list[str] = []

        def _fmt_time(ms: int) -> str:
            td = timedelta(milliseconds=ms)
            total_seconds = int(td.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            seconds = total_seconds % 60
            millis = ms % 1000
            return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

        for sub in subtitles:
            lines.append(str(sub.index))
            lines.append(f"{_fmt_time(sub.start_ms)} --> {_fmt_time(sub.end_ms)}")
            lines.append(sub.text)
            lines.append("")

        return "\n".join(lines)
