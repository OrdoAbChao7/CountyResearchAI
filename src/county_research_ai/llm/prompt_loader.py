"""提示词模板加载与渲染。

从项目 prompts/ 目录加载 Markdown 模板,用 Jinja2 填充变量后返回字符串。

特性:
    - 模板文件缓存(避免重复读盘)
    - 支持 has_template() 预检(避免抛异常)
    - 支持 render_string() 渲染内联字符串(用于 fallback)
    - 自动转义关闭(生成文本而非 HTML)

模板变量约定(各 prompt 共用):
    county            县名(已格式化)
    focus             研究方向
    date              日期字符串
    processed_data    清洗后的数据文本(供 analysis 类模板)
    analysis_content  已有分析结果文本(供 summary 类模板)
"""
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from ..config import Settings, get_settings
from ..exceptions import LLMError

logger = logging.getLogger(__name__)


class PromptLoader:
    """提示词模板加载器。

    Usage:
        loader = PromptLoader()
        if loader.has_template("industry_analysis"):
            prompt = loader.render("industry_analysis", county="安吉县", focus="竹产业", ...)
        else:
            prompt = loader.render_string("分析 {{ county }} 的 {{ focus }}", county=..., focus=...)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._prompts_dir: Path = self._settings.prompts_dir
        self._env = Environment(
            loader=FileSystemLoader(str(self._prompts_dir)),
            autoescape=False,            # 不转义 HTML 实体
            keep_trailing_newline=True,  # 保留模板末尾换行
            trim_blocks=True,            # 块标签后第一个换行自动去除
            lstrip_blocks=True,          # 块标签前导空白自动去除
        )
        self._cache: dict[str, object] = {}  # name -> Template

    def get_template(self, name: str):
        """按名称获取模板(带缓存)。

        Args:
            name: 模板名,不含扩展名(自动追加 .md);
                  若已含 .md 则原样使用

        Returns:
            Jinja2 Template 对象

        Raises:
            LLMError: 模板文件不存在
        """
        if name in self._cache:
            return self._cache[name]

        filename = name if name.endswith(".md") else f"{name}.md"
        try:
            tpl = self._env.get_template(filename)
        except TemplateNotFound as err:
            raise LLMError(
                f"提示词模板不存在: {filename}",
                context={"name": name, "filename": filename, "prompts_dir": str(self._prompts_dir)},
            ) from err
        self._cache[name] = tpl
        return tpl

    def render(self, name: str, **kwargs: object) -> str:
        """渲染指定模板。

        Args:
            name: 模板名(不含扩展名)
            **kwargs: 模板变量

        Returns:
            渲染后的字符串
        """
        tpl = self.get_template(name)
        try:
            return tpl.render(**kwargs)
        except Exception as e:
            raise LLMError(
                f"模板渲染失败: {name}",
                context={"name": name, "error": str(e), "vars": list(kwargs.keys())},
            ) from e

    def render_string(self, template_str: str, **kwargs: object) -> str:
        """渲染内联字符串模板(用于 fallback 场景)。

        Args:
            template_str: 含 Jinja2 语法的字符串
            **kwargs: 模板变量

        Returns:
            渲染后的字符串
        """
        try:
            return self._env.from_string(template_str).render(**kwargs)
        except Exception as e:
            raise LLMError(
                "字符串模板渲染失败",
                context={"template": template_str[:200], "error": str(e)},
            ) from e

    def has_template(self, name: str) -> bool:
        """检查模板文件是否存在(不抛异常)。"""
        filename = name if name.endswith(".md") else f"{name}.md"
        exists = (self._prompts_dir / filename).exists()
        if not exists:
            logger.debug("模板不存在(将使用 fallback) | name=%s", name)
        return exists

    @property
    def prompts_dir(self) -> Path:
        """模板根目录(便于诊断)。"""
        return self._prompts_dir
