# 备课智能体 v2 · 本地部署版

> 本目录是完整的本地部署版（FastAPI + SQLite + 本地网页工作台），不再依赖任何独立的单文件网页版。

面向高校教师的「全自动备课智能体」：新建课程 → 上传资料 → 课程地图（门 A）→ 逐份生成教案/讲义/课件/逐字稿（门 B）→ 打包交付（门 C）。

借鉴豆包的工作任务模式，并把 2026-10 的《备课智能体外壳化设计方案》落到可运行的本地版：

- **对话总控**：一句话解析为结构化任务（行动 / 周次 / 文件类型 / 侧重点 / 语气），能直接执行；
- **提示词框架库**：8 套 8 要素框架（角色 / 任务 / 领域规范 / 结构 / 内容深度 / 风格 / 输出格式 / 校验），生成不再散落硬编码；
- **公共资源区**：学校模板、课程标准、教学方法论、公共案例、思政素材全校共享，按相关性注入；
- **课程知识库**：资料原文公平分配注入 + 关键词检索，资料重复上传自动去重；
- **三处确认门**：门 A 周次规划、门 B 逐文件确认、门 C 整包交付；
- **门 B 自动续跑**：批准教案自动排队生成讲义，批准讲义自动生成互动课件与逐字稿；
- **逐文件查看页**：左侧完整渲染（教案为双表格，课件为互动预览），右侧对话式修改，多轮 + 版本历史 + 一键回退；
- **互动课件双格式**：一份结构化 JSON 同时导出 16:9 PPTX（可编辑、带讲稿备注）与自包含互动 HTML（翻页、全屏、讲稿、测验/投票/讨论）；
- **多格式交付**：docx（A4 横向双表）/ PPTX / 互动 HTML / 自包含 HTML / Markdown / 浏览器打印 PDF / 整包 zip。

---

## 一、快速开始

### Windows（推荐）

1. 进入 `备课智能体演示版` 文件夹；
2. 双击 **`run.bat`**（首次会自动创建 `.venv`、安装依赖，约 2–5 分钟）；
3. 浏览器打开 **http://127.0.0.1:8000**。

若 8000 端口被占用，可把 `run.bat` 里的 `--port 8000` 改为其他端口，或用命令行：

