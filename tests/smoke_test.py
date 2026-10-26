# -*- coding: utf-8 -*-
"""端到端冒烟测试（无需 API Key）。

用假的 OpenAI 兼容网关替换 app.gateway.chat，真实启动 uvicorn，
跑通：建课 → 上传/粘贴资料 → 解析 → 课程地图（门 A）→ 生成教案（门 B）
→ 自动续跑讲义 → 自动续跑逐字稿 → 修订 → 导出 docx/html/md → 打包 → 对话总控。

运行：
    cd 备课智能体演示版
    .venv/Scripts/python.exe tests/smoke_test.py
"""
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if os.environ.get("KB_SMOKE_DIR"):
    TMP = Path(os.environ["KB_SMOKE_DIR"])
    TMP.mkdir(parents=True, exist_ok=True)
else:
    TMP = Path(tempfile.mkdtemp(prefix="kb-smoke-"))
os.environ["DB_PATH"] = str(TMP / "data.db")
os.environ["OUTPUT_DIR"] = str(TMP / "output")
os.environ["LLM_API_KEY"] = "test-key"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
sys.path.insert(0, str(ROOT))

from app import gateway  # noqa: E402

PORT = 8019
BASE = f"http://127.0.0.1:{PORT}"
PASS = 0


def check(cond, label, extra=""):
    global PASS
    if not cond:
        print(f"[FAIL] {label} {extra}")
        raise SystemExit(1)
    PASS += 1
    print(f"[ OK ] {label}")


# ================= 假模型 =================
def _plan_text(week, title, hours=2):
    total = hours * 45
    parts = [10, 30, 25, total - 80, 15] if total >= 90 else [5, total - 20, 5, 5, 5]
    names = ["课程导入", "概念讲解", "案例辨析", "课堂实训", "小结与作业"]
    rows = []
    for i, (nm, mi) in enumerate(zip(names, parts)):
        rows.append(
            f"| 一、{nm}（{mi}分钟） | 第{i + 1}环节：围绕「{title}」讲解具体知识点、"
            f"展示来自课程资料的真实案例与数据，并给出正例与反例 | 展示案例并追问："
            f"这个画面里哪一处体现了{title}的核心要点？请两位同学回答后点评 | "
            f"观察、记录并在学习通提交一句话判断，同伴互评 | 用具体任务检验理解，"
            f"让{title}从概念落到可操作的动作 |")
    body = "\n".join(rows)
    long = ("本环节的教学内容来自上传资料的原文：镜头语言包含远景、全景、中景、近景、特写，"
            "景别决定信息量与情绪强度；脚本结构强调开头三秒抓住注意力，中段展开冲突，结尾引导互动。"
            "教师需要把上述概念与本周主题结合，给出学生可执行的操作步骤和判断标准。"
            * 3)
    return f"""# 教案：第 {week} 周 {title}

一句话思政核心：用镜头记录身边的中国故事，在真实任务中体会文化自信。

## 一、教学基本信息
| 项目 | 内容 |
| --- | --- |
| 课题 | 短视频制作——{title} |
| 班级 | 网新2531 |
| 课时安排 | {hours} 课时（{total} 分钟）|
| 教材 | 短视频制作（第 3 章）|
| 课程类型 | 专业核心课 |
| 授课地点 | 实训室 |
| 教学目标 | 知识目标：能说出五种景别的定义与信息量差异；能力目标：能为给定情境独立设计三个镜头并说明理由；素养目标：形成用影像讲好中国故事的意识 |
| 教学重难点 | 重点：景别与信息量的对应关系；难点：景别选择与情绪表达的统一 |
| 学情分析 | 学生已具备手机拍摄基础，但习惯用全景记录，缺少景别判断；本课用对比案例与限时任务突破 |
| 教学方法 | 讲授法、案例分析法、任务驱动法、同伴互评 |
| 教学资源 | 多媒体课件、学习通、校园短视频案例、分镜表模板 |
| 教学反思 | 课后根据学生分镜作品判断景别选择是否到位，并记录典型错误 |

## 二、教学过程环节
| 教学环节 | 教学内容 | 教师活动 | 学生活动 | 设计意图 |
| --- | --- | --- | --- | --- |
{body}

## 三、教学资源与课后反思
{long}
"""


