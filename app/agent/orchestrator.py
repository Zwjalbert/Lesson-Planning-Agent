# -*- coding: utf-8 -*-
"""编排层：备课主智能体 / 工作流引擎（v2）。

三层实现，对应「豆包工作模式装进固定外壳」：
  1. 对话总控：intent.py 把自然语言解析成结构化任务；
  2. 技能路由：SKILLS 注册表把任务路由到「框架 + 大模型 + 校验 + 确认门」；
  3. 依赖链与周间记忆：教案 →(批准)→ 讲义 →(批准)→ 逐字稿；上周摘要注入下周。

v2 新增：
  - 后台任务持久化（重启后状态可追溯、不会假运行）；
  - 进度按「本轮要处理的文件数」计算，跳过项也会说明原因；
  - 门 B 批准后按课程设置自动续跑下游（auto_chain）；
  - 可取消；
  - 对话总控可直接执行（生成地图 / 启动生成 / 修改单文件）。
"""
import threading
import time

from .. import store, gateway, config
from . import tools, prompts, intent

# ================= 技能注册表 =================
# 技能 = 框架 + 工具 + 校验 + 确认门
SKILLS = [
    {"name": "材料读取", "fn": "parse_materials", "framework": "", "gate": "",
     "desc": "解析 txt/md/csv/docx/xlsx/pdf 资料并生成摘要，构建课程知识库"},
    {"name": "需求映射", "fn": "parse_intent", "framework": "intent_mapper", "gate": "",
     "desc": "把教师一句话映射为结构化任务（周次/文件类型/侧重点/语气）"},
    {"name": "课程地图", "fn": "build_plan", "framework": "course_map", "gate": "A",
     "desc": "按资料生成逐周规划（主题/学时/目标/思政点），人工确认后放行"},
    {"name": "教案撰写", "fn": "gen_lesson_plan", "framework": "lesson_plan", "gate": "B",
     "desc": "横版双表教案：表一 12 栏目、表二 5 列、环节时间合计=学时×45"},
    {"name": "讲义撰写", "fn": "gen_handout", "framework": "handout", "gate": "B",
     "desc": "与教案环节对应的模块化讲解正文，可直接照念"},
    {"name": "课件制作", "fn": "gen_courseware", "framework": "courseware", "gate": "B",
     "desc": "生成结构化互动课件，同时导出 16:9 PPTX 与自包含互动 HTML"},
    {"name": "逐字稿撰写", "fn": "gen_script", "framework": "script", "gate": "B",
     "desc": "含教师话语与舞台指示的分段逐字稿"},
    {"name": "周间记忆", "fn": "summary_gen", "framework": "summary", "gate": "",
     "desc": "上周教案摘要注入下周，保证课程连续性"},
    {"name": "质量校验", "fn": "validate_artifact", "framework": "", "gate": "B",
     "desc": "检查栏目/列/时间合计/套话/重复句，不合格自动修复一次"},
    {"name": "文件修改", "fn": "revise_artifact", "framework": "file_reviser", "gate": "B",
     "desc": "按教师反馈输出完整新版，保留结构与栏目，支持多轮与版本回退"},
    {"name": "打包导出", "fn": "package_course", "framework": "", "gate": "C",
     "desc": "docx / PPTX / 互动 HTML / Markdown 渲染，按周归档并打包 zip"},
]

SKILL_MAP = {s["fn"]: s for s in SKILLS}
_FILE_ORDER = ["lesson_plan", "handout", "courseware", "script"]


def skill_of(name: str) -> dict:
    for s in SKILLS:
        if s["name"] == name or s["fn"] == name:
            return s
    return {"name": name, "desc": "", "fn": "", "framework": "", "gate": ""}


def route_by_action(action: str) -> list:
    if action == "course_map":
        return ["课程地图"]
    if action == "generate":
        return ["教案撰写", "周间记忆", "讲义撰写", "课件制作", "逐字稿撰写", "质量校验", "打包导出"]
    if action == "revise":
        return ["文件修改", "质量校验"]
    return ["需求映射"]


# ================= 后台任务 =================
def task_state(tid: str) -> dict:
    t = store.get_task(tid)
    if not t:
        return {"status": "missing", "log": [], "done": 0, "total": 0}
    t["percent"] = int(t.get("done", 0) / t["total"] * 100) if t.get("total") else 0
    return t


