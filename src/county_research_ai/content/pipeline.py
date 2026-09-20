"""短视频内容生产流水线。

串联(第二阶段):
    story_miner → director → script_generator → fact_checker → ContentPackage

输入: 县名 + 已生成的研究报告路径(Markdown)
输出: ContentPackage(落盘到 content_outputs/{县名}/{日期}/)

落盘文件:
    - story.json        故事线(第二阶段新增)
    - angle.json        选题角度
    - script.md         脚本(人类可读 Markdown,含旁白/字幕/画面/证据)
    - fact_check.json   事实核查结果
    - package.json      完整内容包

设计要点:
    - 不依赖研究 Pipeline,只消费已生成的研究报告
    - 与 storage/local_fs.py 风格一致:目录创建幂等、UTF-8、中文不转义
    - 单步失败不阻断整体(fail_fast=False 时各步降级),最终落盘始终执行
    - StoryMiner 严禁编造,失败时 story_line 为 None
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import PROJECT_ROOT, Settings, get_settings
from ..models import ContentPackage
from .director import ContentDirector
from .fact_checker import FactChecker
from .script_generator import ScriptGenerator
from .story_miner import StoryMiner

logger = logging.getLogger(__name__)


class ContentPipeline:
    """短视频内容生产流水线。

    Usage:
        pipe = ContentPipeline()
        pkg = pipe.produce(
            county="安吉县",
            report_path="reports/安吉县_竹产业_20260806.md",
        )
        # pkg: ContentPackage
    """

    # 研究报告读取截断长度(防止超出 LLM 上下文)
    _MAX_REPORT_CHARS = 12000

    def __init__(
        self,
        story_miner: StoryMiner | None = None,
        director: ContentDirector | None = None,
        script_generator: ScriptGenerator | None = None,
        fact_checker: FactChecker | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._story_miner = story_miner or StoryMiner(settings=self._settings)
        self._director = director or ContentDirector(settings=self._settings)
        self._script_generator = script_generator or ScriptGenerator(settings=self._settings)
        self._fact_checker = fact_checker or FactChecker(settings=self._settings)
        # 输出根目录:content_outputs/(项目根下,与 reports/ 同级)
        self._output_root = PROJECT_ROOT / "content_outputs"

    # ---- 公开入口 ----

    def produce(self, *, county: str, report_path: str) -> ContentPackage:
        """执行完整内容生产流水线,返回 ContentPackage 并落盘。

        Args:
            county: 县名
            report_path: 研究报告 Markdown 路径

        Returns:
            ContentPackage(同时已落盘到 content_outputs/{县名}/{日期}/)
        """
        logger.info("内容生产流水线启动 | 县=%s | 报告=%s", county, report_path)
        report_content = self._load_report(report_path)

        # 0. 故事线提炼(第二阶段新增)
        story_line = self._story_miner.mine(county=county, report_content=report_content)

        # 1. 选题角度
        angle = self._director.generate_angle(county=county, report_content=report_content)
        # 2. 短视频脚本
        script = self._script_generator.generate_script(county=county, angle=angle)
        # 3. 事实核查
        fact_check = self._fact_checker.check(
            county=county, script=script, report_content=report_content,
        )
        # 4. 组装内容包
        package = ContentPackage(
            county=county,
            report_path=report_path,
            story_line=story_line if story_line.main_story else None,  # 空故事线不填充
            angle=angle,
            script=script,
            fact_check=fact_check,
        )
        # 5. 落盘
        out_dir = self._save_package(package=package)
        logger.info(
            "内容生产流水线完成 | 输出=%s | 核查状态=%s",
            out_dir, fact_check.overall_status,
        )
        return package

    @property
    def output_root(self) -> Path:
        """输出根目录(便于诊断)。"""
        return self._output_root

    # ---- 内部方法 ----

    def _load_report(self, report_path: str) -> str:
        """读取研究报告 Markdown 文本(截断到 _MAX_REPORT_CHARS 防 token 超限)。"""
        p = Path(report_path)
        if not p.exists():
            raise FileNotFoundError(f"研究报告不存在: {report_path}")
        text = p.read_text(encoding="utf-8")
        if len(text) > self._MAX_REPORT_CHARS:
            logger.warning(
                "研究报告过长已截断 | 原长=%d | 截断=%d",
                len(text), self._MAX_REPORT_CHARS,
            )
            text = text[: self._MAX_REPORT_CHARS]
        return text

    def _save_package(self, *, package: ContentPackage) -> Path:
        """按 content_outputs/{县名}/{日期}/{5 文件} 落盘。"""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        county_safe = self._safe_name(package.county)
        out_dir = self._output_root / county_safe / date_str
        out_dir.mkdir(parents=True, exist_ok=True)

        # story.json — 故事线(第二阶段新增,可选)
        if package.story_line:
            (out_dir / "story.json").write_text(
                package.story_line.model_dump_json(indent=2), encoding="utf-8",
            )
        # angle.json — 选题角度
        (out_dir / "angle.json").write_text(
            package.angle.model_dump_json(indent=2), encoding="utf-8",
        )
        # script.md — 脚本(人类可读 Markdown)
        (out_dir / "script.md").write_text(
            self._render_script_md(package), encoding="utf-8",
        )
        # fact_check.json — 事实核查结果
        (out_dir / "fact_check.json").write_text(
            package.fact_check.model_dump_json(indent=2), encoding="utf-8",
        )
        # package.json — 完整内容包
        (out_dir / "package.json").write_text(
            package.model_dump_json(indent=2), encoding="utf-8",
        )
        return out_dir

    @staticmethod
    def _render_script_md(package: ContentPackage) -> str:
        """渲染脚本为人类可读 Markdown(便于人工审阅与配音)。"""
        lines: list[str] = []
        lines.append(f"# {package.script.title}")
        lines.append("")
        lines.append(f"- 县名: {package.county}")
        lines.append(f"- 来源报告: `{package.report_path}`")
        lines.append(f"- 角度 ID: `{package.angle.angle_id}`")
        lines.append(f"- 总字数: {package.script.total_word_count}")
        lines.append(f"- 核查状态: **{package.fact_check.overall_status}**")
        lines.append("")

        # 故事线信息(第二阶段新增)
        if package.story_line and package.story_line.main_story:
            lines.append("## 故事线")
            lines.append("")
            lines.append(f"**主线**: {package.story_line.main_story}")
            lines.append("")
            if package.story_line.time_span:
                lines.append(f"- 时间跨度: {package.story_line.time_span}")
            if package.story_line.conflict_type:
                lines.append(f"- 冲突类型: {package.story_line.conflict_type}")
            if package.story_line.characters:
                lines.append(f"- 关键人物: {', '.join(package.story_line.characters)}")
            if package.story_line.enterprises:
                lines.append(f"- 关键企业: {', '.join(package.story_line.enterprises)}")
            if package.story_line.events:
                lines.append(f"- 关键事件: {', '.join(package.story_line.events)}")
            if package.story_line.data_points:
                lines.append(f"- 关键数据: {', '.join(package.story_line.data_points)}")
            lines.append("")

        # 选题角度信息
        if package.angle.hook or package.angle.perspective:
            lines.append("## 选题角度")
            lines.append("")
            if package.angle.hook:
                lines.append(f"**钩子**: {package.angle.hook}")
                lines.append("")
            if package.angle.perspective:
                lines.append(f"**视角**: {package.angle.perspective}")
                lines.append("")
            if package.angle.target_audience:
                lines.append(f"**目标受众**: {package.angle.target_audience}")
                lines.append("")
            if package.angle.tone:
                lines.append(f"**叙事基调**: {package.angle.tone}")
                lines.append("")
            if package.angle.key_points:
                lines.append("**核心要点**:")
                for kp in package.angle.key_points:
                    lines.append(f"- {kp}")
                lines.append("")
        # 脚本段位
        lines.append("## 脚本")
        lines.append("")
        for seg in package.script.segments:
            lines.append(f"### [{seg.time_range}] {seg.segment_id}")
            lines.append("")
            lines.append(f"**旁白**: {seg.narration}")
            lines.append("")
            if seg.on_screen:
                lines.append(f"**屏幕文字**: {seg.on_screen}")
                lines.append("")
            if seg.visual_hint:
                lines.append(f"**画面建议**: {seg.visual_hint}")
                lines.append("")
            if seg.source_refs:
                lines.append("**证据来源**:")
                for ref in seg.source_refs:
                    lines.append(f"- {ref}")
                lines.append("")
        # 事实核查结果
        if package.fact_check.items:
            lines.append("## 事实核查")
            lines.append("")
            lines.append(f"整体状态: **{package.fact_check.overall_status}**")
            lines.append("")
            for it in package.fact_check.items:
                lines.append(f"- [{it.verdict}] `{it.segment_id}` {it.claim}")
                if it.evidence:
                    lines.append(f"  - 依据: {it.evidence}")
                if it.note:
                    lines.append(f"  - 备注: {it.note}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _safe_name(name: str) -> str:
        """清洗路径组件(与 LocalFSStorage._safe_name 一致)。"""
        if not name:
            return "unnamed"
        cleaned = name.strip().replace("/", "_").replace("\\", "_")
        for ch in (':', '*', '?', '"', '<', '>', '|'):
            cleaned = cleaned.replace(ch, "_")
        while "__" in cleaned:
            cleaned = cleaned.replace("__", "_")
        return cleaned.strip("_") or "unnamed"
