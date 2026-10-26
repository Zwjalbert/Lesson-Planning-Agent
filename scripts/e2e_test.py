# -*- coding: utf-8 -*-
"""端到端验证脚本：真实模型模式跑通演示版全流程（模拟前端调用）。

按「增量推进」设计：每轮点「生成」推进一层（教案→批准→讲义→批准→逐字稿），
完整演示确认门 B「批准后自动继续下游」。
前置：在 .env 配置 LLM_API_KEY（全部生成内容均由 AI 大模型产出，需真实 Key）。
用法：.venv/bin/python scripts/e2e_test.py
"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000"
PASS, FAIL = 0, 0


def req(method, path, data=None, files=None):
    global PASS, FAIL
    try:
        if method == "GET":
            r = urllib.request.urlopen(BASE + path, timeout=30)
            body = r.read().decode()
        else:
            boundary = "----e2e%d" % int(time.time())
            parts = []
            if data:
                for k, v in data.items():
                    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
            if files:
                for name, content in files:
                    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\nContent-Type: text/plain\r\n\r\n{content}\r\n".encode())
            parts.append(f"--{boundary}--\r\n".encode())
            rq = urllib.request.Request(BASE + path, data=b"".join(parts), method=method,
                                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
            r = urllib.request.urlopen(rq, timeout=180)
            body = r.read().decode()
        try:
            j = json.loads(body)
        except Exception:
            j = {"raw": body[:200]}
        print(f"[OK] {method} {path} → {json.dumps(j, ensure_ascii=False)[:150]}")
        PASS += 1
        return j
    except UnicodeDecodeError:
        # 二进制响应（如 zip/docx 下载）
        print(f"[OK] {method} {path} → <binary>")
        PASS += 1
        return {"binary": True}
    except Exception as e:
        print(f"[FAIL] {method} {path} → {e}")
        FAIL += 1
        return None


def wait_task(tid):
    for _ in range(90):
        time.sleep(1.5)
        t = req("GET", f"/api/task/{tid}")
        if t and t.get("status") != "running":
            print("  任务日志：\n    " + "\n    ".join(t.get("log", [])))
            return t
    return None


def status_map(cid):
    b = req("GET", f"/api/course/{cid}/board")
    arts = (b or {}).get("artifacts", [])
    return arts, {f"{a['week_no']}-{a['file_type']}": a for a in arts}


def main():
    # 1. 建课 + 传资料 + 解析
    c = req("POST", "/api/course", {"name": "新媒体产品设计与制作（短视频）测试",
                                     "semester": "2026-2027-1", "weeks": "16",
                                     "theme": "短视频脚本、镜头语言、剪辑节奏"})
    cid = c["course_id"] if c else 1
    # 本脚本按「每轮手动推进一层」验证，先关闭自动续跑，避免与手动 generate 冲突
    req("PATCH", f"/api/course/{cid}", {"auto_chain": "0"})
    req("POST", f"/api/course/{cid}/material-text",
        {"filename": "教学计划与进度表",
         "content": "本课程面向短视频方向，第2周讲授镜头语言与景别，第3周讲授脚本结构（三幕式与爆点设计）。"
                    "教学目标是学生能独立撰写分镜脚本。课程思政：讲好中国故事，传播正能量。"})
    req("POST", f"/api/course/{cid}/material", None,
        files=[("课程讲义素材.txt", "镜头语言包括远景、全景、中景、近景、特写。景别决定信息量与情绪强度。"
                                    "脚本结构：开头3秒抓注意力，中段展开，结尾引导互动。")])
    req("POST", f"/api/course/{cid}/parse")

    # 2. 门 A：生成课程地图并批准
    req("POST", f"/api/course/{cid}/plan", {"weeks": "[2,3]"})
    req("POST", f"/api/course/{cid}/plan/approve")

    # 3. 门 B：三轮增量生成
    # 第 1 轮 → 生成教案（review）
    g = req("POST", f"/api/course/{cid}/generate", {"weeks": "[2,3]"})
    wait_task(g["task_id"])
    arts, _ = status_map(cid)
    print(f"  第1轮产物状态: {[(a['week_no'], a['file_type'], a['status']) for a in arts]}")

    # 批准全部教案 → 第 2 轮 → 生成讲义
    for a in arts:
        if a["file_type"] == "lesson_plan" and a["status"] == "review":
            req("POST", f"/api/artifact/{a['id']}/approve")
    g = req("POST", f"/api/course/{cid}/generate", {"weeks": "[2,3]"})
    wait_task(g["task_id"])
    arts, _ = status_map(cid)
    print(f"  第2轮产物状态: {[(a['week_no'], a['file_type'], a['status']) for a in arts]}")

    # 批准全部讲义 → 第 3 轮 → 生成逐字稿
    for a in arts:
        if a["file_type"] == "handout" and a["status"] == "review":
            req("POST", f"/api/artifact/{a['id']}/approve")
    g = req("POST", f"/api/course/{cid}/generate", {"weeks": "[2,3]"})
    wait_task(g["task_id"])
    arts, _ = status_map(cid)
    print(f"  第3轮产物状态: {[(a['week_no'], a['file_type'], a['status']) for a in arts]}")

    # 修订一份逐字稿 + 批准其余逐字稿
    for a in arts:
        if a["file_type"] == "script":
            if a["week_no"] == 3:
                req("POST", f"/api/artifact/{a['id']}/revise", {"feedback": "思政点再自然一些，结合本地案例"})
            else:
                req("POST", f"/api/artifact/{a['id']}/approve")

    # 4. 门 C：打包 + 下载校验 + 用量
    p = req("POST", f"/api/course/{cid}/package")
    if p and p.get("ok"):
        import urllib.request as _ur
        zpath = "output/e2e_package.zip"
        _ur.urlretrieve(f"{BASE}/api/course/{cid}/download", zpath)
        import zipfile
        z = zipfile.ZipFile(zpath)
        names = z.namelist()
        print(f"  zip 内容: {names}")
        assert any(n.endswith(".docx") for n in names), "zip 缺少 docx"
        assert "《课程文件夹索引与使用说明》.docx" in names, "缺少索引说明"
        print("[OK] zip 解压校验通过（含索引说明与产物 docx）")
    u = req("GET", f"/api/course/{cid}/usage")
    if u:
        print(f"  用量: 调用 {u['calls']} 次, 费用 ¥{u['cost']}, "
              f"token in {u['in_tokens']} out {u['out_tokens']}")

    # 5. 对话总控（演示模式关键词解析）
    req("POST", f"/api/course/{cid}/chat", {"text": "生成第2-3周教学包"})

    print(f"\n===== 通过 {PASS} / 失败 {FAIL} =====")


if __name__ == "__main__":
    main()