def cancel(tid: str) -> dict:
    t = store.get_task(tid)
    if not t:
        return {"ok": False, "msg": "任务不存在"}
    if t["status"] not in ("queued", "running"):
        return {"ok": False, "msg": "任务已结束"}
    store.request_cancel(tid)
    store.append_task_log(tid, "收到取消请求，将在当前文件完成后停止")
    return {"ok": True, "msg": "正在取消…"}


def has_running_task(course_id: int) -> bool:
    return any(t["status"] in ("queued", "running") for t in store.list_tasks(course_id, 5))


def _approved_weeks(course_id: int) -> set:
    return {p["week_no"] for p in store.list_week_plans(course_id) if p["status"] == "approved"}


def generate_weeks(course_id: int, weeks: list, file_types=None, focus: str = "",
                   tone: str = "", auto: bool = False) -> dict:
    """启动批量生成（后台线程）。返回 {ok, task_id} 或 {ok:False,msg}。"""
    course = store.get_course(course_id)
    if not course:
        return {"ok": False, "msg": "课程不存在"}
    if config.MODE != "real":
        return {"ok": False, "msg": "未配置 API Key：生成需要调用真实大模型，请先在 .env 配置 LLM_API_KEY 并重启服务"}
    weeks = sorted({int(w) for w in (weeks or [])})
    if not weeks:
        return {"ok": False, "msg": "请选择要生成的周次"}
    approved = _approved_weeks(course_id)
    missing = [w for w in weeks if w not in approved]
    if missing:
        return {"ok": False,
                "msg": f"第{'、'.join(map(str, missing))}周尚未批准课程地图，请先完成门 A"}
    if has_running_task(course_id):
        return {"ok": False, "msg": "已有生成任务在运行，请等待完成或先取消"}
    fts = [f for f in (file_types or _FILE_ORDER) if f in tools.FILE_TYPES]
    if not fts:
        return {"ok": False, "msg": "请至少选择一种文件类型"}
    fts = [f for f in _FILE_ORDER if f in fts]
    payload = {"weeks": weeks, "file_types": fts, "focus": focus, "tone": tone,
               "auto": bool(auto)}
    total = len(weeks) * len(fts)
    tid = store.create_task(course_id, "generate", payload, total)
    store.append_task_log(
        tid, f"任务已创建：第{'、'.join(map(str, weeks))}周 · "
             f"{'、'.join(tools.file_type_cn(f) for f in fts)}"
             + ("（自动续跑）" if auto else ""))
    t = threading.Thread(target=_run_weeks, args=(tid, course_id, weeks, fts, focus, tone),
                         daemon=True, name=f"gen-{tid}")
    t.start()
    return {"ok": True, "task_id": tid, "total": total}


def _done(tid, n=1):
    t = store.get_task(tid)
    if t:
        store.update_task(tid, done=min(t["total"], t.get("done", 0) + n))


