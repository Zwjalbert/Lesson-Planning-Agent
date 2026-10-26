# -*- coding: utf-8 -*-
"""课程知识库与上下文装配（v2）。

两层知识：
  1. 公共资源区（Public Vault）：学校模板、课程标准、教学方法论、案例库、思政素材，
     全校共享，按相关性取 Top-K；
  2. 课程库：本课程上传资料，按原文注入（唯一事实依据）。

注入顺序遵循「先公共规范 → 后课程事实 → 再本次需求」：
  公共资源给「怎么写/按什么标准」；课程资料给「写什么」；focus/tone 给「这一次偏什么」。
超出长度时按资料份数公平分配并显式标注截断，避免第一份资料挤掉其余资料。
"""
import re
from collections import Counter

from . import config, store

_STOP = set(
    "的了在和是就都而及与或一个这那我你他她它们对于关于通过进行可以需要我们你们"
    "以及并但从而因此同时主要教学课程内容学生教师本周上周什么怎么如何以及如果"
    "因为所以没有不是就是还要可能应该我们他们这个那个"
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fa5]{2,8}|[A-Za-z]{2,}")


def _terms(text: str) -> list:
    return [w for w in _TOKEN_RE.findall(text or "") if w not in _STOP]


def split_chunks(text: str, filename: str = "", material_id: int = 0,
                 size: int = 800, overlap: int = 80) -> list:
    """按段落切块，块间保留少量重叠，避免概念被切断。"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if len(p.strip()) > 8]
    chunks, buf, buf_len = [], "", 0

    def flush():
        nonlocal buf, buf_len
        if buf.strip():
            chunks.append({"source": filename, "material_id": material_id, "text": buf.strip()})
        tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
        buf, buf_len = tail, len(tail)

    for p in paras:
        if buf_len + len(p) > size and buf:
            flush()
        buf += p + "\n"
        buf_len += len(p)
    if buf.strip():
        chunks.append({"source": filename, "material_id": material_id, "text": buf.strip()})
    return chunks


def build_index(course_id: int) -> list:
    idx = []
    for m in store.list_materials(course_id, with_content=True):
        idx.extend(split_chunks(m.get("content") or "", m.get("filename") or "",
                                m.get("id") or 0))
    return idx


def _score(query: str, chunk: str) -> float:
    q_words = _terms(query)
    if not q_words:
        return 0.0
    c_words = Counter(_terms(chunk))
    # 词频 × 词长（长词更特异），并给开头命中小幅加权
    s = sum(min(c_words.get(w, 0), 4) * (len(w) - 1) for w in q_words)
    head = chunk[:120]
    s += sum(1.5 for w in q_words if w in head)
    return s


def search(course_id: int, query: str, top_k: int = 4) -> list:
    """检索最相关的资料块。"""
    idx = build_index(course_id)
    if not idx:
        return []
    scored = [(_score(query, c["text"]), c) for c in idx]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for s, c in scored:
        key = (c["source"], c["text"][:80])
        if key in seen:
            continue
        seen.add(key)
        out.append({"source": c["source"], "text": c["text"][:800],
                    "score": round(s, 2), "material_id": c.get("material_id", 0)})
        if len(out) >= top_k:
            break
    return out


def summarize_materials(course_id: int) -> str:
    lines = []
    for m in store.list_materials(course_id):
        s = (m.get("summary") or "").strip()
        if not s:
            s = "（尚未生成摘要）"
        lines.append(f"- 《{m['filename']}》（{m.get('chars') or 0} 字）：{s}")
    return "\n".join(lines) or "（暂无上传资料：请在上传资料页添加教学计划、教材目录或课程要求）"


def full_context(course_id: int, limit_chars: int = None) -> str:
    """课程资料原文注入：多份资料公平分配字符预算，超长显式标注。"""
    limit = int(limit_chars or config.MAX_CONTEXT_CHARS)
    mats = store.list_materials(course_id, with_content=True)
    if not mats:
        return ("（课程知识库暂无上传资料。请基于教学常识生成，并在依据不足处显式标注"
                "「（依据教学常识补充）」；同时提醒教师补充教学计划/教材等资料。）")
    n = len(mats)
    per = max(1200, limit // max(1, n))
    parts, used = [], 0
    for m in mats:
        content = m.get("content") or ""
        budget = min(per, max(200, limit - used))
        seg = content[:budget]
        used += len(seg)
        head = f"【资料《{m['filename']}》（原文，共 {len(content)} 字）】"
        parts.append(head + "\n" + seg)
        if len(content) > len(seg):
            parts.append(f"（《{m['filename']}》后续 {len(content) - len(seg)} 字未注入："
                         "已超出上下文长度，请以已注入部分和检索片段为准，不要编造未出现的内容）")
    return "\n\n".join(parts)


def vault_context(query: str, top_k: int = None, limit_chars: int = 4200) -> str:
    """公共资源区注入：按相关性取条目，每条约 1200 字。"""
    k = int(top_k or config.VAULT_TOP_K)
    items = store.search_vault(query, limit=k)
    if not items:
        return "（公共资源区暂无匹配条目）"
    per = max(600, limit_chars // max(1, len(items)))
    parts = []
    for it in items:
        kind = store.VAULT_KINDS.get(it.get("kind"), it.get("kind"))
        text = (it.get("content") or "")[:per]
        parts.append(f"【{kind}·{it['name']}】\n{text}")
    return "\n\n".join(parts)


def assemble_context(course_id: int, query: str, focus: str = "", tone: str = "",
                     include_vault: bool = True) -> str:
    """装配一次生成所需的完整上下文（公共 → 课程 → 本次需求）。"""
    parts = []
    if include_vault:
        parts.append("========== 公共资源区（学校规范/方法/思政素材，按相关性选取） ==========\n"
                     + vault_context(query))
    parts.append("========== 课程资料原文（唯一事实依据） ==========\n"
                 + full_context(course_id))
    hits = search(course_id, query, top_k=4)
    if hits:
        lines = ["========== 与本次内容最相关的资料片段（针对性检索） =========="]
        for i, h in enumerate(hits, 1):
            lines.append(f"[{i}] 来源《{h['source']}》：\n{h['text']}")
        parts.append("\n".join(lines))
    demand = []
    if focus:
        demand.append(f"本次侧重点：{focus}")
    if tone:
        demand.append(f"语言风格/语气：{tone}")
    if demand:
        parts.append("========== 本次需求 ==========\n" + "\n".join(demand))
    return "\n\n".join(parts)


def stats(course_id: int) -> dict:
    mats = store.list_materials(course_id, with_content=True)
    chars = sum(len(m.get("content") or "") for m in mats)
    return {"count": len(mats), "chars": chars,
            "with_summary": sum(1 for m in mats if m.get("summary"))}