```bat
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

### macOS / Linux

```bash
cd 备课智能体演示版
bash run.sh
```

### 配置模型（必需）

系统不会用内置模板冒充生成；未配置 Key 时，除资料解析、地图编辑、查看、导出以外，生成不可用。

1. 打开项目根目录 `.env`；
2. 填写 `LLM_API_KEY`（豆包方舟 / DeepSeek / 任意 OpenAI 兼容服务）；
3. 重启服务。

默认指向豆包方舟最新旗舰 `doubao-seed-2-1-pro-260915`；短任务（意图/摘要）可自动走轻量模型，降低成本与延迟。

---

## 二、六步流程

| 步骤 | 界面 | 说明 |
| --- | --- | --- |
| ① 课程工作台 | 新建/切换课程、进度、最近任务、对话总控 | 一句话即可驱动 |
| ② 资料库 | 上传 docx/xlsx/pdf/txt/md/csv 或粘贴文本 → 解析摘要 | 同名资料自动更新，不重复堆积 |
| ③ 课程地图 | 选周次 → 生成/补全 → 表格内编辑 → **门 A 批准** | 主题/学时/目标/思政点；改已批准周次自动退回 |
| ④ 生成中心 | 选周次与文件类型 → 后台任务 → 进度/日志/矩阵 | 教案 →（批准）→ 讲义 →（批准）→ 课件 + 逐字稿；可取消 |
| ⑤ 确认中心 | 预览 + 校验提示 + 批准/修改/版本 | **门 B**；课件可内嵌互动预览，批准后按开关自动续跑下游 |
| ⑥ 交付与用量 | 打包 zip / 单文件导出 / 费用统计 | **门 C**；docx / PPTX / 互动 HTML / Markdown |

**门 A 语义**：批准的是「周次规划」，不是产物。修改已批准周次的主题、学时、目标或思政点，会自动退回待确认，避免地图与产物不一致。

**门 B 语义**：教案/讲义完稿后进入待确认；未批准时下游保持等待。开启「批准后自动续跑」后，批准教案自动生成讲义，批准讲义自动生成互动课件与逐字稿，无需重复点生成。

**门 C 语义**：只有已定稿（approved）的文件才进入 zip；未定稿不会被误打包。

---

## 三、v2 主要优化

### 1. 生成质量

- 教案严格执行学校横版双表：表一 12 栏目、表二 5 列、环节 4–6 个、时间合计 = 学时 × 45；
- 反模板化：提示词明确禁止「讲授本课核心概念」「学生分组讨论」等套话，校验器检测命中并提示；
- 自动修复：校验不通过时，自动让模型只修结构（不重写内容）一次，问题减少才采用，并在界面标注；
- 上下文装配：公共资源 → 课程资料原文 → 针对性检索 → 本次侧重/语气；多份资料公平分配，超长显式标注截断；
- 周间记忆：上周教案摘要注入下周，开头自然承接；
- 校验维度：栏目齐全、表格列、时间合计、字数、舞台指示、套话、重复句、讲义环节对应、逐字稿可照念性。

### 2. 体验

- 全新工作台：课程进度、下一步建议、最近任务、确认记录、对话总控；
- 课程地图表格可编辑并自动保存，支持逐周 AI 重写；
- 生成进度按「本轮要处理的文件数」计算，跳过项写明原因；
- 所有长操作有按钮 loading 与顶部进度条；删除、重置等有自定义确认弹窗；
- 逐文件查看页：双表渲染、校验提示、多轮对话修改、版本回退、打印/PDF；
- 公共资源区可增删改停用，提示词框架可逐项查看 8 要素。

### 3. 可靠性

- 数据层迁移兼容 v1（自动补列、建索引、唯一约束）；
- 资料同名更新、摘要原地更新，不再重复插入；
- 后台任务持久化：服务重启后「运行中」任务标记为已中断，不再假运行；
- 生成失败自动重试 1 次，仍失败标记 failed 并可在确认中心重试；
- 网关对 401/403/404/429/超时/网络错误给出可操作提示，限流与 5xx 自动重试一次；
- 上传按魔数校验真实格式，明确提示旧版 .doc/.xls 需另存；支持 CSV。

---

## 四、目录结构

```
备课智能体演示版/
├── run.bat / run.sh            # 一键启动
├── requirements.txt
├── .env.example                # 配置模板（复制为 .env）
├── app/
│   ├── config.py               # 路径、模型、限制、刊例价
│   ├── gateway.py              # 统一网关：多厂商 + 轻量模型 + 重试 + 计量
│   ├── store.py                # SQLite：课程/资料/地图/产物/版本/任务/公共资源/用量
│   ├── frameworks.py           # 提示词框架库（8 套 × 8 要素）
│   ├── rag.py                  # 分块检索 + 上下文装配（公共 → 课程 → 需求）
│   ├── courseware.py           # 课件 JSON → PPTX / 互动 HTML
│   ├── render.py               # docx / HTML / Markdown / 索引 / zip
│   ├── main.py                 # FastAPI 接口
│   ├── agent/
│   │   ├── intent.py           # 一句话 → 结构化任务（LLM + 规则兜底）
│   │   ├── prompts.py          # 框架 + 上下文 → messages
│   │   ├── tools.py            # 生成/校验/修复/修订/确认/地图
│   │   └── orchestrator.py     # 工作流引擎、依赖链、自动续跑、对话执行
│   └── static/
│       ├── index.html          # 工作台单页
│       ├── styles.css / app.js / md.js
│       └── viewer.html         # 逐文件查看页
├── tests/
│   ├── smoke_test.py           # 无 Key 端到端冒烟（假模型，53 项断言）
│   ├── seed_demo.py            # 生成演示数据
│   └── check_docx.py           # 检查 docx 版式
└── output/                     # 打包 zip
```

---

## 五、接口一览（本地）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/system/info` | 模式、模型、限制、技能、框架统计 |
| GET | `/api/courses` | 课程列表（含资料/产物统计） |
| POST | `/api/course` | 新建课程 |
| PATCH/DELETE | `/api/course/{cid}` | 更新/删除课程 |
| GET | `/api/course/{cid}/board` | 工作台全量数据 |
| POST | `/api/course/{cid}/material` | 上传资料（multipart） |
| POST | `/api/course/{cid}/material-text` | 粘贴资料 |
| POST | `/api/course/{cid}/parse` | 解析并生成摘要 |
| POST | `/api/course/{cid}/plan` | 生成课程地图（门 A） |
| PATCH | `/api/course/{cid}/plan/{week}` | 编辑周次（已批准自动退回） |
| POST | `/api/course/{cid}/plan/approve` | 批准周次 |
| POST | `/api/course/{cid}/generate` | 启动生成任务 |
| GET | `/api/task/{tid}` | 任务状态/进度/日志 |
| POST | `/api/task/{tid}/cancel` | 取消任务 |
| GET | `/api/artifact/{aid}` | 产物详情 + 校验 + 版本 |
| POST | `/api/artifact/{aid}/approve` | 门 B 批准（可自动续跑） |
| POST | `/api/artifact/{aid}/revise` | 带反馈修改 |
| GET | `/api/artifact/{aid}/export?fmt=docx|html|md` | 导出 |
| GET | `/viewer/{cid}/{aid}` | 逐文件查看页 |
| POST | `/api/course/{cid}/artifact/{aid}/edit` | 查看页对话修改 |
| POST | `/api/course/{cid}/chat` | 对话总控（解析 + 执行） |
| GET/POST/PATCH/DELETE | `/api/vault` | 公共资源区 |
| GET | `/api/frameworks` | 提示词框架库 |
| POST | `/api/course/{cid}/package` | 打包（门 C） |
| GET | `/api/course/{cid}/download` | 下载最新 zip |

