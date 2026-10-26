# -*- coding: utf-8 -*-
"""提示词装配层（v2）。

不再把长提示词硬编码在函数里，而是：
  frameworks.py  提供 8 要素框架（角色/任务/规范/结构/深度/风格/格式/校验）；
  rag.assemble_context 提供「公共资源 → 课程原文 → 本次需求」的上下文；
  本文件只负责把两者组装成 OpenAI 兼容的 messages。

这样可保证：每一类文件都按同一套质量底线生成，且新增文件类型不需要改提示词逻辑。
"""
from .. import config, rag, frameworks

FILE_TYPE_CN = {
    "lesson_plan": "教案",
    "handout": "讲义",
    "courseware": "互动课件",
    "script": "理论讲解逐字稿",
    "week_plan": "课程地图",
    "summary": "周间摘要",
    "intent": "意图",
}


def _base(course: dict) -> dict:
    return {
        "course": course.get("name") or "",
        "school": config.SCHOOL_NAME,
        "semester": course.get("semester") or "",
        "class_name": course.get("class_name") or "（按课程资料填写）",
        "textbook": course.get("textbook") or "（按课程资料填写）",
    }


def _week_mapping(course: dict, week: dict, **extra) -> dict:
    hours = int(week.get("hours") or 2)
    m = _base(course)
    m.update({
        "week": week.get("week_no") or week.get("week") or "",
        "title": week.get("title") or "",
        "hours": hours,
        "minutes": hours * 45,
        "objective": week.get("objective") or "",
        "ideo": week.get("ideo") or "",
    })
    m.update(extra)
    return m


