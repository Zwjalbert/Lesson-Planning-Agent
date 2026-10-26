# -*- coding: utf-8 -*-
"""生成一份可视化演示数据（不调用模型），用于界面检查与截图。

用法：
    $env:KB_DEMO_DIR='...'
    python tests/seed_demo.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(os.environ.get("KB_DEMO_DIR") or (ROOT / "_demo"))
TMP.mkdir(parents=True, exist_ok=True)
os.environ["DB_PATH"] = str(TMP / "data.db")
os.environ["OUTPUT_DIR"] = str(TMP / "output")
sys.path.insert(0, str(ROOT))

from app import store  # noqa: E402


def make_plan(week, title, hours=2):
    total = hours * 45
    parts = [10, 30, 25, total - 80, 15]
    names = ["课程导入", "概念讲解", "案例辨析", "课堂实训", "小结与作业"]
    rows = []
    for i, (nm, mi) in enumerate(zip(names, parts)):
        rows.append(
            f"| {['一','二','三','四','五'][i]}、{nm}（{mi}分钟） | 第{i + 1}环节：围绕「{title}」讲解具体知识点，"
            f"展示课程资料中的真实案例与数据，给出正例与反例 | 展示案例并追问：这个画面里哪一处体现了"
            f"{title}的核心要点？请两位同学回答后点评 | 观察、记录并在学习通提交一句话判断，同伴互评 | "
            f"用具体任务检验理解，让{title}从概念落到可操作的动作 |")
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
{chr(10).join(rows)}

## 三、教学资源与课后反思
本课以「{title}」为主线，结合课程资料中的景别定义、镜头语言与脚本结构展开。课堂开始用校园短片
激活经验，随后用五组对比画面建立"信息量—情绪"的判断标准，再通过食堂排队情境完成迁移练习。
课后反思关注两点：学生能否说明选择理由，以及是否只会使用全景。下一周将把景别判断接入脚本结构，
让学生把镜头选择写进分镜表。教师在巡视时要记录典型错误，作为下周导入的真实素材。
"""


def make_handout(week, title):
    return f"""# 讲义：第 {week} 周 {title}

## 一、导入（10分钟）
同学们好，上节课我们完成了拍摄基础。今天进入「{title}」。先看一段校园短片，请大家注意：哪一个镜头让你印象最深？（停顿）为什么？请两位同学说说看。

## 二、概念讲解（30分钟）
我们先明确景别：远景交代环境，全景交代人物关系，中景看动作，近景看表情，特写看细节。请大家注意，景别不是越大越好，它决定的其实是观众能看到多少信息。比如拍食堂排队，用全景能看到队伍长度，用特写只能看到餐盘，这就是信息量的差别。那么，如果我们要表现"等待很久"，你会选哪个景别？

## 三、案例辨析（25分钟）
来看同一情境的五种拍法。第一组用远景，第二组用特写。请大家判断：哪一组更能表现情绪？为什么？小组讨论三分钟，派代表说明理由。教师点评时要把"景别—信息量—情绪"三者连起来。

## 四、课堂实训（15分钟）
现在请大家独立完成一个任务：为"食堂排队"设计三个镜头，写清景别、画面内容和选择理由，提交到学习通。巡视时重点看学生是否只会用全景。

## 五、小结与作业（10分钟）
今天我们掌握了一条主线：先判断要传递什么信息，再选择景别。课后作业：用手机拍三张不同景别的照片，并各写一句选择理由；预习下周的脚本结构。
"""


def make_script(week, title):
    return f"""## 开场（3分钟）
（面带微笑，环视教室）同学们好！欢迎回到短视频制作课堂。上节课我们练了拍摄基础，这节课我们进入「{title}」。（停顿）先问大家一个问题：你上一次刷到的短视频，第一个画面是什么？

## 导入（8分钟）
（播放校园短片，30 秒）请大家边看边记：哪个镜头让你印象最深？（暂停视频）好，请这位同学说说。（倾听并点头）他说是特写，因为看到了人物的表情。很好，这就是今天要讲的景别。

## 核心讲解（30分钟）
（切换课件）我们先看远景。远景交代环境，让观众知道"在哪里"。（指向屏幕）这张图是校园全景，信息量最大，但情绪最弱。再看特写，只保留眼睛，信息量小，但情绪最强。大家发现了吗？景别其实是在做减法。（板书：信息量下降、情绪上升）那么中景呢？中景看动作，适合讲"发生了什么"。

## 互动辨析（20分钟）
（发放对比图）现在四人一组，比较远景和特写两组画面，讨论：如果要表现"等待很久"，选哪一组？为什么？给大家三分钟。（巡视）第二组，你们说选特写，因为能看到焦急的表情，很好。还有不同意见吗？（请另一位同学）他说可以先用远景交代队伍，再用特写切表情，这个思路更完整，我们把掌声给他。

## 实训（15分钟）
（发分镜表）现在独立完成：为"食堂排队"设计三个镜头，写清景别、画面内容、选择理由。做完后同桌互查，看看有没有只会用全景的情况。（巡视并个别指导）注意，三个镜头要能连成一个完整的小故事。

## 小结与作业（7分钟）
（回到板书）今天我们记住一句话：先想清楚要传递什么信息，再决定用哪个景别。课后作业：拍三张不同景别的照片，各写一句理由；预习脚本结构。（下课）
"""