def _run_weeks(tid: str, course_id: int, weeks: list, fts: list, focus: str, tone: str):
    store.update_task(tid, status="running")
    store.update_course_status(course_id, "generating")
    store.append_task_log(tid, "开始执行：按「教案→讲义→课件/逐字稿」依赖链逐周推进（周间记忆已启用）")
    review_count = 0
    fail_count = 0
    prev_summary = ""
    try:
        for w in weeks:
            if store.task_cancelled(tid):
                break
            plan = store.ensure_artifact(course_id, w, "lesson_plan")
            for ft in fts:
                if store.task_cancelled(tid):
                    break
                try:
                    res = _process_one(tid, course_id, w, ft, prev_summary, focus, tone)
                    if res == "review":
                        review_count += 1
                    elif res == "failed":
                        fail_count += 1
                except Exception as e:  # 单项失败不影响整批
                    fail_count += 1
                    store.append_task_log(tid, f"第{w}周{tools.file_type_cn(ft)}异常：{type(e).__name__}: {e}")
                    store.set_artifact(store.ensure_artifact(course_id, w, ft)["id"],
                                       status="failed", feedback=str(e)[:300])
                _done(tid, 1)

            # 周间记忆：取本周教案摘要，注入下一周
            plan = store.ensure_artifact(course_id, w, "lesson_plan")
            if plan.get("content"):
                try:
                    r = gateway.chat(prompts.summary_gen(plan["content"], 180),
                                     temperature=0.2, max_tokens=360, task="summary",
                                     file_type="summary", course_id=course_id, week_no=w)
                    prev_summary = r["text"].strip()
                except Exception:
                    prev_summary = prompts.summary_prompt(plan["content"], 180)
            if store.task_cancelled(tid):
                break

        if store.task_cancelled(tid):
            store.update_task(tid, status="cancelled", message="已取消")
            store.append_task_log(tid, "任务已取消（已完成的文件保留，可继续确认）")
        else:
            msg = f"本轮完成：{review_count} 份待确认"
            if fail_count:
                msg += f"，{fail_count} 项失败"
            store.update_task(tid, status="done", message=msg)
            store.append_task_log(tid, msg + "；请在「确认中心」逐份批准（门 B）")
    except Exception as e:
        store.update_task(tid, status="failed", message=f"任务失败：{e}")
        store.append_task_log(tid, f"任务异常终止：{type(e).__name__}: {e}")
    finally:
        arts = store.list_artifacts(course_id, with_content=False)
        if any(a["status"] == "review" for a in arts):
            store.update_course_status(course_id, "review")
        elif arts and all(a["status"] == "approved" for a in arts):
            store.update_course_status(course_id, "ready")
        else:
            store.update_course_status(course_id, "generating")


def _process_one(tid, course_id, w, ft, prev_summary, focus, tone) -> str:
    """处理单个文件，返回 review / skipped / failed / done。"""
    a = store.ensure_artifact(course_id, w, ft)
    label = f"第{w}周{tools.file_type_cn(ft)}"
    if a["status"] == "approved" and a.get("content"):
        store.append_task_log(tid, f"{label}已定稿，跳过")
        return "done"
    if a["status"] == "review" and a.get("content"):
        store.append_task_log(tid, f"{label}待确认，跳过（批准后自动续跑）")
        return "review"
    ok, missing = tools.dependencies_ready(course_id, w, ft)
    if not ok:
        store.append_task_log(tid, f"{label}等待依赖：{'、'.join(missing)} 尚未批准")
        return "skipped"

    fn = getattr(tools, tools.FILE_TYPES[ft]["generator"])
    kwargs = {"focus": focus, "tone": tone}
    if ft == "lesson_plan":
        kwargs["prev_summary"] = prev_summary
    last = None
    for attempt in (1, 2):
        if store.task_cancelled(tid):
            return "skipped"
        try:
            store.append_task_log(tid, f"调用技能「{SKILL_MAP.get(fn.__name__, {}).get('name', fn.__name__)}」"
                                       f"生成{label}" + (f"（第{attempt}次）" if attempt > 1 else ""))
            r = fn(course_id, w, **kwargs)
            if r.get("ok"):
                msg = r.get("msg", "")
                store.append_task_log(tid, msg)
                if r.get("warnings"):
                    store.append_task_log(tid, f"{label}校验提示：" + "；".join(r["warnings"][:4]))
                return "review"
            last = r.get("msg") or "生成失败"
            store.append_task_log(tid, f"{label}未生成：{last}")
            if "依赖" in last:
                return "skipped"
        except Exception as e:
            last = str(e)
            store.append_task_log(tid, f"{label}第{attempt}次失败：{type(e).__name__}: {last}")
            if attempt == 1:
                time.sleep(1.0)
    store.set_artifact(a["id"], status="failed", feedback=(last or "")[:300])
    store.append_task_log(tid, f"{label}两次失败，已标记失败，可在确认中心单独重试")
    return "failed"


# ================= 周间记忆 / 自动续跑 =================
def summarize_week(course_id: int, week_no: int, max_len: int = 180) -> str:
    a = store.ensure_artifact(course_id, week_no, "lesson_plan")
    if not a.get("content"):
        return ""
    try:
        r = gateway.chat(prompts.summary_gen(a["content"], max_len), temperature=0.2,
                         max_tokens=360, task="summary", file_type="summary",
                         course_id=course_id, week_no=week_no)
        return r["text"].strip()
    except Exception:
        return prompts.summary_prompt(a["content"], max_len)


