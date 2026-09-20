"""短视频内容生产模块。

基于县域产业研究报告,生产 60 秒短视频脚本内容包:

第二阶段流程(升级):
    研究报告(Markdown) → StoryMiner → ContentDirector → ScriptGenerator → FactChecker → ContentPackage

公开类:
    - ContentPipeline      流水线编排(story_miner → director → script_generator → fact_checker)
    - StoryMiner           故事线提炼(研究报告 → StoryLine)
    - ContentDirector      选题角度策划(研究报告 → ContentAngle)
    - ScriptGenerator      60 秒脚本生成(ContentAngle → VideoScript)
    - FactChecker          事实核查(VideoScript + 报告 → FactCheckResult)
    - TopicAgent           选题发现(扫描本地 reports/ → TopicCandidate 列表)
    - SCRIPT_SEGMENTS      60 秒短视频固定 5 段时间轴常量

输出位置:
    content_outputs/{县名}/{日期}/{story.json, angle.json, script.md, fact_check.json, package.json}
"""
from .director import ContentDirector
from .fact_checker import FactChecker
from .pipeline import ContentPipeline
from .script_generator import ScriptGenerator
from .story_miner import StoryMiner
from .topic_agent import TopicAgent
from .templates import SCRIPT_SEGMENTS

__all__ = [
    "ContentPipeline",
    "StoryMiner",
    "ContentDirector",
    "ScriptGenerator",
    "FactChecker",
    "TopicAgent",
    "SCRIPT_SEGMENTS",
]