def _handout_text(week, title):
    return f"""# 讲义：第 {week} 周 {title}

## 一、导入（10分钟）
同学们好，上节课我们完成了拍摄基础。今天进入「{title}」。先看一段校园短片，请大家注意：哪一个镜头让你印象最深？（停顿）为什么？请两位同学说说看。

## 二、概念讲解（30分钟）
我们先明确景别：远景交代环境，全景交代人物关系，中景看动作，近景看表情，特写看细节。请大家注意，景别不是越大越好，它决定的其实是观众能看到多少信息。比如拍食堂排队，用全景能看到队伍长度，用特写只能看到餐盘——这就是信息量的差别。那么，如果我们要表现"等待很久"，你会选哪个景别？（提问）

## 三、案例辨析（25分钟）
来看同一情境的五种拍法。第一组用远景，第二组用特写。请大家判断：哪一组更能表现情绪？为什么？小组讨论三分钟，派代表说明理由。教师点评时要注意，把"景别—信息量—情绪"三者连起来。

## 四、课堂实训（15分钟）
现在请大家独立完成一个任务：为"食堂排队"设计三个镜头，写清景别、画面内容和选择理由，提交到学习通。巡视时重点看学生是否只会用全景。

## 五、小结与作业（10分钟）
今天我们掌握了一条主线：先判断要传递什么信息，再选择景别。课后作业：用手机拍三张不同景别的照片，并各写一句选择理由；预习下周的脚本结构。
"""


def _script_text(week, title):
    body = f"""## 开场（3分钟）
（面带微笑，环视教室）同学们好！欢迎回到短视频制作课堂。上节课我们练了拍摄基础，这节课我们进入「{title}」。（停顿）先问大家一个问题：你上一次刷到的短视频，第一个画面是什么？

## 导入（8分钟）
（播放校园短片，30 秒）请大家边看边记：哪个镜头让你印象最深？（暂停视频）好，请这位同学说说。（倾听并点头）他说是特写，因为看到了人物的表情。很好，这就是今天要讲的景别。

## 核心讲解（30分钟）
（切换课件）我们先看远景。远景交代环境，让观众知道"在哪里"。（指向屏幕）这张图是校园全景，信息量最大，但情绪最弱。再看特写，只保留眼睛，信息量小，但情绪最强。大家发现了吗？景别其实是在做减法。（板书：信息量↓ 情绪↑）那么中景呢？中景看动作，适合讲"发生了什么"。

## 互动辨析（20分钟）
（发放对比图）现在四人一组，比较远景和特写两组画面，讨论：如果要表现"等待很久"，选哪一组？为什么？给大家三分钟。（巡视）第二组，你们说选特写，因为能看到焦急的表情，很好。还有不同意见吗？（请另一位同学）他说可以先用远景交代队伍，再用特写切表情——这个思路更完整，我们把掌声给他。

## 实训（15分钟）
（发分镜表）现在独立完成：为"食堂排队"设计三个镜头，写清景别、画面内容、选择理由。做完后同桌互查，看看有没有只会用全景的情况。（巡视并个别指导）注意，三个镜头要能连成一个完整的小故事。

## 小结与作业（7分钟）
（回到板书）今天我们记住一句话：先想清楚要传递什么信息，再决定用哪个景别。课后作业：拍三张不同景别的照片，各写一句理由；预习脚本结构。（下课）
"""
    # 补足字数与舞台指示
    fill = "".join(
        f"（停顿·{i}）第{i}组注意，景别的选择没有标准答案，但有判断标准：信息量、情绪强度、叙事目的。"
        f"（板书·{i}）把第{i}组讨论的三个标准用在每一次拍摄里。"
        f"（提问·{i}）如果第{i}组换成夜间场景，你会怎么调整？"
        f"（倾听·{i}）很好，第{i}组先保证曝光，再考虑景别。"
        for i in range(1, 7))
    return body + "\n\n## 补充讲解\n" + fill + "\n"