def on_artifact_approved(course_id: int, week_no: int, file_type: str) -> dict:
    """门 B 批准后的自动续跑钩子（受课程 auto_chain 开关控制）。"""
    course = store.get_course(course_id)
    if not course or not int(course.get("auto_chain") or 0):
        return {"started": False, "reason": "未开启自动续跑"}
    if config.MODE != "real":
        return {"started": False, "reason": "未配置 API Key"}
    if week_no not in _approved_weeks(course_id):
        return {"started": False, "reason": "周次未批准课程地图"}
    if has_running_task(course_id):
        return {"started": False, "reason": "已有任务运行中"}
    ready = []
    for ft in _FILE_ORDER:
        a = store.ensure_artifact(course_id, week_no, ft)
        if a["status"] == "approved" and a.get("content"):
            continue
        if a["status"] == "review" and a.get("content"):
            continue
        ok, _ = tools.dependencies_ready(course_id, week_no, ft)
        if ok:
            ready.append(ft)
    # 只推进到「下一层」：教案批准后先生成讲义；讲义批准后生成课件与逐字稿
    if file_type == "lesson_plan":
        ready = [f for f in ready if f == "handout"]
    elif file_type == "handout":
        ready = [f for f in ready if f in ("courseware", "script")]
    else:
        ready = []
    if not ready:
        return {"started": False, "reason": "没有可续跑的下游文件"}
    r = generate_weeks(course_id, [week_no], ready, auto=True)
    if r.get("ok"):
        store.append_task_log(r["task_id"], "由门 B 批准自动触发")
    return {"started": bool(r.get("ok")), **(r if r.get("ok") else {"reason": r.get("msg")})}


# ================= 课程地图（门 A） =================
def run_build_plan(course_id: int, weeks: list, focus: str = "", tone: str = "") -> dict:
    return tools.build_plan(course_id, weeks, focus, tone)


# ================= 对话总控（解析 + 执行） =================
def chat(course_id: int, text: str, execute: bool = True) -> dict:
    it = intent.parse(course_id, text)
    if not it.get("ok"):
        return it
    result = {"intent": it, "executed": False, "reply": it.get("reply", "")}

    def finish():
        store.add_message(course_id, "assistant", result.get("reply") or "")
        return {**it, **result}

    if not execute:
        return finish()
    if config.MODE != "real" and it.get("action") in ("course_map", "generate", "revise"):
        result["needs_key"] = True
        result["reply"] = (it.get("reply") or "") + \
            "\n当前未配置 API Key，无法调用大模型执行。请先在 .env 填写 LLM_API_KEY 并重启服务。"
        return finish()
    try:
        if it["action"] == "course_map":
            r = tools.build_plan(course_id, it.get("weeks") or [], it.get("focus", ""),
                                 it.get("tone", ""))
            result.update(executed=bool(r.get("ok")), plan_result=r,
                          reply=r.get("msg") if r.get("ok") else f"{it.get('reply','')}\n{r.get('msg')}")
        elif it["action"] == "generate":
            r = generate_weeks(course_id, it.get("weeks") or [], it.get("file_types"),
                               it.get("focus", ""), it.get("tone", ""))
            result.update(executed=bool(r.get("ok")), task_id=r.get("task_id"),
                          reply=(it.get("reply", "") + "\n" + r.get("msg", "")) if r.get("ok")
                          else f"{it.get('reply','')}\n{r.get('msg')}")
        elif it["action"] == "revise":
            tgt = it.get("target") or {}
            if tgt.get("week") and tgt.get("file_type") and it.get("focus"):
                aid = store.ensure_artifact(course_id, int(tgt["week"]), tgt["file_type"])["id"]
                r = tools.revise_artifact(aid, it.get("focus"))
                result.update(executed=bool(r.get("ok")), artifact_id=aid, reply=r.get("msg"))
            else:
                result["questions"] = it.get("questions") or [
                    "请说明要修改哪一周、哪份文件，以及具体要求（如：第 2 周教案，导入换成校园案例）"]
                result["reply"] = (it.get("reply") or "") + "\n" + result["questions"][0]
        else:
            result["questions"] = it.get("questions") or []
    except Exception as e:
        result["reply"] = f"{it.get('reply','')}\n执行失败：{e}"
    return finish()