# ================= 对话总控 =================
def intent_parse(user_text: str, course: dict, planned_weeks: list,
                 artifacts: list, history: str) -> list:
    mapping = _base(course)
    mapping.update({
        "week": "", "title": "", "hours": course.get("weeks") or 16,
        "minutes": "", "focus": "", "tone": "",
    })
    planned = "、".join(f"第{w}周" for w in planned_weeks) or "（尚未生成课程地图）"
    art_lines = []
    for a in artifacts:
        art_lines.append(f"第{a['week_no']}周 {FILE_TYPE_CN.get(a['file_type'], a['file_type'])}：{a['status']}")
    art_text = "；".join(art_lines) or "（尚无产物）"
    system = frameworks.system_prompt("intent_mapper", mapping)
    user = (
        f"课程：{course['name']}（{course.get('semester','')}，共 {course.get('weeks',16)} 周）\n"
        f"班级：{course.get('class_name') or '未设置'}；教材：{course.get('textbook') or '未设置'}\n"
        f"课程主题/要求：{course.get('theme') or '无'}\n"
        f"已规划周次：{planned}\n产物状态：{art_text}\n"
        f"最近对话：\n{history or '（无）'}\n\n"
        f"教师本次说：{user_text}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 课程地图（门 A） =================
def week_plan_gen(course_id: int, course: dict, weeks: list, focus: str = "",
                  tone: str = "", overview: str = "") -> list:
    mapping = _base(course)
    mapping.update({"week": "", "title": "", "hours": "", "minutes": "",
                    "focus": focus, "tone": tone})
    system = frameworks.system_prompt("course_map", mapping,
                                      extra=f"本次需要生成/补全的周次：{weeks}。")
    query = f"{course.get('name','')} {course.get('theme','')} 教学计划 周次 主题 {' '.join(map(str, weeks))}"
    context = rag.assemble_context(course_id, query, focus, tone)
    user = (
        f"课程名称：{course['name']}；学期：{course.get('semester','')}；"
        f"总周数：{course.get('weeks',16)}；班级：{course.get('class_name') or '未设置'}\n"
        f"课程主题/要求：{course.get('theme') or '无'}\n"
        f"需要输出的周次：{weeks}（必须全部输出，不得遗漏或重复）\n\n"
        f"{context}\n\n资料概览：\n{overview}\n\n"
        "请只输出 JSON 数组。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 教案 =================
def lesson_plan_gen(course_id: int, course: dict, week: dict, prev_summary: str = "",
                    focus: str = "", tone: str = "") -> list:
    mapping = _week_mapping(course, week, focus=focus, tone=tone,
                            prev_summary=prev_summary)
    extra = ""
    if prev_summary:
        extra = ("本周与上周衔接：在「一、课程导入」中先用一句话回顾上周核心内容，"
                 f"再自然过渡到本周。上周摘要：{prev_summary}")
    if focus:
        extra += f"\n本次侧重点：{focus}。"
    if tone:
        extra += f"\n语言风格：{tone}。"
    system = frameworks.system_prompt("lesson_plan", mapping, extra=extra)
    query = f"{course['name']} {week.get('title','')} {week.get('objective','')} {focus}"
    context = rag.assemble_context(course_id, query, focus, tone)
    user = (
        f"课程：{course['name']}（{course.get('semester','')}）\n"
        f"第 {week['week_no']} 周 主题：{week.get('title')}（{week.get('hours',2)} 学时）\n"
        f"周目标：{week.get('objective') or '（未填写）'}\n"
        f"本周思政核心：{week.get('ideo') or '（未填写，请结合内容提炼）'}\n"
        f"班级：{course.get('class_name') or '未设置'}；教材：{course.get('textbook') or '未设置'}\n\n"
        f"{context}\n\n请直接输出完整教案。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 讲义 =================
def handout_gen(course_id: int, course: dict, week: dict, lesson_plan: str,
                focus: str = "", tone: str = "") -> list:
    mapping = _week_mapping(course, week, focus=focus, tone=tone)
    extra = ""
    if focus:
        extra = f"本次侧重点：{focus}；语言风格：{tone or '课堂口语'}。"
    system = frameworks.system_prompt("handout", mapping, extra=extra)
    query = f"{week.get('title','')} {focus} 讲解 案例 练习"
    context = rag.assemble_context(course_id, query, focus, tone)
    user = (
        f"课程：{course['name']}；第 {week['week_no']} 周 主题：{week.get('title')}\n"
        f"本周教案（必须逐环节对应）：\n{lesson_plan[:7000]}\n\n"
        f"{context}\n\n请输出完整讲义正文。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 互动课件（PPT / HTML 共用 JSON） =================
def courseware_gen(course_id: int, course: dict, week: dict, lesson_plan: str,
                   handout: str, focus: str = "", tone: str = "") -> list:
    mapping = _week_mapping(course, week, focus=focus, tone=tone)
    extra = ""
    if focus:
        extra = f"本次侧重点：{focus}；语言风格：{tone or '课堂口语'}。"
    system = frameworks.system_prompt("courseware", mapping, extra=extra)
    query = f"{week.get('title','')} 互动课件 PPT 幻灯片 课堂活动 {focus}"
    context = rag.assemble_context(course_id, query, focus, tone)
    user = (
        f"课程：{course['name']}；第 {week['week_no']} 周 主题：{week.get('title')}\n"
        f"课时：{week.get('hours',2)} 学时（{int(week.get('hours',2))*45} 分钟）\n"
        f"周目标：{week.get('objective') or '（未填写）'}\n"
        f"思政点：{week.get('ideo') or '（未填写）'}\n\n"
        f"本周教案（课件必须与教学环节对应）：\n{lesson_plan[:6500]}\n\n"
        f"本周讲义（提取课堂讲解重点与互动问题）：\n{handout[:4500]}\n\n"
        f"{context}\n\n"
        "请只输出课件 JSON 对象，不要 Markdown 代码围栏，不要解释文字。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 逐字稿 =================
def script_gen_part(course_id: int, course: dict, week: dict, lesson_plan: str,
                    handout: str, part: int, prev_tail: str = "",
                    focus: str = "", tone: str = "") -> list:
    part_label = "第一部分（开场、衔接、导入与核心讲解前半）" if part == 1 else \
        "第二部分（核心讲解后半、互动、实训、小结与作业）"
    mapping = _week_mapping(course, week, focus=focus, tone=tone,
                            part_label=part_label)
    system = frameworks.system_prompt("script", mapping,
                                      extra=f"本次只写{part_label}，约 2000–2500 字。")
    query = f"{week.get('title','')} 逐字稿 讲授 {focus}"
    context = rag.assemble_context(course_id, query, focus, tone)
    tail = ("\n\n第一部分结尾（请自然承接，不要重复）：\n" + prev_tail[-900:]) if prev_tail else ""
    user = (
        f"课程：{course['name']}；第 {week['week_no']} 周 主题：{week.get('title')}\n"
        f"教案：\n{lesson_plan[:4500]}\n\n讲义要点：\n{handout[:3500]}\n\n"
        f"{context}{tail}\n\n请直接输出{part_label}的逐字稿。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 周间记忆 =================
def summary_gen(text: str, max_len: int = 180) -> list:
    mapping = {"max_len": max_len, "course": "", "school": config.SCHOOL_NAME,
               "semester": "", "class_name": "", "textbook": "", "week": "",
               "title": "", "hours": "", "minutes": "", "focus": "", "tone": ""}
    system = frameworks.system_prompt("summary", mapping)
    return [{"role": "system", "content": system},
            {"role": "user", "content": (text or "")[:8000]}]


def summary_prompt(text: str, max_len: int = 180) -> str:
    """本地截断兜底（仅当摘要模型调用失败时使用，不冒充生成）。"""
    t = " ".join((text or "").split())
    return t[:max_len] + ("…" if len(t) > max_len else "")


# ================= 文件修改 =================
def revise_prompt(artifact: dict, feedback: str, course: dict, week: dict,
                  course_id: int, focus: str = "") -> list:
    file_cn = FILE_TYPE_CN.get(artifact.get("file_type"), artifact.get("file_type"))
    mapping = _week_mapping(course, week, file_type_cn=file_cn, focus=focus,
                            tone="")
    if artifact.get("file_type") == "courseware":
        system = frameworks.system_prompt(
            "courseware", mapping,
            extra=(f"这是对已有课件的修改。教师反馈：{feedback}。"
                   "只修改要求涉及的内容，保持 slides 字段结构与页数基本不变，"
                   "输出完整 JSON 对象，不要输出 JSON 之外的文字。"))
    else:
        system = frameworks.system_prompt("file_reviser", mapping,
                                          extra=f"教师反馈：{feedback}")
    query = f"{week.get('title','')} {feedback} 修订"
    context = rag.assemble_context(course_id, query, focus, "")
    user = (
        f"文件类型：{file_cn}\n课程：{course['name']}；第 {week.get('week_no','')} 周 "
        f"主题：{week.get('title','')}\n\n"
        f"原文件（完整）：\n{artifact.get('content','')[:14000]}\n\n"
        f"教师修改要求：{feedback}\n\n"
        f"{context}\n\n"
        "请输出修改后的完整文件，保留原有结构与栏目；不要输出修改说明。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 结构修复（校验不通过时自动跑一次） =================
def repair_prompt(artifact: dict, issues: str, course: dict, week: dict) -> list:
    """自动修复模式：只修结构/缺失项，不重写内容与案例。"""
    file_cn = FILE_TYPE_CN.get(artifact.get("file_type"), artifact.get("file_type"))
    base = _week_mapping(course, week)
    fid = {"lesson_plan": "lesson_plan", "handout": "handout",
           "courseware": "courseware",
           "script": "script"}.get(artifact.get("file_type"), "file_reviser")
    base["file_type_cn"] = file_cn
    spec = frameworks.system_prompt(fid, base)
    system = (
        "你是备课文件的格式修复助手。下面给出该文件类型的生成规范与「校验问题清单」。\n"
        "你的任务：在原文件基础上修复问题清单中的每一项，保持原有内容、案例、教学设计不变；\n"
        "只补充缺失栏目/列、修正时间合计、替换模板化套话，不要重写整篇文章，不要输出修改说明。\n\n"
        + spec)
    user = (
        f"文件类型：{file_cn}\n课程：{course['name']}；第 {week.get('week_no','')} 周 "
        f"主题：{week.get('title','')}；学时：{week.get('hours',2)}\n\n"
        f"原文件：\n{artifact.get('content','')[:16000]}\n\n"
        f"校验问题清单（必须逐条修复）：\n{issues}\n\n"
        "请输出修复后的完整文件。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ================= 周次主题局部重写 =================
def week_retitle_prompt(course: dict, week: dict, focus: str = "") -> list:
    mapping = _base(course)
    mapping.update({"week": week.get("week_no"), "title": week.get("title"),
                    "hours": week.get("hours"), "minutes": "", "focus": focus,
                    "tone": ""})
    system = frameworks.system_prompt("course_map", mapping,
                                      extra=f"只重写第 {week.get('week_no')} 周这一周。")
    user = (
        f"课程：{course['name']}；主题要求：{course.get('theme') or '无'}\n"
        f"第 {week.get('week_no')} 周现有主题：{week.get('title')}；学时：{week.get('hours')}\n"
        f"本次侧重：{focus or '让主题更具体、更贴合资料'}\n"
        "请只输出包含这一周的 JSON 数组（1 个元素）。")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