def _courseware_text(week, title):
    data = {
        "title": f"{title} · 互动课件",
        "subtitle": "用镜头语言把知识点讲清楚",
        "duration": "2学时（90分钟）",
        "learning_goals": ["能区分五种景别", "能为给定情境选择景别并说明理由",
                           "能用影像讲好身边的中国故事"],
        "slides": [
            {"type": "cover", "title": f"第{week}周 · {title}", "subtitle": "短视频制作",
             "bullets": [], "notes": "开场问好，说明本课主题与课堂任务。"},
            {"type": "objectives", "title": "学习目标", "bullets": [
                "能说出五种景别的定义与适用场景", "能为校园短片选择合适景别",
                "能说明景别与信息量、情绪的关系"], "notes": "带学生读目标，明确本课要完成的分镜任务。"},
            {"type": "concept", "title": "景别：信息量的减法", "bullets": [
                "远景交代环境，全景交代人物关系", "中景看动作，近景看表情，特写看细节",
                "景别越小，信息越少，情绪越强"], "notes": "用校园全景与特写对比，建立信息量—情绪坐标。"},
            {"type": "case", "title": "案例：食堂排队的等待", "bullets": [
                "情境：午餐高峰的食堂窗口", "问题：怎样让观众感到等待很久",
                "判断：先用远景交代队伍，再切特写抓表情"], "notes": "先让学生判断，再给出组合镜头的思路。"},
            {"type": "activity", "title": "课堂活动：设计三个镜头", "bullets": [
                "任务：为校园快递站排队设计三个镜头", "步骤：写景别、画面、理由",
                "提交：学习通分镜表，同桌互评"], "notes": "巡视时关注学生是否只会用全景。",
             "interaction": {"type": "discuss", "question": "三个镜头如何连成一个完整的小故事？",
                              "answer": "先交代环境，再抓动作，最后用特写收束情绪。"}},
            {"type": "quiz", "title": "随堂测验：选哪个景别", "bullets": [], "notes": "先让学生举手，再点选项揭晓答案。",
             "interaction": {"type": "quiz", "question": "要表现人物焦急的表情，优先用哪种景别？",
                              "options": ["远景", "特写", "全景"], "answer": "B",
                              "explain": "特写压缩环境信息，放大表情与情绪。"}},
            {"type": "concept", "title": "投票：等待很久怎么拍", "bullets": [
                "A：一个远景固定镜头", "B：远景 + 特写组合", "C：只拍餐盘特写"],
             "notes": "投票后请两组说明理由，引出组合镜头。",
             "interaction": {"type": "poll", "question": "你会选哪种拍法？",
                              "options": ["一个远景", "远景+特写", "只拍餐盘"], "answer": "B"}},
            {"type": "summary", "title": "本课小结", "bullets": [
                "先判断信息，再选择景别", "景别是减法，情绪是加法",
                "作业：拍三张不同景别照片并写理由"], "notes": "回扣目标，布置作业，预告脚本结构。"},
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def fake_chat(messages, **kw):
    task = kw.get("task") or ""
    ft = kw.get("file_type") or ""
    user = messages[-1]["content"] if messages else ""
    week = int((re.search(r"第\s*(\d+)\s*周", user) or [0, 1])[1])
    title = (re.search(r"主题[：:]\s*([^\n（(]+)", user) or [0, "镜头语言与景别"])[1].strip()
    hours = int((re.search(r"（\s*(\d+)\s*学时\s*）", user) or [0, 2])[1])
    course = (re.search(r"课程[：:]\s*([^\n（(]+)", user) or [0, "短视频制作"])[1].strip()
    text = ""
    if task == "intent":
        if "地图" in user:
            text = json.dumps({"action": "course_map", "workflow": "course_map",
                               "file_types": [], "weeks": [1, 2], "focus": "",
                               "tone": "", "reply": "先生成课程地图"}, ensure_ascii=False)
        elif "生成" in user:
            text = json.dumps({"action": "generate", "workflow": "week_package",
                               "file_types": ["lesson_plan", "handout", "courseware", "script"],
                               "weeks": [2], "focus": "", "tone": "",
                               "reply": "开始生成第 2 周教学包"}, ensure_ascii=False)
        else:
            text = json.dumps({"action": "ask", "workflow": "ask", "file_types": [],
                               "weeks": [], "reply": "请告诉我周次"}, ensure_ascii=False)
    elif ft == "week_plan" or task == "course_map":
        weeks = [int(x) for x in re.findall(r"\d+", (re.search(r"需要输出的周次[：:]\s*\[([^\]]+)\]", user) or [0, "1"])[1])]
        names = ["课程导入与拍摄基础", "镜头语言与景别", "脚本结构与爆点", "剪辑节奏", "综合实训"]
        arr = [{"week": w, "title": names[(w - 1) % len(names)],
                "hours": 2, "objective": f"能独立完成{names[(w - 1) % len(names)]}的课堂任务并说明理由",
                "ideo": "用影像讲好身边的中国故事"} for w in weeks]
        text = json.dumps(arr, ensure_ascii=False)
    elif ft == "lesson_plan" or task == "lesson_plan":
        text = _plan_text(week, title, hours)
    elif ft == "handout" or task == "handout":
        text = _handout_text(week, title)
    elif ft == "courseware" or task == "courseware":
        text = _courseware_text(week, title)
    elif ft == "script" or task == "script":
        text = _script_text(week, title)
    elif task == "revise":
        text = _script_text(week, title) + "\n（本次已按反馈把本地案例换成校园快递站排队。）\n"
    elif task == "summary":
        text = f"上周主题{title}，已讲景别与信息量，布置了分镜作业，下周需要衔接脚本结构。"
    else:
        text = f"示例内容：{title}"
    gateway._record_usage("fake", "fake-1", 120, 300, 0.0012, kw.get("course_id"),
                          kw.get("week_no"), ft or "general", task, 12)
    return {"text": text, "model": "fake-1", "tokens": {"in": 120, "out": 300},
            "cost": 0.0012, "trace_id": "fake", "latency_ms": 12, "finish_reason": "stop"}


gateway.chat = fake_chat

# ================= HTTP 工具 =================
def http(method, path, body=None, raw=None, headers=None):
    url = BASE + path
    data = raw
    hd = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hd["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hd)
    with urllib.request.urlopen(req, timeout=120) as r:
        ctype = r.headers.get("Content-Type", "")
        blob = r.read()
        if "json" in ctype:
            return json.loads(blob.decode("utf-8"))
        return blob


def wait_task(tid, timeout=60):
    for _ in range(timeout * 2):
        t = http("GET", f"/api/task/{tid}")
        if t.get("status") not in ("queued", "running"):
            return t
        time.sleep(0.5)
    raise AssertionError(f"任务超时：{tid}")


def multipart(fields, files):
    boundary = "----smoke" + str(int(time.time() * 1000))
    out = []
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for name, content, ctype in files:
        out.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n').encode())
        out.append(content)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def main():
    print("TMP", TMP, "DB", os.environ.get("DB_PATH"), "writable", os.access(TMP, os.W_OK))
    with open(TMP / "probe.txt", "w", encoding="utf-8") as f:
        f.write("ok")
    import sqlite3
    probe = sqlite3.connect(str(TMP / "probe.db"))
    probe.execute("CREATE TABLE IF NOT EXISTS t(x)")
    probe.commit()
    probe.close()
    print("probe ok")
    from app import store
    store.init()
    import uvicorn
    from app.main import app
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    check(True, "服务已启动")

    info = http("GET", "/api/system/info")
    check(info["version"] == "2.0.0" and info["frameworks"]["total"] >= 7, "系统信息/框架库")
    check(len(http("GET", "/api/frameworks")["frameworks"]) >= 7, "框架列表")
    check(len(http("GET", "/api/vault")["items"]) >= 5, "公共资源区种子数据")

    c = http("POST", "/api/course", {"name": "短视频制作（冒烟测试）", "semester": "2026-2027-1",
                                     "weeks": 16, "theme": "镜头语言、脚本结构、剪辑节奏",
                                     "class_name": "网新2531", "textbook": "短视频制作"})
    check(c["ok"], "新建课程")
    cid = c["course_id"]

    # 粘贴文本 + CSV 上传
    r = http("POST", f"/api/course/{cid}/material-text",
             {"filename": "教学计划.txt",
              "content": "第1周 课程导入与拍摄基础\n第2周 镜头语言与景别：远景、全景、中景、近景、特写\n第3周 脚本结构：三幕式"})
    check(r["ok"], "粘贴资料")
    raw, hd = multipart({}, [("进度表.csv", "周次,主题\n1,课程导入\n2,镜头语言\n".encode("utf-8"), "text/csv")])
    r = http("POST", f"/api/course/{cid}/material", raw=raw, headers=hd)
    check(r["ok"], "上传 CSV 资料")
    mats = http("GET", f"/api/course/{cid}/board")["materials"]
    check(len(mats) == 2, f"资料去重后 2 份（实际 {len(mats)}）")

    r = http("POST", f"/api/course/{cid}/parse", {})
    check(r["ok"] and "2 份" in r["msg"], "解析资料（摘要）")

    r = http("POST", f"/api/course/{cid}/plan", {"weeks": [1, 2]})
    check(r["ok"] and len(r["plans"]) == 2, "生成课程地图（门 A）")
    r = http("PATCH", f"/api/course/{cid}/plan/2", {"title": "镜头语言与景别（已校对）"})
    check(r["ok"], "编辑课程地图")
    r = http("POST", f"/api/course/{cid}/plan/approve", {"weeks": [1, 2]})
    check(r["ok"], "批准课程地图")
    # 修改已批准周次应自动退回待确认
    r = http("PATCH", f"/api/course/{cid}/plan/2", {"objective": "能区分五种景别并说明选择理由"})
    check(r["ok"] and r["week"]["status"] == "review", "修改已批准周次自动退回门 A")
    r = http("POST", f"/api/course/{cid}/plan/approve", {"weeks": [2]})
    check(r["ok"], "重新批准该周次")

    g = http("POST", f"/api/course/{cid}/generate",
             {"weeks": [1], "file_types": ["lesson_plan", "handout", "courseware", "script"],
              "focus": "多放校园案例"})
    check(g["ok"], "启动生成任务")
    t = wait_task(g["task_id"])
    check(t["status"] == "done" and t["percent"] == 100, "生成任务完成且进度 100%")

    arts = {a["file_type"]: a for a in http("GET", f"/api/course/{cid}/board")["artifacts"]}
    check(arts["lesson_plan"]["status"] == "review", "教案进入门 B")
    check(arts["handout"]["status"] == "pending", "讲义等待教案批准")
    check(arts["courseware"]["status"] == "pending", "课件等待教案与讲义批准")

    ap = http("POST", f"/api/artifact/{arts['lesson_plan']['id']}/approve")
    check(ap["ok"] and ap.get("auto", {}).get("started"), "批准教案后自动续跑讲义")
    t2 = wait_task(ap["auto"]["task_id"])
    check(t2["status"] == "done", "自动续跑任务完成")
    arts = {a["file_type"]: a for a in http("GET", f"/api/course/{cid}/board")["artifacts"]}
    check(arts["handout"]["status"] == "review", "讲义完成进入门 B")

    ap = http("POST", f"/api/artifact/{arts['handout']['id']}/approve")
    check(ap["ok"] and ap.get("auto", {}).get("started"), "批准讲义后自动续跑课件与逐字稿")
    t3 = wait_task(ap["auto"]["task_id"])
    check(t3["status"] == "done" and t3["total"] == 2, "课件与逐字稿任务完成")
    arts = {a["file_type"]: a for a in http("GET", f"/api/course/{cid}/board")["artifacts"]}
    check(arts["script"]["status"] == "review", "逐字稿完成进入门 B")
    check(arts["courseware"]["status"] == "review", "课件完成进入门 B")

    cw = http("GET", f"/api/artifact/{arts['courseware']['id']}")["artifact"]
    check(len(cw["content"]) > 800 and not cw["issues"],
          f"课件 JSON 校验通过（{len(cw['content'])} 字符）", extra=str(cw["issues"]))
    preview = http("GET", f"/api/artifact/{arts['courseware']['id']}/preview")
    check(b'id="deck"' in preview and b"<iframe" not in preview, "互动课件预览 HTML")
    pptx = http("GET", f"/api/artifact/{arts['courseware']['id']}/export?fmt=pptx")
    check(len(pptx) > 10000 and pptx[:2] == b"PK", "导出 PPTX")
    cw_html = http("GET", f"/api/artifact/{arts['courseware']['id']}/export?fmt=html")
    check(len(cw_html) > 3000 and b"id=\"deck\"" in cw_html, "导出互动 HTML")

    a = http("GET", f"/api/artifact/{arts['script']['id']}")["artifact"]
    check(len(a["content"]) > 2500 and not a["issues"],
          f"逐字稿校验通过（{len(a['content'])} 字）", extra=str(a["issues"]))

    r = http("POST", f"/api/artifact/{arts['script']['id']}/revise",
             {"feedback": "把案例换成校园快递站排队，语气更口语"})
    check(r["ok"], "带反馈修改")
    revs = http("GET", f"/api/artifact/{arts['script']['id']}/revisions")["revisions"]
    check(len(revs) >= 2, "修改历史已记录")
    r = http("POST", f"/api/artifact/{arts['script']['id']}/restore/{revs[-1]['id']}")
    check(r["ok"], "版本回退")

    r = http("POST", f"/api/artifact/{arts['courseware']['id']}/approve")
    check(r["ok"], "课件定稿")

    for ft in ("lesson_plan", "handout", "script"):
        for kind in ("docx", "html", "md"):
            blob = http("GET", f"/api/artifact/{arts[ft]['id']}/export?fmt={kind}")
            check(len(blob) > 200, f"导出 {ft}.{kind}")

    p = http("POST", f"/api/course/{cid}/package", {})
    check(p["ok"] and p["size"] > 0, "打包教学包")
    z = http("GET", f"/api/course/{cid}/download")
    check(len(z) > 1000, "下载 zip")
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        names = zf.namelist()
        check(any(n.endswith("课件.pptx") for n in names), "教学包含 PPTX 课件")
        check(any(n.endswith("课件-互动版.html") for n in names), "教学包含互动 HTML 课件")

    chat = http("POST", f"/api/course/{cid}/chat", {"text": "生成第2周教学包"})
    check(chat["ok"] and chat.get("task_id"), "对话总控直接启动生成")
    wait_task(chat["task_id"])

    v = http("POST", "/api/vault", {"kind": "case", "name": "测试案例", "content": "食堂排队情境",
                                    "tags": "校园"})
    check(v["ok"], "新增公共资源")
    r = http("PATCH", f"/api/vault/{v['item_id']}", {"name": "测试案例（改）"})
    check(r["ok"], "编辑公共资源")
    r = http("DELETE", f"/api/vault/{v['item_id']}")
    check(r["ok"], "删除公共资源")

    usage = http("GET", f"/api/course/{cid}/usage")
    check(usage["calls"] > 0, f"用量计量（{usage['calls']} 次调用）")

    print(f"\n===== 全部通过：{PASS} 项 =====")
    print(f"临时数据目录：{TMP}")
    server.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
