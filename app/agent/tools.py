# -*- coding: utf-8 -*-
"""工具集：智能体可调用的「工具」（对应「文件级子任务管线」六步）。

生成工具统一流程：
  确保产物记录 → 状态 drafting → 取上下文与框架 → 调网关 → 规则校验
  →（可选）自动修复一次 → 状态 review（门 B）→ 记录修改历史。

所有生成内容均由大模型产出；校验器只提示与修复结构，不生成内容。
"""
import json
import re

from .. import store, rag, gateway, config, courseware
from . import prompts

FILE_TYPES = {
    "lesson_plan": {"cn": "教案", "deps": [], "stage": 1, "generator": "gen_lesson_plan"},
    "handout": {"cn": "讲义", "deps": ["lesson_plan"], "stage": 2, "generator": "gen_handout"},
    "courseware": {"cn": "课件", "deps": ["lesson_plan", "handout"], "stage": 3,
                   "generator": "gen_courseware"},
    "script": {"cn": "理论讲解逐字稿", "deps": ["lesson_plan", "handout"], "stage": 3,
               "generator": "gen_script"},
}
FILE_TYPE_CN = {k: v["cn"] for k, v in FILE_TYPES.items()}


def file_type_cn(ft: str) -> str:
    return FILE_TYPE_CN.get(ft, ft)


def deps_of(ft: str) -> list:
    return FILE_TYPES.get(ft, {}).get("deps", [])


# ================= 资料解析 =================
def parse_materials(course_id: int, force: bool = False) -> dict:
    """为每份资料生成摘要并原地更新（不重复插入资料）。"""
    mats = store.list_materials(course_id, with_content=True)
    if not mats:
        return {"ok": False, "msg": "请先上传资料"}
    done, fallback = 0, 0
    for m in mats:
        if m.get("summary") and not force:
            continue
        content = m.get("content") or ""
        try:
            r = gateway.chat(prompts.summary_gen(content), temperature=0.2, max_tokens=320,
                             task="summary", file_type="summary", course_id=course_id)
            summary = r["text"].strip()
            done += 1
        except Exception as e:  # 摘要失败不阻断：本地截取，并标明来源
            summary = "（本地摘要，模型调用失败）" + prompts.summary_prompt(content, 160)
            fallback += 1
            _ = e
        store.update_material_summary(m["id"], summary)
    n = len(store.list_materials(course_id))
    store.add_confirm_log(course_id, None, "parse", f"解析 {n} 份资料")
    msg = f"知识库就绪：{n} 份资料"
    if done:
        msg += f"，模型摘要 {done} 份"
    if fallback:
        msg += f"，本地摘要 {fallback} 份（模型暂不可用）"
    return {"ok": True, "msg": msg, "count": n}


