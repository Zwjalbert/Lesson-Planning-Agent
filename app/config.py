# -*- coding: utf-8 -*-
"""全局配置（v2）。

读取 .env，判定运行模式，并集中管理路径、上传限制、上下文长度等参数。
所有路径均可用环境变量覆盖，便于测试与部署。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(name: str, default: Path) -> Path:
    raw = (os.getenv(name) or "").strip()
    return Path(raw).expanduser().resolve() if raw else default


OUTPUT_DIR = _path("OUTPUT_DIR", ROOT / "output")
DB_PATH = _path("DB_PATH", ROOT / "data.db")
STATIC_DIR = ROOT / "app" / "static"

PORT = int(os.getenv("PORT", "8000"))
APP_VERSION = "2.0.0"

# ---- 学校与模板 ----
SCHOOL_NAME = (os.getenv("SCHOOL_NAME") or "").strip() or "阳泉师范高等专科学校"
DOC_HEADER = (os.getenv("DOC_HEADER") or "").strip() or f"{SCHOOL_NAME}教案"

# ---- 主模型（默认最新豆包旗舰）----
LLM_API_KEY = (os.getenv("LLM_API_KEY") or "").strip()
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or "").strip() or "https://ark.cn-beijing.volces.com/api/v3"
LLM_MODEL = (os.getenv("LLM_MODEL") or "").strip() or "doubao-seed-2-1-pro-260915"
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "360"))

# ---- 轻量模型（摘要、意图、修订等短任务，可选）----
LLM_LITE_API_KEY = (os.getenv("LLM_LITE_API_KEY") or "").strip()
LLM_LITE_BASE_URL = (os.getenv("LLM_LITE_BASE_URL") or "").strip()
LLM_LITE_MODEL = (os.getenv("LLM_LITE_MODEL") or "").strip() or "doubao-seed-2-1-lite-260915"

# ---- 运行模式 ----
# real：已配置 key，全部生成环节真实调用大模型；
# no_key：未配置 key，生成不可用（界面给出配置指引），不再使用内置模板冒充生成。
MODE = "real" if LLM_API_KEY else "no_key"

# ---- 生成与上传限制 ----
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_MATERIAL_CHARS = int(os.getenv("MAX_MATERIAL_CHARS", "200000"))   # 单份资料最多保留字符
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "16000"))      # 资料全文注入上限
VAULT_TOP_K = int(os.getenv("VAULT_TOP_K", "3"))
AUTO_REPAIR = (os.getenv("AUTO_REPAIR", "1").strip() not in ("0", "false", "False"))
MAX_TASK_KEEP = int(os.getenv("MAX_TASK_KEEP", "60"))

# ---- 内置刊例价（元/百万 token：输入,输出），估算值，可在 .env 修改 ----
def _price(s: str, default: str):
    raw = (s or default).strip()
    try:
        a, b = raw.split(",")
        return float(a), float(b)
    except Exception:
        return tuple(float(x) for x in default.split(","))


PRICING = {
    "doubao-seed-pro": _price(os.getenv("PRICING_DOUBAO_SEED_PRO", ""), "6.0,30.0"),
    "doubao-seed-lite": _price(os.getenv("PRICING_DOUBAO_SEED_LITE", ""), "3.0,12.0"),
    "doubao-pro": _price(os.getenv("PRICING_DOUBAO_PRO", ""), "2.0,8.0"),
    "doubao-lite": _price(os.getenv("PRICING_DOUBAO_LITE", ""), "0.8,2.0"),
    "deepseek": _price(os.getenv("PRICING_DEEPSEEK", ""), "2.0,8.0"),
    "openai": _price(os.getenv("PRICING_OPENAI", ""), "15.0,60.0"),
}

# 短任务走轻量模型（成本更低、速度更快）；结构修复要重写全文，仍走主模型
LITE_TASKS = {"intent", "summary", "validate", "title"}


def model_price(model: str):
    """按模型名粗匹配刊例价，返回 (输入价, 输出价) 元/百万 token。"""
    m = (model or "").lower()
    if "seed-2-1-lite" in m or "seed-2-0-lite" in m or "seed-lite" in m or "seed-2-1-turbo" in m:
        return PRICING["doubao-seed-lite"]
    if "seed" in m or "evolving" in m:
        return PRICING["doubao-seed-pro"]
    if "lite" in m or "flash" in m or "mini" in m:
        return PRICING["doubao-lite"]
    if "deepseek" in m:
        return PRICING["deepseek"]
    if "gpt" in m or m.startswith("o1") or m.startswith("o3"):
        return PRICING["openai"]
    return PRICING["doubao-pro"]


def lite_ready() -> bool:
    return bool(LLM_LITE_API_KEY or LLM_LITE_BASE_URL)


def info() -> dict:
    """供前端展示的系统信息。"""
    return {
        "version": APP_VERSION,
        "mode": MODE,
        "model": LLM_MODEL,
        "base_url": LLM_BASE_URL,
        "lite_model": LLM_LITE_MODEL if lite_ready() else None,
        "school": SCHOOL_NAME,
        "pricing": {k: list(v) for k, v in PRICING.items()},
        "limits": {
            "max_upload_mb": MAX_UPLOAD_MB,
            "max_material_chars": MAX_MATERIAL_CHARS,
            "max_context_chars": MAX_CONTEXT_CHARS,
            "auto_repair": AUTO_REPAIR,
            "llm_timeout": LLM_TIMEOUT,
        },
        "features": [
            "对话总控（结构化意图）", "课程地图门A（可逐周编辑）", "教案/讲义/课件/逐字稿依赖链",
            "课件 PPTX + 互动 HTML 双格式", "门B 逐文件确认与对话修改", "修改历史与版本回退", "自动续跑下游",
            "公共资源区注入", "提示词框架库", "docx/HTML/Markdown 导出", "整包 zip 交付",
        ],
        "note": (
            f"真实模式：全部生成内容由 AI 大模型产出（{LLM_MODEL}），费用按内置刊例估算、以账号账单为准"
            if MODE == "real"
            else "未配置 API Key：系统不会用模板冒充生成，请在 .env 配置 LLM_API_KEY（或查看配置指引）后使用"
        ),
    }


# 启动时确保目录存在（失败时由调用方给出可读错误）
try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:  # pragma: no cover - 只读环境下由接口层提示
    pass