---

## 六、验证

### 1. 端到端冒烟（无需 Key）

```bash
# Windows
set KB_SMOKE_DIR=%TEMP%\kb-smoke
.venv\Scripts\python -X utf8 tests\smoke_test.py

# macOS / Linux
KB_SMOKE_DIR=/tmp/kb-smoke .venv/bin/python -X utf8 tests/smoke_test.py
```

脚本会替换模型网关为假模型、真实启动 uvicorn，覆盖：建课 → 资料去重/CSV → 解析 → 地图 → 批准 → 生成教案 → 自动续跑讲义 → 自动续跑课件与逐字稿 → 修订 → 版本回退 → 三种格式导出 → 课件 JSON/PPTX/互动 HTML → 打包/下载 → 对话执行 → 公共资源 CRUD → 用量计量。共 53 项断言。

### 2. 演示数据

```bash
set KB_DEMO_DIR=%TEMP%\kb-demo
.venv\Scripts\python -X utf8 tests\seed_demo.py
```

生成一份含 5 周地图、3 份定稿、2 份待确认、1 份失败的演示数据库，便于检查界面。

### 3. docx 版式

```bash
.venv\Scripts\python -X utf8 tests\check_docx.py http://127.0.0.1:8000 4
```

会打印页面方向（A4 横向）、页眉、表一/表二行列数、列宽，便于确认导出符合学校模板。

---

## 七、配置项（.env）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 空 | 主模型 Key；空 = 未配置模式 |
| `LLM_BASE_URL` | 火山方舟 v3 | OpenAI 兼容服务根地址 |
| `LLM_MODEL` | `doubao-seed-2-1-pro-260915` | 主模型 |
| `LLM_LITE_API_KEY` / `LLM_LITE_MODEL` | 空 / lite | 短任务轻量模型（可选） |
| `LLM_TIMEOUT` | 360 | 单次调用超时（秒）；长文生成慢时可调到 420–600 |
| `PORT` | 8000 | 本地端口 |
| `SCHOOL_NAME` | 阳泉师范高等专科学校 | 导出页眉/界面学校名 |
| `MAX_UPLOAD_MB` | 20 | 单文件上传上限 |
| `MAX_MATERIAL_CHARS` | 200000 | 单份资料保留字符 |
| `MAX_CONTEXT_CHARS` | 16000 | 资料注入总长度 |
| `AUTO_REPAIR` | 1 | 校验不通过是否自动修复一次 |
| `DB_PATH` / `OUTPUT_DIR` | 项目内 | 数据库/输出目录（测试可覆盖） |
| `PRICING_*` | 内置刊例 | 元/百万 token，估算用 |

---

## 八、与生产版的差异

- 单机 SQLite + 本地文件，未接学校统一账号、Vault 密钥托管、配额熔断、多租户；
- 逐字稿为两段生成（约 3000–5000 字），生产版可继续分段扩到 8000–12000；
- 交付为 docx / PPTX / 互动 HTML / Markdown / 打印 PDF；文生图、课件 animations 与视频尚未接入；
- 公共资源区为单机 SQLite 种子 + 手工维护，生产版为全校共享库 + 管理员后台；
- 知识库为关键词检索（无向量库/重排/OCR），扫描件 PDF 仍需先转文本。

> 以上差异不影响本地演示「从一句话到整包教学资料」的完整闭环。

---

## 九、技术栈

Python 3.10+ · FastAPI · SQLite（WAL）· 原生 JS 单页前端 · python-docx · openpyxl · pypdf · OpenAI 兼容客户端。