# ================= 课程地图（门 A） =================
def _parse_json_array(text: str) -> list:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        data = json.loads(t)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("plans", "weeks", "data", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
    except Exception:
        pass
    start, end = t.find("["), t.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            pass
    raise ValueError("模型返回的不是合法 JSON 数组")


_GENERIC_TITLES = ("核心知识", "实践应用", "综合实训", "本章内容", "本课内容", "知识讲解",
                   "课程学习", "内容学习", "本周内容", "专题学习")


def _clean_plan_item(p: dict, course_weeks: int) -> dict | None:
    raw_week = p.get("week") or p.get("week_no") or 0
    m = re.search(r"\d+", str(raw_week))
    try:
        w = int(m.group(0)) if m else 0
    except Exception:
        return None
    title = str(p.get("title") or "").strip()
    if not (1 <= w <= max(1, course_weeks)) or not title or len(title) > 30:
        return None
    if any(t in title for t in _GENERIC_TITLES):
        # 允许模型用具体主题覆盖；仅当整句都是占位词时判为不合格
        if len(title) <= 10:
            return None
    try:
        hours = int(p.get("hours") or 2)
    except Exception:
        hours = 2
    hours = hours if hours in (2, 3, 4) else 2
    return {
        "week": w,
        "title": title,
        "hours": hours,
        "objective": str(p.get("objective") or "").strip()[:300],
        "ideo": str(p.get("ideo") or "").strip()[:300],
    }


def build_plan(course_id: int, weeks: list, focus: str = "", tone: str = "") -> dict:
    course = store.get_course(course_id)
    if not course:
        return {"ok": False, "msg": "课程不存在"}
    weeks = sorted({int(w) for w in weeks if str(w).isdigit() and 1 <= int(w) <= course["weeks"]})
    if not weeks:
        return {"ok": False, "msg": "请指定要规划的周次（1–%d）" % course["weeks"]}
    overview = rag.summarize_materials(course_id)
    msgs = prompts.week_plan_gen(course_id, course, weeks, focus, tone, overview)
    r = gateway.chat(msgs, temperature=0.35, max_tokens=min(8000, 900 + len(weeks) * 220),
                     json_mode=True, task="course_map", file_type="week_plan",
                     course_id=course_id)
    try:
        raw = _parse_json_array(r["text"])
    except Exception:
        return {"ok": False, "msg": "课程地图解析失败：模型未返回 JSON 数组，请重试"}
    plans = [p for p in (_clean_plan_item(x, course["weeks"]) for x in raw if isinstance(x, dict))
             if p]
    # 模型偶尔重复同一周：以第一次出现的为准
    dedup = {}
    for p in plans:
        dedup.setdefault(p["week"], p)
    plans = list(dedup.values())
    got = {p["week"] for p in plans}
    missing = [w for w in weeks if w not in got]
    if missing:
        msgs2 = prompts.week_plan_gen(course_id, course, missing, focus, tone, overview)
        r2 = gateway.chat(msgs2, temperature=0.35, max_tokens=min(8000, 900 + len(missing) * 220),
                          json_mode=True, task="course_map", file_type="week_plan",
                          course_id=course_id)
        try:
            raw2 = _parse_json_array(r2["text"])
            more = [p for p in (_clean_plan_item(x, course["weeks"]) for x in raw2 if isinstance(x, dict))
                    if p and p["week"] in missing]
            plans += more
        except Exception:
            more = []
        still = sorted(set(missing) - {p["week"] for p in plans})
        if still:
            return {"ok": False,
                    "msg": f"模型未返回完整规划（缺第{'、'.join(map(str, still))}周），请重试或减少周次"}
    # 合并已有规划：未涉及的周次保留
    existing = {p["week_no"]: p for p in store.list_week_plans(course_id)}
    for p in plans:
        p["status"] = "review"
    merged = []
    for w in sorted(set(existing) | {p["week"] for p in plans}):
        if w in {p["week"] for p in plans}:
            merged.append(next(p for p in plans if p["week"] == w))
        else:
            e = existing[w]
            merged.append({"week": w, "title": e["title"], "hours": e["hours"],
                           "objective": e["objective"], "ideo": e["ideo"],
                           "status": e["status"]})
    store.save_week_plans(course_id, merged)
    store.add_confirm_log(course_id, None, "build_plan",
                          f"生成第{'、'.join(map(str, sorted({p['week'] for p in plans})))}周课程地图")
    return {"ok": True,
            "msg": f"课程地图已生成（{len(plans)} 周），请核对后批准（门 A）",
            "plans": store.list_week_plans(course_id)}


def regenerate_week(course_id: int, week_no: int, focus: str = "") -> dict:
    """只重写某一周的主题/目标/思政点。"""
    course = store.get_course(course_id)
    week = store.get_week_plan(course_id, week_no)
    if not course or not week:
        return {"ok": False, "msg": "课程或周次不存在"}
    msgs = prompts.week_retitle_prompt(course, week, focus)
    r = gateway.chat(msgs, temperature=0.4, max_tokens=600, json_mode=True,
                     task="course_map", file_type="week_plan", course_id=course_id,
                     week_no=week_no)
    try:
        raw = _parse_json_array(r["text"])
    except Exception:
        return {"ok": False, "msg": "重写失败：模型返回格式异常，请重试"}
    item = _clean_plan_item(raw[0], course["weeks"]) if raw and isinstance(raw[0], dict) else None
    if not item:
        return {"ok": False, "msg": "重写结果不合格，请换个说法重试"}
    store.update_week_plan(course_id, week_no, title=item["title"], hours=item["hours"],
                           objective=item["objective"], ideo=item["ideo"], status="review")
    store.add_confirm_log(course_id, None, "retitle", f"第{week_no}周：{item['title']}")
    return {"ok": True, "msg": f"第 {week_no} 周已重写", "week": store.get_week_plan(course_id, week_no)}


def update_week_plan(course_id: int, week_no: int, **fields) -> dict:
    ok = store.update_week_plan(course_id, week_no, **fields)
    if ok:
        store.add_confirm_log(course_id, None, "edit_plan", f"第{week_no}周")
        return {"ok": True, "msg": f"第 {week_no} 周已保存",
                "week": store.get_week_plan(course_id, week_no)}
    return {"ok": False, "msg": "保存失败：周次不存在"}


def approve_plan(course_id: int, weeks=None) -> dict:
    if weeks:
        weeks = [int(w) for w in weeks]
    store.approve_week_plans(course_id, weeks)
    store.add_confirm_log(course_id, None, "approve_plan",
                          f"批准{'第' + '、'.join(map(str, weeks)) + '周' if weeks else '全部'}课程地图")
    return {"ok": True, "msg": "课程地图已批准（门 A）"}


# ================= 生成依赖 =================
def _fetch_week(course_id: int, week_no: int) -> dict:
    p = store.get_week_plan(course_id, week_no)
    if p:
        return p
    return {"week_no": week_no, "title": f"第{week_no}周", "hours": 2,
            "objective": "", "ideo": ""}


def dependencies_ready(course_id: int, week_no: int, file_type: str) -> tuple:
    """返回 (是否就绪, 未批准依赖名称列表)。"""
    missing = []
    for dep in deps_of(file_type):
        a = store.ensure_artifact(course_id, week_no, dep)
        if a["status"] != "approved" or not a.get("content"):
            missing.append(file_type_cn(dep))
    return (not missing, missing)


def _ensure_drafting(course_id, week_no, file_type):
    a = store.ensure_artifact(course_id, week_no, file_type)
    store.set_artifact(a["id"], status="drafting",
                       title=f"第{week_no}周 {file_type_cn(file_type)}")
    return a["id"]


def _merge_r(a: dict, b: dict) -> dict:
    return {
        "text": b["text"],
        "model": b["model"],
        "tokens": {"in": a["tokens"]["in"] + b["tokens"]["in"],
                   "out": a["tokens"]["out"] + b["tokens"]["out"]},
        "cost": a["cost"] + b["cost"],
        "latency_ms": a.get("latency_ms", 0) + b.get("latency_ms", 0),
        "trace_id": f"{a.get('trace_id','')}+{b.get('trace_id','')}",
    }


def _finalize(aid: int, course: dict, week: dict, file_type: str, text: str,
              r: dict, source: str = "generate") -> dict:
    """校验 → 可选自动修复 → 写库（review）→ 记录版本。"""
    text = (text or "").strip()
    if len(text) < 80:
        raise RuntimeError("模型输出过短，已终止本次生成")
    issues = validate_text(file_type, text, week.get("hours", 2))
    repaired = False
    if issues and config.AUTO_REPAIR:
        try:
            r2 = gateway.chat(prompts.repair_prompt(
                {"file_type": file_type, "content": text}, "；".join(issues), course, week),
                temperature=0.2, max_tokens=5000, task="repair",
                file_type=file_type, course_id=course["id"], week_no=week["week_no"])
            issues2 = validate_text(file_type, r2["text"], week.get("hours", 2))
            # 只有确实减少问题且篇幅没有大幅缩水才采用修复稿
            if len(issues2) < len(issues) and len(r2["text"]) > len(text) * 0.65:
                text, issues, repaired = r2["text"].strip(), issues2, True
                r = _merge_r(r, r2)
                source = "repair"
        except Exception:
            pass
    store.set_artifact(aid, status="review", content=text, model=r["model"],
                       tokens=r["tokens"], cost=r["cost"], latency_ms=r.get("latency_ms", 0),
                       feedback="", warnings="；".join(issues),
                       word_count=len(text), task_id="")
    store.save_revision(aid, text, feedback="", source=source, model=r["model"])
    store.add_confirm_log(course["id"], aid, source,
                          f"第{week['week_no']}周{file_type_cn(file_type)}" +
                          ("（自动修复）" if repaired else ""))
    msg = f"第 {week['week_no']} 周{file_type_cn(file_type)}初稿完成"
    if repaired:
        msg += "（已自动修复结构）"
    if issues:
        msg += f"，仍有 {len(issues)} 项校验提示"
    return {"ok": True, "artifact_id": aid, "msg": msg, "warnings": issues,
            "tokens": r["tokens"], "cost": r["cost"], "model": r["model"]}


def _with_failure(aid, course_id, week_no, file_type, fn, *args, **kwargs):
    try:
        return fn(aid, *args, **kwargs)
    except Exception:
        store.set_artifact(aid, status="failed", feedback="生成失败，可重试")
        store.add_confirm_log(course_id, aid, "failed",
                              f"第{week_no}周{file_type_cn(file_type)}")
        raise


# ================= 教案 =================
def gen_lesson_plan(course_id: int, week_no: int, prev_summary: str = "",
                    focus: str = "", tone: str = "") -> dict:
    course = store.get_course(course_id)
    week = _fetch_week(course_id, week_no)
    aid = _ensure_drafting(course_id, week_no, "lesson_plan")

    def run(artifact_id, *args, **kwargs):
        msgs = prompts.lesson_plan_gen(course_id, course, week, prev_summary, focus, tone)
        r = gateway.chat(msgs, temperature=0.55, max_tokens=4800,
                         task="lesson_plan", file_type="lesson_plan",
                         course_id=course_id, week_no=week_no)
        return _finalize(artifact_id, course, week, "lesson_plan", r["text"], r)

    return _with_failure(aid, course_id, week_no, "lesson_plan", run)


# ================= 讲义 =================
def gen_handout(course_id: int, week_no: int, focus: str = "", tone: str = "") -> dict:
    plan = store.ensure_artifact(course_id, week_no, "lesson_plan")
    ok, missing = dependencies_ready(course_id, week_no, "handout")
    if not ok or not plan.get("content"):
        return {"ok": False, "msg": f"讲义依赖{'、'.join(missing) or '教案'}，请先批准教案"}
    course = store.get_course(course_id)
    week = _fetch_week(course_id, week_no)
    aid = _ensure_drafting(course_id, week_no, "handout")

    def run(artifact_id, *args, **kwargs):
        msgs = prompts.handout_gen(course_id, course, week, plan["content"], focus, tone)
        r = gateway.chat(msgs, temperature=0.55, max_tokens=6000,
                         task="handout", file_type="handout",
                         course_id=course_id, week_no=week_no)
        return _finalize(artifact_id, course, week, "handout", r["text"], r)

    return _with_failure(aid, course_id, week_no, "handout", run)


# ================= 互动课件（PPT + HTML 共用一份 JSON） =================
def gen_courseware(course_id: int, week_no: int, focus: str = "", tone: str = "") -> dict:
    plan = store.ensure_artifact(course_id, week_no, "lesson_plan")
    handout = store.ensure_artifact(course_id, week_no, "handout")
    ok, missing = dependencies_ready(course_id, week_no, "courseware")
    if not ok or not plan.get("content") or not handout.get("content"):
        return {"ok": False, "msg": f"课件依赖{'、'.join(missing) or '教案与讲义'}，请先批准"}
    course = store.get_course(course_id)
    week = _fetch_week(course_id, week_no)
    aid = _ensure_drafting(course_id, week_no, "courseware")

    def run(artifact_id, *args, **kwargs):
        msgs = prompts.courseware_gen(course_id, course, week, plan["content"],
                                      handout["content"], focus, tone)
        r = gateway.chat(msgs, temperature=0.55, max_tokens=5200,
                         task="courseware", file_type="courseware",
                         course_id=course_id, week_no=week_no)
        return _finalize(artifact_id, course, week, "courseware", r["text"], r)

    return _with_failure(aid, course_id, week_no, "courseware", run)


# ================= 逐字稿（分两段） =================
def gen_script(course_id: int, week_no: int, focus: str = "", tone: str = "") -> dict:
    plan = store.ensure_artifact(course_id, week_no, "lesson_plan")
    handout = store.ensure_artifact(course_id, week_no, "handout")
    ok, missing = dependencies_ready(course_id, week_no, "script")
    if not ok or not plan.get("content") or not handout.get("content"):
        return {"ok": False, "msg": f"逐字稿依赖{'、'.join(missing) or '教案与讲义'}，请先批准"}
    course = store.get_course(course_id)
    week = _fetch_week(course_id, week_no)
    aid = _ensure_drafting(course_id, week_no, "script")

    def run(artifact_id, *args, **kwargs):
        p1 = gateway.chat(prompts.script_gen_part(course_id, course, week, plan["content"],
                                                  handout["content"], 1, focus=focus, tone=tone),
                          temperature=0.65, max_tokens=6000, task="script",
                          file_type="script", course_id=course_id, week_no=week_no)
        p2 = gateway.chat(prompts.script_gen_part(course_id, course, week, plan["content"],
                                                  handout["content"], 2, p1["text"],
                                                  focus=focus, tone=tone),
                          temperature=0.65, max_tokens=6000, task="script",
                          file_type="script", course_id=course_id, week_no=week_no)
        full = p1["text"].strip() + "\n\n---\n\n" + p2["text"].strip()
        merged = _merge_r(p1, p2)
        merged["text"] = full
        return _finalize(artifact_id, course, week, "script", full, merged)

    return _with_failure(aid, course_id, week_no, "script", run)


# ================= 修订 / 确认 =================
def revise_artifact(artifact_id: int, feedback: str, focus: str = "") -> dict:
    a = store.get_artifact(artifact_id)
    if not a:
        return {"ok": False, "msg": "产物不存在"}
    content = a.get("content") or ""
    store.save_revision(artifact_id, content, feedback=feedback, source="before_revise",
                        model=a.get("model", ""))
    store.set_artifact(artifact_id, status="revising", feedback=feedback)
    course = store.get_course(a["course_id"])
    week = _fetch_week(a["course_id"], a["week_no"])
    try:
        msgs = prompts.revise_prompt(a, feedback, course, week, a["course_id"], focus)
        r = gateway.chat(msgs, temperature=0.45, max_tokens=6000,
                         task="revise", file_type=a["file_type"],
                         course_id=a["course_id"], week_no=a["week_no"])
        issues = validate_text(a["file_type"], r["text"], week.get("hours", 2))
        if issues and config.AUTO_REPAIR:
            try:
                r2 = gateway.chat(prompts.repair_prompt(
                    {"file_type": a["file_type"], "content": r["text"]},
                    "；".join(issues), course, week),
                    temperature=0.2, max_tokens=5000, task="repair",
                    file_type=a["file_type"], course_id=a["course_id"], week_no=a["week_no"])
                issues2 = validate_text(a["file_type"], r2["text"], week.get("hours", 2))
                if len(issues2) < len(issues) and len(r2["text"]) > len(r["text"]) * 0.65:
                    r = _merge_r(r, r2)
                    issues = issues2
            except Exception:
                pass
        store.set_artifact(artifact_id, status="review", content=r["text"], model=r["model"],
                           tokens=r["tokens"], cost=r["cost"], latency_ms=r.get("latency_ms", 0),
                           feedback="", warnings="；".join(issues), word_count=len(r["text"]))
        store.save_revision(artifact_id, r["text"], feedback=feedback, source="revise",
                            model=r["model"])
        store.add_confirm_log(a["course_id"], artifact_id, "revise", feedback)
        return {"ok": True, "artifact_id": artifact_id,
                "msg": "已按要求重新生成，请再次确认", "warnings": issues}
    except Exception as e:
        store.set_artifact(artifact_id, status="review", feedback=str(e)[:400])
        store.add_confirm_log(a["course_id"], artifact_id, "revise_failed", str(e)[:300])
        return {"ok": False, "msg": f"修改失败：{e}"}


def approve_artifact(artifact_id: int) -> dict:
    a = store.get_artifact(artifact_id)
    if not a:
        return {"ok": False, "msg": "产物不存在"}
    if not (a.get("content") or "").strip():
        return {"ok": False, "msg": "内容为空，不能批准"}
    store.set_artifact(artifact_id, status="approved", feedback="")
    store.add_confirm_log(a["course_id"], artifact_id, "approve", "")
    return {"ok": True, "msg": "已批准定稿", "artifact": store.get_artifact(artifact_id)}


def reopen_artifact(artifact_id: int, reason: str = "退回修改") -> dict:
    a = store.get_artifact(artifact_id)
    if not a:
        return {"ok": False, "msg": "产物不存在"}
    store.set_artifact(artifact_id, status="review", feedback="")
    store.add_confirm_log(a["course_id"], artifact_id, "reopen", reason)
    return {"ok": True, "msg": "已退回确认中心"}


def reset_artifact(artifact_id: int, reason: str = "重新生成") -> dict:
    a = store.get_artifact(artifact_id)
    if not a:
        return {"ok": False, "msg": "产物不存在"}
    store.reset_artifact(artifact_id, reason)
    store.add_confirm_log(a["course_id"], artifact_id, "reset", reason)
    return {"ok": True, "msg": "已清空，等待重新生成"}


# ================= 质量校验 =================
_CLICHE = (
    "讲授本课核心概念", "用直观案例引出主题", "建立系统认知", "激发学生兴趣",
    "学生分组讨论", "掌握核心知识并能结合案例实际运用", "提高学生综合素质",
    "为今后的学习打下坚实基础", "做到学以致用",
)
_PLACEHOLDER = ("（待补）", "（待填写）", "待补充完整", "……（略）", "XXX", "xxxx")


def _table_rows(text: str, header_kw: str) -> list:
    """粗取某张表的数据行（含表头之后到空行为止）。"""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if header_kw in line and line.strip().startswith("|"):
            rows = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(lines[j])
                j += 1
            return rows
    return []


def _minutes_in(text: str) -> int:
    vals = [int(x) for x in re.findall(r"(\d{1,3})\s*分钟", text)]
    return sum(vals)


def validate_text(file_type: str, content: str, hours: int = 2) -> list:
    """返回问题列表（空列表=通过）。只提示，不阻断人工确认。"""
    t = content or ""
    issues = []
    if not t.strip():
        return ["内容为空"]
    if any(p in t for p in _PLACEHOLDER):
        issues.append("存在占位符（待补/待填写/XXX），需要补全")
    if "教学基本信息" not in t and file_type == "lesson_plan":
        issues.append("缺少「教学基本信息」表")
    if file_type == "lesson_plan":
        need = ["课题", "班级", "课时安排", "教材", "课程类型", "授课地点", "教学目标",
                "教学重难点", "学情分析", "教学方法", "教学资源", "教学反思"]
        missing = [k for k in need if k not in t]
        if missing:
            issues.append("表一缺少栏目：" + "、".join(missing))
        if "教学过程" not in t:
            issues.append("缺少「教学过程」表")
        for col in ("教学环节", "教学内容", "教师活动", "学生活动", "设计意图"):
            if col not in t:
                issues.append(f"教学过程表缺少「{col}」列")
                break
        if "一句话思政核心" not in t and "思政核心" not in t:
            issues.append("缺少「一句话思政核心」段落")
        rows = _table_rows(t, "教学环节")
        stage_rows = [r for r in rows if not re.match(r"^\|\s*[-: ]+\|", r.strip())]
        stage_rows = [r for r in stage_rows if "教学环节" not in r]
        n_stage = len(stage_rows)
        if n_stage < 3:
            issues.append(f"教学过程环节过少（{n_stage} 行），应为 4–6 个环节")
        elif n_stage > 6:
            issues.append(f"教学过程环节过多（{n_stage} 行），应为 4–6 个环节")
        mins = _minutes_in("\n".join(stage_rows))
        expect = int(hours or 2) * 45
        if mins == 0:
            issues.append("教学环节未标注时间（如「一、课程导入（10分钟）」）")
        elif mins != expect:
            issues.append(f"环节时间合计 {mins} 分钟，与 {hours} 学时×45={expect} 分钟不一致")
        if len(t) < 1000:
            issues.append(f"教案正文偏短（{len(t)} 字，建议 1200–2200 字）")
        hit = [w for w in _CLICHE if w in t]
        if hit:
            issues.append("检测到模板化套话：" + "、".join(hit[:3]) + "，请改写为具体内容")
    elif file_type == "handout":
        if len(t) < 1600:
            issues.append(f"讲义偏短（{len(t)} 字，建议 2000–3500 字）")
        headings = re.findall(r"^##\s+(.+)$", t, re.M)
        if len(headings) < 4:
            issues.append(f"讲义模块过少（{len(headings)} 个），应与教案环节一一对应")
        for kw in ("导入", "小结", "作业"):
            if kw not in t:
                issues.append(f"讲义缺少「{kw}」相关内容")
        if t.count("？") < 3:
            issues.append("讲义缺少课堂提问（建议至少 3 个追问）")
        if t.count("|") > 6:
            issues.append("讲义使用了较多表格，应改为可照念的讲解正文")
        hit = [w for w in _CLICHE if w in t]
        if hit:
            issues.append("检测到模板化套话：" + "、".join(hit[:3]))
    elif file_type == "courseware":
        issues.extend(courseware.validate_deck(t))
    elif file_type == "script":
        if len(t) < 2500:
            issues.append(f"逐字稿偏短（{len(t)} 字，建议 3000–5000 字）")
        if t.count("（") < 6:
            issues.append("逐字稿缺少舞台指示（如（播放案例）（停顿 3 秒））")
        headings = re.findall(r"^##\s+(.+)$", t, re.M)
        if len(headings) < 4:
            issues.append("逐字稿分节过少，应按课堂时间顺序分节")
        if not any(k in t for k in ("同学们", "大家", "各位")):
            issues.append("逐字稿缺少面向学生的直接称呼，可照念性不足")
        hit = [w for w in _CLICHE if w in t]
        if hit:
            issues.append("检测到模板化套话：" + "、".join(hit[:3]))
    # 通用：重复句检测（课件是结构化 JSON，不按正文句重复判断）
    if file_type != "courseware":
        sents = [s.strip() for s in re.split(r"[。！？\n]", t) if len(s.strip()) >= 18]
        if sents:
            from collections import Counter
            dup = [s for s, n in Counter(sents).items() if n >= 3]
            if dup:
                issues.append("存在重复句（内容可能注水），如：" + dup[0][:30])
    return issues


def validate_artifact(a: dict) -> tuple:
    """兼容旧接口：返回 (是否通过, 提示文本)。"""
    hours = 2
    try:
        week = store.get_week_plan(a["course_id"], a["week_no"]) or {}
        hours = week.get("hours", 2)
    except Exception:
        pass
    issues = validate_text(a.get("file_type"), a.get("content") or "", hours)
    return (not issues, "；".join(issues))
