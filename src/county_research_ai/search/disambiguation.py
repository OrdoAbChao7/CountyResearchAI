"""县域与地名行政区划消歧器。

解决：
1. 县 vs 县级市 vs 地级市 vs 市辖区 的行政层级消歧（如鹤岗市是地级市，安吉县是县，信丰县是县）；
2. 同名县域与跨省同名消歧；
3. 补全省份、地级市上下文，生成高质量限定词，避免搜索结果偏离或混淆上级地市总量数据。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DisambiguationResult:
    """行政区划消歧结果。"""
    raw_name: str
    clean_name: str
    province: str = ""
    prefecture: str = ""
    admin_level: str = "county"  # county(县) / county_level_city(县级市) / prefecture_level_city(地级市) / district(区)
    full_name: str = ""
    aliases: list[str] = field(default_factory=list)
    search_qualifiers: list[str] = field(default_factory=list)
    disambiguation_hint: str = ""

    def get_preferred_query_prefix(self) -> str:
        """获取检索前缀，包含必要省市限定。"""
        parts = [p for p in [self.province, self.prefecture, self.clean_name] if p]
        # 去重（例如如果省市名字相同或已经包含）
        unique_parts = []
        for p in parts:
            if not any(p in u or u in p for u in unique_parts):
                unique_parts.append(p)
            elif p == self.clean_name and p not in unique_parts:
                unique_parts.append(p)
        return " ".join(unique_parts) if unique_parts else self.clean_name


# 常见典型县域/县级市/地级市知识库（高频研究对象内置精确先验）
_KNOWN_REGIONS: dict[str, dict[str, str]] = {
    "安吉": {
        "clean_name": "安吉县",
        "province": "浙江省",
        "prefecture": "湖州市",
        "admin_level": "county",
        "hint": "浙江省湖州市辖县，中国第一竹乡，需区分湖州市全域与安吉县域数据",
    },
    "安吉县": {
        "clean_name": "安吉县",
        "province": "浙江省",
        "prefecture": "湖州市",
        "admin_level": "county",
        "hint": "浙江省湖州市辖县，中国第一竹乡",
    },
    "信丰": {
        "clean_name": "信丰县",
        "province": "江西省",
        "prefecture": "赣州市",
        "admin_level": "county",
        "hint": "江西省赣州市辖县，赣南脐橙发源地，需区分赣州市全域脐橙总量与信丰县本级数据",
    },
    "信丰县": {
        "clean_name": "信丰县",
        "province": "江西省",
        "prefecture": "赣州市",
        "admin_level": "county",
        "hint": "江西省赣州市辖县，赣南脐橙发源地",
    },
    "鹤岗": {
        "clean_name": "鹤岗市",
        "province": "黑龙江省",
        "prefecture": "鹤岗市",
        "admin_level": "prefecture_level_city",
        "hint": "黑龙江省地级市，百年煤城，资源枯竭型城市，辖六区两县（萝北、绥滨）",
    },
    "鹤岗市": {
        "clean_name": "鹤岗市",
        "province": "黑龙江省",
        "prefecture": "鹤岗市",
        "admin_level": "prefecture_level_city",
        "hint": "黑龙江省地级市，百年煤城，资源枯竭型城市",
    },
    "曹县": {
        "clean_name": "曹县",
        "province": "山东省",
        "prefecture": "菏泽市",
        "admin_level": "county",
        "hint": "山东省菏泽市辖县，汉服与木制品产业集聚区",
    },
    "义乌": {
        "clean_name": "义乌市",
        "province": "浙江省",
        "prefecture": "金华市",
        "admin_level": "county_level_city",
        "hint": "浙江省金华市代管县级市，小商品之都",
    },
    "义乌市": {
        "clean_name": "义乌市",
        "province": "浙江省",
        "prefecture": "金华市",
        "admin_level": "county_level_city",
        "hint": "浙江省金华市代管县级市",
    },
    "昆山": {
        "clean_name": "昆山市",
        "province": "江苏省",
        "prefecture": "苏州市",
        "admin_level": "county_level_city",
        "hint": "江苏省苏州市代管县级市，百强县之首",
    },
    "昆山市": {
        "clean_name": "昆山市",
        "province": "江苏省",
        "prefecture": "苏州市",
        "admin_level": "county_level_city",
        "hint": "江苏省苏州市代管县级市",
    },
    "正定": {
        "clean_name": "正定县",
        "province": "河北省",
        "prefecture": "石家庄市",
        "admin_level": "county",
        "hint": "河北省石家庄市辖县，历史文化名城与现代商贸物流",
    },
    "正定县": {
        "clean_name": "正定县",
        "province": "河北省",
        "prefecture": "石家庄市",
        "admin_level": "county",
        "hint": "河北省石家庄市辖县",
    },
    "十堰": {
        "clean_name": "十堰市",
        "province": "湖北省",
        "prefecture": "十堰市",
        "admin_level": "prefecture_level_city",
        "hint": "湖北省地级市，东风商用车发源地、中国商用车之都、南水北调中线核心水源区",
    },
    "十堰市": {
        "clean_name": "十堰市",
        "province": "湖北省",
        "prefecture": "十堰市",
        "admin_level": "prefecture_level_city",
        "hint": "湖北省地级市，东风商用车发源地、中国商用车之都、南水北调中线核心水源区",
    },
    "赣州经开区": {
        "clean_name": "赣州经开区",
        "province": "江西省",
        "prefecture": "赣州市",
        "admin_level": "district",
        "hint": "江西省赣州市国家级经济技术开发区，聚焦新能源汽车及关键零部件（孚能科技等）、电子信息、稀土新材料与智能制造",
    },
    "赣州经济技术开发区": {
        "clean_name": "赣州经开区",
        "province": "江西省",
        "prefecture": "赣州市",
        "admin_level": "district",
        "hint": "江西省赣州市国家级经济技术开发区，聚焦新能源汽车及关键零部件、电子信息与稀土新材料",
    },
}

_ADMIN_SUFFIXES = ("自治县", "自治旗", "特区", "林区", "旗", "县", "市", "区")


def disambiguate_region(name: str) -> DisambiguationResult:
    """根据输入的县域名进行消歧与层级推断。

    Args:
        name: 用户输入的县域名称（如 "安吉", "安吉县", "浙江省湖州市安吉县", "鹤岗市"）

    Returns:
        DisambiguationResult 消歧后的结构化数据
    """
    raw_name = name.strip()
    if not raw_name:
        return DisambiguationResult(raw_name="", clean_name="")

    # 1. 检查精确内置库
    if raw_name in _KNOWN_REGIONS:
        info = _KNOWN_REGIONS[raw_name]
        if info["prefecture"] and info["prefecture"] == info["clean_name"]:
            full_name = f"{info['province']}{info['clean_name']}"
        else:
            full_name = f"{info['province']}{info['prefecture']}{info['clean_name']}"
        return DisambiguationResult(
            raw_name=raw_name,
            clean_name=info["clean_name"],
            province=info["province"],
            prefecture=info["prefecture"],
            admin_level=info["admin_level"],
            full_name=full_name,
            aliases=[raw_name, info["clean_name"]],
            search_qualifiers=[info["clean_name"], f"{info['province']} {info['clean_name']}"],
            disambiguation_hint=info.get("hint", ""),
        )

    # 2. 检查前缀包含全称格式，例如 "浙江省湖州市安吉县"
    full_match = re.match(
        r"^([\u4e00-\u9fa5]{2,4}省|[\u4e00-\u9fa5]{2,4}自治区|北京市|上海市|天津市|重庆市)?"
        r"([\u4e00-\u9fa5]{2,6}市|[\u4e00-\u9fa5]{2,6}地区|[\u4e00-\u9fa5]{2,6}盟|[\u4e00-\u9fa5]{2,6}自治州)?"
        r"([\u4e00-\u9fa5]{2,8}(?:自治县|自治旗|特区|林区|旗|县|市|区))?$",
        raw_name,
    )
    if full_match:
        prov = full_match.group(1) or ""
        pref = full_match.group(2) or ""
        county = full_match.group(3) or ""
        if county:
            # 判断层级
            level = "county"
            if county.endswith("市"):
                level = "county_level_city"
            elif county.endswith("区"):
                level = "district"
            elif any(county.endswith(s) for s in ("自治县", "县", "旗", "自治旗")):
                level = "county"

            clean_name = county
            # 检查 clean_name 是否在库中
            hint = ""
            if clean_name in _KNOWN_REGIONS:
                info = _KNOWN_REGIONS[clean_name]
                prov = prov or info["province"]
                pref = pref or info["prefecture"]
                level = info["admin_level"]
                hint = info.get("hint", "")

            full = f"{prov}{pref}{clean_name}"
            return DisambiguationResult(
                raw_name=raw_name,
                clean_name=clean_name,
                province=prov,
                prefecture=pref,
                admin_level=level,
                full_name=full,
                aliases=[raw_name, clean_name],
                search_qualifiers=[clean_name, f"{prov} {clean_name}".strip()],
                disambiguation_hint=hint,
            )
        elif pref:
            # 输入为包含省份的地级市（如“黑龙江省鹤岗市”）
            clean_name = pref
            level = "prefecture_level_city"
            hint = ""
            if clean_name in _KNOWN_REGIONS:
                info = _KNOWN_REGIONS[clean_name]
                prov = prov or info["province"]
                level = info["admin_level"]
                hint = info.get("hint", "")

            full = f"{prov}{clean_name}"
            return DisambiguationResult(
                raw_name=raw_name,
                clean_name=clean_name,
                province=prov,
                prefecture=pref,
                admin_level=level,
                full_name=full,
                aliases=[raw_name, clean_name],
                search_qualifiers=[clean_name, f"{prov} {clean_name}".strip()],
                disambiguation_hint=hint,
            )

    # 3. 基础归一化（如果没有后缀，尝试补充“县”或原样输出）
    clean_name = raw_name
    admin_level = "county"
    if any(raw_name.endswith(suffix) for suffix in _ADMIN_SUFFIXES):
        if raw_name.endswith("市"):
            admin_level = "county_level_city"
        elif raw_name.endswith("区"):
            admin_level = "district"
    else:
        # 没有后缀的 2 字符地名（如 "安吉"、"信丰"）尝试加 "县"
        if len(raw_name) <= 3:
            candidate = f"{raw_name}县"
            if candidate in _KNOWN_REGIONS:
                info = _KNOWN_REGIONS[candidate]
                return DisambiguationResult(
                    raw_name=raw_name,
                    clean_name=info["clean_name"],
                    province=info["province"],
                    prefecture=info["prefecture"],
                    admin_level=info["admin_level"],
                    full_name=f"{info['province']}{info['prefecture']}{info['clean_name']}",
                    aliases=[raw_name, info["clean_name"]],
                    search_qualifiers=[info["clean_name"], f"{info['province']} {info['clean_name']}"],
                    disambiguation_hint=info.get("hint", ""),
                )
            clean_name = candidate

    return DisambiguationResult(
        raw_name=raw_name,
        clean_name=clean_name,
        admin_level=admin_level,
        full_name=clean_name,
        aliases=[raw_name, clean_name],
        search_qualifiers=[clean_name],
    )
