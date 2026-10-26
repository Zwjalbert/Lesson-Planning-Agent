# -*- coding: utf-8 -*-
"""需求映射（Intent Mapper）。

把教师的一句话解析成结构化任务：
  {action, workflow, file_types, weeks, target, focus, tone, questions, reply}

优先调用大模型（intent_mapper 框架）；未配置 Key 或模型解析失败时，
退回本地规则解析，保证「对话总控」在无 Key 时也能给出可用引导。
"""
import json
import re

from .. import store, gateway, config
from . import prompts, tools


def _extract_json(text: str) -> dict:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            data = json.loads(t[s:e + 1])
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def _weeks_in(text: str) -> list:
    weeks = set()
    for a, b in re.findall(r"(\d{1,2})\s*[-~—至到]\s*(\d{1,2})\s*周", text or ""):
        a, b = int(a), int(b)
        if 1 <= a <= b <= 30:
            weeks |= set(range(a, min(b, 30) + 1))
    for s in re.findall(r"第?\s*(\d{1,2})\s*周", text or ""):
        n = int(s)
        if 1 <= n <= 30:
            weeks.add(n)
    return sorted(weeks)


def _file_types_in(text: str) -> list:
    t = text or ""
    if any(k in t for k in ("教学包", "全套", "一套", "所有文件", "全部文件")):
        return ["lesson_plan", "handout", "courseware", "script"]
    out = []
    if "教案" in t:
        out.append("lesson_plan")
    if "讲义" in t:
        out.append("handout")
    if any(k in t for k in ("课件", "PPT", "ppt", "幻灯片", "演示文稿", "互动课件")):
        out.append("courseware")
    if any(k in t for k in ("逐字稿", "讲稿", "口播稿")):
        out.append("script")
    return out or ["lesson_plan", "handout", "courseware", "script"]


def _rule_parse(text: str, course: dict, planned: list, artifacts: list) -> dict:
    t = text or ""
    weeks = _weeks_in(t)
    fts = _file_types_in(t)
    focus = ""
    m = re.search(r"(?:侧重|重点|多放|加强|突出|要求|希望)[:：]?\s*([^。；\n]{2,40})", t)
    if m:
        focus = m.group(1).strip()
    tone = ""
    for kw in ("通俗", "生动", "有趣", "幽默", "严谨", "正式", "口语化", "贴近学生"):
        if kw in t:
            tone = kw
            break
    target = None
    mt = re.search(r"第?\s*(\d{1,2})\s*周[^\n。；]{0,8}(教案|讲义|课件|PPT|ppt|逐字稿|讲稿)", t)
    if mt:
        ft = {"教案": "lesson_plan", "讲义": "handout", "课件": "courseware",
              "PPT": "courseware", "ppt": "courseware",
              "逐字稿": "script", "讲稿": "script"}[mt.group(2)]
        target = {"week": int(mt.group(1)), "file_type": ft}

    if any(k in t for k in ("修改", "改成", "调整", "润色", "修订", "换一个", "替换")):
        action, workflow = "revise", "single_file"
    elif any(k in t for k in ("课程地图", "地图", "周计划", "教学规划", "规划一下", "大纲")):
        action, workflow = "course_map", "course_map"
    elif any(k in t for k in ("生成", "备课", "准备", "撰写", "写", "产出", "做一份", "来一份")):
        action = "generate"
        workflow = "week_package" if len(fts) >= 2 else "single_file"
    else:
        action, workflow = "ask", "ask"

    if action == "revise" and not target:
        # 只有「修改第 3 周」但没有文件类型时，默认教案
        if weeks:
            target = {"week": weeks[0], "file_type": "lesson_plan"}
    questions = []
    reply = ""
    if action == "generate":
        if not planned:
            action, workflow = "course_map", "course_map"
            reply = "课程地图还没生成，我先按你给的周次生成地图，确认后再生成教学包。"
        elif not weeks:
            pending = _pending_weeks(planned, artifacts)
            weeks = pending or planned
            reply = f"我将按课程地图生成第{'、'.join(map(str, weeks))}周的教学文件。"
        else:
            reply = f"开始准备第{'、'.join(map(str, weeks))}周的文件。"
    elif action == "course_map":
        weeks = weeks or list(range(1, int(course.get("weeks") or 16) + 1))
        reply = f"生成第{'、'.join(map(str, weeks[0:1]))}{'等 ' + str(len(weeks)) + ' ' if len(weeks) > 1 else ''}周的课程地图，确认后进入生成。"
    elif action == "revise":
        if target:
            reply = (f"准备修改第{target['week']}周"
                     f"{tools.file_type_cn(target['file_type'])}，请在下方填写具体修改要求。")
        else:
            questions = ["要修改哪一周、哪一份文件？", "希望怎么改（换案例/调节奏/改思政点/精简）？"]
            reply = "我可以直接改某一份文件，请告诉我「第几周 + 教案/讲义/课件/逐字稿」和修改要求。"
    else:
        reply = ("你可以直接说：「生成第 2-3 周教学包」「生成第 2 周课件」「重做第 3 周教案」「把第 2 周导入换成校园案例」。"
                 if planned else "建议先生成课程地图（门 A），再逐周生成教学包。")
    return {
        "action": action, "workflow": workflow, "file_types": fts, "weeks": weeks,
        "target": target, "focus": focus, "tone": tone, "questions": questions,
        "reply": reply, "source": "rule",
    }


