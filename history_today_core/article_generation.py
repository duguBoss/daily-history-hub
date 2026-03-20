from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any

import requests

from .common import log, to_simplified
from .constants import FALLBACK_GEMINI_MODEL, PRIMARY_GEMINI_MODEL, REQUEST_TIMEOUT
from .filters import is_china_related_text

def build_gemini_prompt(target_date: dt.date, merged_items: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    compact_items = [
        {
            "year": item["year"],
            "text": item["text"],
            "categories": item["categories"],
            "sources": item["sources"],
            "source_confidence": item["source_confidence"],
            "page_title": item["pages"][0]["title"] if item["pages"] else "",
            "detail_title": (item.get("detail") or {}).get("title", ""),
            "detail_description": (item.get("detail") or {}).get("description", ""),
            "detail_extract": (item.get("detail") or {}).get("extract", ""),
            "detail_url": (item.get("detail") or {}).get("url", ""),
        }
        for item in merged_items
    ]
    return (
        "You are writing a finished WeChat article.\n"
        "**CRITICAL REQUIREMENTS (必须严格遵守以下所有限制):**\n"
        "1. 语言要求：**全部内容必须使用标准简体中文（Simplified Chinese）**。绝对禁止输出繁体字！绝对禁止出现整句或整段的英文（除必须保留的少数专有名词外，务必将所有英文素材完美翻译成中文）。\n"
        "2. 叙事视角：作为全知全能的叙述者直接陈述历史事实。**绝对禁止**出现任何表明信息来源的词汇（如“根据大英百科全书”、“维基百科补充提到”、“资料显示”、“参考记录”等）。\n"
        "3. 消除AI痕迹：**绝对禁止**使用任何AI生成的元语言或修饰词（如“缺少详细信息”、“这标志着”、“不可否认”、“以下为您生成”、“为您串联”等）。\n"
        "4. 内容完整性：文章必须结构完整、连贯流畅，自然地展开故事，并且有一个合理的收尾句。**绝对不能**烂尾、中途断裂或显得拼凑缺失。\n"
        "5. 行文风格：引人入胜的杂志深度专栏风格，同时保持客观真实，不带感情色彩。\n"
        "Exclude anything related to China, PRC, ROC, Hong Kong, Macau, Taiwan, Tibet, Xinjiang, Chinese dynasties, politics, parties, sovereignty, independence, territorial disputes, border conflicts, coups, rebellions, revolutions, sanctions, diplomatic crises, and geopolitics.\n"
        "The title must be in Simplified Chinese. Must be exactly 32 characters. Must follow this format: '历史上的今天：[流量标题格式，包含悬念/数字/反差/热点词]，例如：历史上的今天：此人发明一物改变世界，至今仍影响每个人'.\n"
        "Return valid JSON only with this schema:\n"
        "{\n"
        '  "title": "简体中文标题，严格32字",\n'
        '  "summary": "纯简体中文摘要，不超过80字",\n'
        '  "content_text": "complete Chinese article body with at least 5 paragraphs separated by \\n\\n, combining the historical points logically."\n'
        "}\n"
        "Do not output markdown. Do not output HTML. Do not mention filtering.\n"
        f"Target date: {target_date.isoformat()}\n"
        f"Merged items: {json.dumps(compact_items, ensure_ascii=False)}"
    )


def validate_gemini_result(result: dict[str, Any]) -> dict[str, Any]:
    for key in ("title", "summary", "content_text"):
        value = result.get(key, "")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Gemini output missing {key}")
        
        # 自动将繁体字转换为简体字
        value = to_simplified(value)
        
        if is_china_related_text(value):
            raise RuntimeError(f"Validation failed: output contains filtered (China-related) content in [{key}].")
        
        # 拦截大段英文 (如果内容中英文字母占比异常高，说明输出了英文段落)
        alpha_count = len(re.findall(r'[a-zA-Z]', value))
        if len(value) > 0 and (alpha_count / len(value)) > 0.3:
            raise RuntimeError(f"Validation failed: Gemini output contains too much English text in [{key}].")

        # 拦截暴露来源和AI痕迹的词汇
        forbidden_words = ["补充提到", "根据", "资料显示", "维基百科", "大英百科全书", "大英百科", "参考"]
        found_words = [word for word in forbidden_words if word in value]
        if found_words:
             raise RuntimeError(f"Validation failed: Gemini output contains forbidden source words ({found_words}) in [{key}].")
             
        result[key] = value
             
    if len(result["summary"].strip()) > 80:
        raise RuntimeError("Validation failed: Gemini output summary exceeds 80 characters.")
    return result


def call_gemini_once(prompt: str, model_name: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Missing GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            # 将 temperature 提高到 0.75，增加输出多样性，打破僵化的输出格式
            "generationConfig": {"temperature": 0.75, "responseMimeType": "application/json"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {payload}")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError(f"Gemini returned empty text: {payload}")
        
    # === 关键控制台打印：在这里打印AI直接吐出的内容，方便排查 ===
    log(f"\n================ Gemini Raw Output ({model_name}) ================\n{text}\n==================================================================\n")

    try:
        parsed_result = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini output is not valid JSON: {e}")

    return validate_gemini_result(parsed_result)


def call_gemini(prompt: str) -> dict[str, Any]:
    errors: list[str] = []
    max_retries = 2
    for attempt in range(max_retries):
        for model_name in (PRIMARY_GEMINI_MODEL, FALLBACK_GEMINI_MODEL):
            try:
                result = call_gemini_once(prompt, model_name)
                if attempt > 0:
                    log(f"重试成功! (尝试 {attempt + 1})")
                return result
            except Exception as exc:
                errors.append(f"{model_name} Error: {exc}")
                log(f"生成失败 (尝试 {attempt + 1}, 模型 {model_name}): {exc}")
                continue
    raise RuntimeError(" | ".join(errors))


def build_fallback_article(target_date: dt.date, merged_items: list[dict[str, Any]]) -> dict[str, Any]:
    # 为了避免输出纯英文，这里先过滤出包含中文字符的事件用于拼接兜底文章
    zh_items = [item for item in merged_items if re.search(r'[\u4e00-\u9fff]', item.get('text', ''))]
    if not zh_items:
        # 如果极端情况下没有任何中文内容，依然拿几个凑数（此时可能会出现英文）
        zh_items = merged_items[:6]
        
    selected = zh_items[:6]
    paragraphs = [
        f"{target_date.month}月{target_date.day}日这一天，历史留下了几段截然不同的切片，权力更替、突发事件和人物命运交错重叠。"
    ]
    for item in selected:
        detail = item.get("detail") or {}
        detail_text = detail.get("extract") or detail.get("description") or ""
        # 移除原有的“维基页面补充提到：”这种机械和暴露来源的拼凑方式
        if detail_text and detail_text not in item['text']:
            paragraphs.append(f"{item['year']}年：{item['text']} {detail_text}")
        else:
            paragraphs.append(f"{item['year']}年：{item['text']}")
            
    paragraphs.append("时间的刻度在这些事件中不断延展，共同构建了我们今天所认识的世界。")
    
    content_text = "\n\n".join(paragraphs)
    content_text = to_simplified(content_text)
        
    return {
        "title": to_simplified(f"历史上的今天：{target_date.month}月{target_date.day}日发生了什么"),
        "summary": to_simplified("这一天并不平静，几段历史在同日交错。"),
        "content_text": content_text,
    }