def main():
    store.init()
    if store.list_courses():
        print("已有课程，跳过种子数据")
        return
    cid = store.create_course("新媒体产品设计与制作（短视频）", "2026-2027-1", 16,
                              "镜头语言、脚本结构、剪辑节奏", "网新2531", "短视频制作（高教社）")
    store.add_material(cid, "短视频课程教学计划（1-16周）.txt",
                       "第1周 课程导入与拍摄基础\n第2周 镜头语言与景别\n第3周 脚本结构：三幕式与爆点\n"
                       "第4周 剪辑节奏与转场\n第5周 综合实训：30秒校园短片", "课程整体进度与每周主题安排，含实训节点。")
    store.add_material(cid, "第五章 镜头语言与景别.docx",
                       "景别包括远景、全景、中景、近景、特写。景别决定信息量与情绪强度。"
                       "远景交代环境，全景交代关系，中景看动作，近景看表情，特写看细节。",
                       "教材第五章：景别定义、信息量与情绪表达。")
    plans = [
        {"week": 1, "title": "课程导入与拍摄基础", "hours": 2,
         "objective": "能完成手机拍摄的三项基础设置并说明用途", "ideo": "用影像记录真实校园生活"},
        {"week": 2, "title": "镜头语言与景别", "hours": 2,
         "objective": "能区分五种景别并为给定情境选择景别", "ideo": "用镜头讲好身边的中国故事"},
        {"week": 3, "title": "脚本结构：三幕式与爆点", "hours": 2,
         "objective": "能按三幕式写出30秒短视频脚本", "ideo": "在叙事中传递积极价值"},
        {"week": 4, "title": "剪辑节奏与转场", "hours": 3,
         "objective": "能完成一段15秒片段的节奏剪辑", "ideo": "精益求精的工匠精神"},
        {"week": 5, "title": "综合实训：30秒校园短片", "hours": 4,
         "objective": "能独立完成30秒短片并说明创作思路", "ideo": "团队协作与责任担当"},
    ]
    store.save_week_plans(cid, plans)
    store.approve_week_plans(cid)
    store.update_week_plan(cid, 3, status="review")
    store.update_week_plan(cid, 4, status="review")
    store.update_week_plan(cid, 5, status="review")

    def put(week, ft, status, text, model="doubao-seed-2-1-pro-260915", cost=0.0123, warns=""):
        aid = store.ensure_artifact(cid, week, ft)["id"]
        store.set_artifact(aid, status=status, content=text, model=model, cost=cost,
                           tokens={"in": 3200, "out": 4200}, latency_ms=18200,
                           word_count=len(text), warnings=warns)
        store.save_revision(aid, text, source="generate", model=model)
        return aid

    put(1, "lesson_plan", "approved", make_plan(1, "课程导入与拍摄基础"))
    put(1, "handout", "approved", make_handout(1, "课程导入与拍摄基础"))
    put(1, "script", "approved", make_script(1, "课程导入与拍摄基础"))
    a2 = put(2, "lesson_plan", "review", make_plan(2, "镜头语言与景别"), cost=0.0156)
    put(2, "handout", "pending", "", model="", cost=0)
    put(3, "lesson_plan", "review", make_plan(3, "脚本结构：三幕式与爆点"), cost=0.0139)
    put(4, "lesson_plan", "failed", "", cost=0, warns="生成失败，可重试")

    # 给第 2 周教案加一个修订版本，展示版本历史
    store.save_revision(a2, make_plan(2, "镜头语言与景别") + "\n\n（修订：导入案例改为校园快递站排队。）",
                        feedback="导入换成校园快递站排队案例", source="revise",
                        model="doubao-seed-2-1-pro-260915")
    store.set_artifact(a2, content=make_plan(2, "镜头语言与景别") + "\n\n（修订：导入案例改为校园快递站排队。）",
                       revision=2, status="review")

    for i, (task, ft) in enumerate([("lesson_plan", "lesson_plan"), ("handout", "handout"),
                                    ("script", "script"), ("summary", "summary")]):
        store.insert_usage(f"demo-{i}", "doubao-seed-2-1-pro-260915", 3200 + i * 300,
                           4200 + i * 200, 0.012 + i * 0.002, cid, i + 1, ft,
                           task=task, latency_ms=16000 + i * 1200)
    for action, reason in [("create", "新媒体产品设计与制作（短视频）"),
                           ("upload", "短视频课程教学计划（1-16周）.txt"),
                           ("parse", "解析 2 份资料"), ("build_plan", "生成 5 周课程地图"),
                           ("approve_plan", "批准全部课程地图"),
                           ("approve", "第1周教案"), ("approve", "第1周讲义"),
                           ("approve", "第1周逐字稿")]:
        store.add_confirm_log(cid, None, action, reason)
    store.add_message(cid, "user", "生成第2-3周教学包")
    store.add_message(cid, "assistant", "好的，按课程地图已规划周次执行：第2、3周。先生成教案，批准后自动续跑讲义。")
    store.add_message(cid, "user", "第2周教案的导入换成校园快递站排队的案例")
    store.add_message(cid, "assistant", "已修改并刷新，保留了双表结构与环节时间；可在确认中心再次核对。")
    print("seeded", cid, TMP)


if __name__ == "__main__":
    main()