def _pending_weeks(planned: list, artifacts: list) -> list:
    """找出尚未全部定稿的已规划周次。"""
    by = {}
    for a in artifacts:
        by.setdefault(a["week_no"], set()).add(a["status"])
    out = []
    for w in planned:
        st = by.get(w, set())
        if st and st <= {"approved"}:
            continue
        out.append(w)
    return out


def _normalize(raw: dict, course: dict, planned: list, artifacts: list, text: str) -> dict:
    base = _rule_parse(text, course, planned, artifacts)
    out = dict(base)
    out["source"] = "llm"
    action = str(raw.get("action") or "").strip()
    if action in ("course_map", "generate", "revise", "ask"):
        out["action"] = action
    if out["action"] == "ask" and raw.get("workflow") in ("week_package", "single_file", "course_map"):
        out["action"] = "course_map" if raw["workflow"] == "course_map" else "generate"
    if raw.get("workflow") in ("week_package", "single_file", "course_map", "ask"):
        out["workflow"] = raw["workflow"]
    fts = [f for f in (raw.get("file_types") or []) if f in tools.FILE_TYPES]
    if fts:
        out["file_types"] = fts
    weeks = []
    for w in (raw.get("weeks") or []):
        try:
            w = int(w)
            if 1 <= w <= int(course.get("weeks") or 16):
                weeks.append(w)
        except Exception:
            pass
    if weeks:
        out["weeks"] = sorted(set(weeks))
    target = raw.get("target") or {}
    try:
        tw, tf = int(target.get("week")), str(target.get("file_type") or "")
        if tw and tf in tools.FILE_TYPES:
            out["target"] = {"week": tw, "file_type": tf}
    except Exception:
        pass
    if raw.get("focus"):
        out["focus"] = str(raw["focus"])[:80]
    if raw.get("tone"):
        out["tone"] = str(raw["tone"])[:40]
    if raw.get("reply"):
        out["reply"] = str(raw["reply"])[:300]
    if raw.get("questions"):
        out["questions"] = [str(q)[:120] for q in raw["questions"]][:3]
    return out


def parse(course_id: int, text: str) -> dict:
    course = store.get_course(course_id)
    if not course:
        return {"ok": False, "msg": "课程不存在"}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "msg": "请输入需求，例如「生成第 2-3 周教学包」"}

    planned = [p["week_no"] for p in store.list_week_plans(course_id)]
    artifacts = store.list_artifacts(course_id, with_content=False)
    history = "\n".join(f"{m['role']}：{(m['text'] or '')[:120]}"
                        for m in store.recent_messages(course_id, 6))
    store.add_message(course_id, "user", text)

    intent = None
    if config.MODE == "real":
        try:
            r = gateway.chat(prompts.intent_parse(text, course, planned, artifacts, history),
                             temperature=0.1, max_tokens=700, json_mode=True,
                             task="intent", file_type="intent", course_id=course_id)
            raw = _extract_json(r["text"])
            if raw:
                intent = _normalize(raw, course, planned, artifacts, text)
        except Exception:
            intent = None
    if intent is None:
        intent = _rule_parse(text, course, planned, artifacts)

    # 生成周次只能落在已规划周次内；地图未规划则转门 A
    if intent.get("action") == "generate":
        if not planned:
            intent["action"] = "course_map"
            intent["workflow"] = "course_map"
            intent["reply"] = "课程地图还未生成，先生成地图（门 A）供你确认。"
            intent["weeks"] = intent.get("weeks") or list(range(1, int(course["weeks"]) + 1))
        else:
            ok = sorted({w for w in (intent.get("weeks") or []) if w in planned})
            if not ok:
                ok = _pending_weeks(planned, artifacts) or list(planned)
            dropped = [w for w in (intent.get("weeks") or []) if w not in planned]
            intent["weeks"] = ok
            if dropped:
                intent["reply"] = (intent.get("reply") or "") + \
                    f"（第{'、'.join(map(str, dropped))}周尚未在课程地图中规划，已跳过）"
    if intent.get("action") == "course_map":
        intent["weeks"] = intent.get("weeks") or list(range(1, int(course["weeks"]) + 1))
        # 只生成已有周次范围
        intent["weeks"] = [w for w in intent["weeks"] if 1 <= w <= int(course["weeks"])]
    if intent.get("action") == "revise" and not intent.get("target"):
        intent["questions"] = intent.get("questions") or ["要修改哪一周、哪一份文件？"]
    intent["ok"] = True
    return intent
