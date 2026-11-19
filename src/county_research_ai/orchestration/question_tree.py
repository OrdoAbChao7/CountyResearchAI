"""研究问题树：把"县域 + 产业方向"展开为可分配的研究维度。

问题树只提供研究框架与检索模板，不产生任何事实结论；
Supervisor 可以覆盖或裁剪这些任务，Critic 的缺口也会反向补充问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.intelligence import AgentKind, ResearchTask


@dataclass(frozen=True)
class QuestionBranch:
    agent: AgentKind
    theme: str
    question: str
    queries: tuple[str, ...] = ()
    priority: int = 3


@dataclass
class ResearchQuestionTree:
    county: str
    focus: str
    root: str
    branches: list[QuestionBranch] = field(default_factory=list)

    def objectives(self) -> list[str]:
        return [branch.question for branch in self.branches]

    def default_tasks(self, *, round_no: int = 1, limit: int = 6) -> list[ResearchTask]:
        """Build one task per specialist.

        Multiple question branches can target the same specialist (for example
        a user objective plus the default industry branch).  They are merged
        into one task so a duplicate node does not silently consume a
        specialist slot at dispatch time.
        """
        by_agent: dict[AgentKind, ResearchTask] = {}
        for branch in sorted(self.branches, key=lambda b: b.priority):
            existing = by_agent.get(branch.agent)
            if existing is None:
                by_agent[branch.agent] = ResearchTask(
                    task_id=f"r{round_no}-{branch.agent.value}-1",
                    agent=branch.agent,
                    objective=branch.question,
                    queries=list(branch.queries),
                    priority=branch.priority,
                    round=round_no,
                )
                continue
            existing.queries = list(
                dict.fromkeys(existing.queries + list(branch.queries))
            )[:4]
            if branch.question not in existing.objective:
                existing.objective = (
                    f"{existing.objective}；补充目标：{branch.question}"
                )[:1000]
            existing.priority = min(existing.priority, branch.priority)
        return list(by_agent.values())[:limit]


def _queries(county: str, focus: str, *templates: str) -> list[str]:
    subject = f"{county}{focus}" if focus else county
    return [template.format(subject=subject, county=county, focus=focus) for template in templates]


def build_question_tree(
    county: str, focus: str = "", objectives: list[str] | None = None
) -> ResearchQuestionTree:
    direction = focus or "主导产业"
    root = (
        f"{county}如何围绕{direction}构建具有竞争力的产业体系？"
        if focus
        else f"{county}的主导产业选择、产业结构与升级路径是什么？"
    )
    focus_label = focus or "产业"
    branches = [
        QuestionBranch(
            agent=AgentKind.INDUSTRY,
            theme="产业结构与产业链",
            question=f"{county}{direction}的产业结构、产业链环节、集群与上下游关系如何？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 产业链 龙头企业 配套",
                    "{subject} 产业集群 发展现状",
                )
            ),
            priority=1,
        ),
        QuestionBranch(
            agent=AgentKind.MACRO,
            theme="宏观经济基本面",
            question=f"{county}的经济总量、增长、财政与产业结构基本面如何？",
            queries=tuple(
                _queries(
                    county,
                    "",
                    "{county} 统计公报 GDP 产业结构",
                    "{county} 财政收入 规上工业 增长",
                )
            ),
            priority=1,
        ),
        QuestionBranch(
            agent=AgentKind.ENTERPRISE,
            theme="企业与竞争格局",
            question=f"{county}{direction}有哪些龙头企业、规上企业与关键企业关系？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 龙头企业 规上企业 名单",
                    "{subject} 专精特新 供应链 合作",
                )
            ),
            priority=2,
        ),
        QuestionBranch(
            agent=AgentKind.POLICY,
            theme="政策环境",
            question=f"{county}针对{direction}出台了哪些规划、政策与扶持措施？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 产业政策 规划 实施方案",
                    "{county} 产业扶持 补贴 土地 人才政策",
                )
            ),
            priority=2,
        ),
        QuestionBranch(
            agent=AgentKind.GEO,
            theme="空间载体与区位",
            question=f"{county}{direction}的园区载体、土地、交通与资源禀赋如何？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 产业园区 开发区",
                    "{county} 交通 区位 土地 资源",
                )
            ),
            priority=3,
        ),
        QuestionBranch(
            agent=AgentKind.INNOVATION,
            theme="创新与技术",
            question=f"{county}{direction}的技术能力、专利、研发平台与产学研合作如何？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 专利 研发 技术创新",
                    "{subject} 科研院所 实验室 产学研",
                )
            ),
            priority=3,
        ),
        QuestionBranch(
            agent=AgentKind.QUANTITATIVE,
            theme="定量分析",
            question=f"{county}{direction}的区位熵、集中度与增长分解如何？",
            queries=tuple(
                _queries(
                    county,
                    focus_label,
                    "{subject} 产值 增加值 企业营收",
                )
            ),
            priority=4,
        ),
    ]

    if objectives:
        for objective in objectives:
            branches.append(
                QuestionBranch(
                    agent=AgentKind.INDUSTRY,
                    theme="用户指定问题",
                    question=objective,
                    queries=tuple(_queries(county, focus_label, "{subject} " + objective[:30])),
                    priority=0,
                )
            )
    return ResearchQuestionTree(county=county, focus=focus, root=root, branches=branches)


__all__ = [
    "QuestionBranch",
    "ResearchQuestionTree",
    "build_question_tree",
]
