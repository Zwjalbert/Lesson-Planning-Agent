# -*- coding: utf-8 -*-
"""统一模型网关（v2）。

设计目标：
  1. 智能体不直接绑定任何供应商 —— 全部经本网关调用，支持多厂商切换；
  2. 统一 OpenAI 兼容协议：豆包方舟 / DeepSeek / 任意 OpenAI 兼容服务；
  3. 每次调用记录用量（模型、输入/输出 token、费用、耗时、trace_id），写入 SQLite；
  4. 短任务（意图/摘要/校验）自动走轻量模型，降低成本与延迟，长文修复仍走主模型；
  5. 未配置 key 时明确报错，不静默降级到模板内容；
  6. 对 429 / 超时 / 5xx 做有限重试，对不支持 response_format 的模型自动降级重试。

演示版不包含：多厂商主备自动切换的探活（生产版在网关做）、请求前额度硬校验。
"""
import time
import uuid
from typing import List, Optional

from openai import OpenAI

from . import config

_TRACE_SEQ = [0]


class GatewayError(Exception):
    """网关调用失败（限流、超时、鉴权等），message 面向教师可直接展示。"""


def _next_trace() -> str:
    _TRACE_SEQ[0] += 1
    return f"c{int(time.time())}-{_TRACE_SEQ[0]:04d}-{uuid.uuid4().hex[:4]}"


_CLIENTS = {}


def _client(base_url: str, api_key: str) -> OpenAI:
    key = (base_url, api_key)
    cli = _CLIENTS.get(key)
    if cli is None:
        cli = OpenAI(api_key=api_key, base_url=base_url,
                     timeout=config.LLM_TIMEOUT, max_retries=0)
        _CLIENTS[key] = cli
    return cli


def pick_model(task: str, model: Optional[str]) -> tuple:
    """返回 (模型名, base_url, api_key)。短任务优先轻量模型。"""
    if model:
        return model, config.LLM_BASE_URL, config.LLM_API_KEY
    if task in config.LITE_TASKS and config.lite_ready() and config.LLM_LITE_API_KEY:
        return (config.LLM_LITE_MODEL,
                config.LLM_LITE_BASE_URL or config.LLM_BASE_URL,
                config.LLM_LITE_API_KEY)
    return config.LLM_MODEL, config.LLM_BASE_URL, config.LLM_API_KEY


def _status_of(e: Exception) -> int:
    code = getattr(e, "status_code", None)
    if isinstance(code, int):
        return code
    text = str(e)
    for c in (401, 403, 404, 408, 429, 500, 502, 503, 504):
        if str(c) in text:
            return c
    return 0


def _friendly(e: Exception, model: str) -> str:
    msg = str(e)
    low = msg.lower()
    code = _status_of(e)
    if code == 401 or "invalid api key" in low or "unauthorized" in low:
        return "API Key 无效或无权限（401）：请核对 Key 是否完整、是否已过期；豆包方舟与 DeepSeek 的 Key 不通用。"
    if "setlimitexceeded" in low or "safe experience mode" in low:
        return ("模型级用量上限/安全体验模式已触发（429）：账号余额充足也可能被暂停。"
                "请登录火山方舟控制台 →「开通管理/模型激活」→ 找到该模型 → "
                "调整或关闭「安全体验模式」/提高用量上限，或改用已开通且未达上限的模型/账号。")
    if "not activated" in low or "modelnotopen" in low:
        return (f"模型未开通（404）：账号尚未开通 {model}。"
                "请到火山方舟控制台「开通管理」激活该模型后再试。")
    if code == 403 or "permission" in low:
        return "接口拒绝访问（403）：请确认账号已开通该模型，且 Key 有调用权限。"
    if code == 404 or "not found" in low or "model_not_found" in low:
        return f"模型或接口地址不存在（404）：请检查模型名 {model} 与 Base URL（只填服务根地址）。"
    if code == 429 or "rate limit" in low or "quota" in low:
        if any(k in low for k in ("rpm", "tpm", "rate limit", "too many requests", "concurrency")):
            return ("触发服务端限流（429）：账号的每分钟请求数/Token 数或并发数已达上限。"
                    "请等待 1–3 分钟后重试；不要连续点击生成，批量任务完成后再操作。")
        return ("账号额度或余额不足（429）：请检查方舟账号余额、模型额度与限流设置；"
                "若余额充足，重点查看该模型的「安全体验模式」用量上限。")
    if code == 408 or "timeout" in low or "timed out" in low:
        return (f"模型响应超时（>{int(config.LLM_TIMEOUT)}s）：请求已发出，但模型未在等待上限内返回。"
                "可把 .env 的 LLM_TIMEOUT 调到 420–600 并重启服务后重试；"
                "也可以换更快的模型、减少本次资料量或降低输出长度。")
    if "connection" in low or "network" in low or "proxy" in low:
        return "无法连接模型服务：请检查网络、代理与 Base URL（如 https://ark.cn-beijing.volces.com/api/v3）。"
    if "context" in low and ("length" in low or "token" in low):
        return "输入超出模型上下文长度：请减少资料量（可只保留关键章节）后重试。"
    if "response_format" in low or "json" in low:
        return f"模型不支持 JSON 输出格式或返回异常：{msg[:160]}"
    return f"模型调用失败（{model}）：{msg[:200]}"


def chat(
    messages: List[dict],
    *,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    json_mode: bool = False,
    model: Optional[str] = None,
    task: str = "general",
    course_id: Optional[int] = None,
    week_no: Optional[int] = None,
    file_type: str = "general",
) -> dict:
    """统一 LLM 调用入口。

    返回：{"text", "model", "tokens": {"in","out"}, "cost", "trace_id", "latency_ms"}
    失败抛 GatewayError（含可读原因），由编排层决定是否重试。
    """
    if config.MODE == "no_key":
        raise GatewayError(
            "未配置 API Key：本系统所有生成内容（课程地图/教案/讲义/逐字稿）均由 AI 大模型产出，"
            "请先在 .env 中配置 LLM_API_KEY（默认使用最新豆包模型 "
            f"{config.LLM_MODEL}），重启服务后使用。")

    model_name, base_url, api_key = pick_model(task, model)
    trace_id = _next_trace()
    kwargs = dict(model=model_name, temperature=temperature, max_tokens=max_tokens)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    client = _client(base_url, api_key)

    t0 = time.time()
    last_err = None
    for attempt in (1, 2):
        try:
            resp = client.chat.completions.create(messages=messages, **kwargs)
            break
        except Exception as e:  # noqa: BLE001 - 统一转成可读错误
            last_err = e
            low = str(e).lower()
            # 模型级暂停/安全体验模式达到上限：重试无意义，直接返回可操作提示
            if "setlimitexceeded" in low or "safe experience mode" in low:
                raise GatewayError(_friendly(e, model_name)) from e
            # 部分深度思考模型不支持 response_format：去掉后重试
            if json_mode and "response_format" in kwargs and attempt == 1:
                kwargs.pop("response_format", None)
                continue
            # 限流/服务端错误/连接问题：等待后重试一次
            code = _status_of(e)
            retryable = code in (408, 429, 500, 502, 503, 504) or \
                any(k in low for k in ("timeout", "timed out", "connection", "overloaded"))
            if attempt == 1 and retryable:
                time.sleep(1.6)
                continue
            raise GatewayError(_friendly(e, model_name)) from e
    else:  # pragma: no cover - 循环必然 break 或 raise
        raise GatewayError(_friendly(last_err or Exception("unknown"), model_name))

    latency_ms = int((time.time() - t0) * 1000)
    try:
        text = (resp.choices[0].message.content or "").strip()
    except Exception:
        text = ""
    if not text:
        raise GatewayError("模型返回空内容：可能是内容审核拦截或输出被截断，请调整要求后重试。")

    usage = getattr(resp, "usage", None)
    in_t = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    out_t = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    price = config.model_price(model_name)
    cost = (in_t * price[0] + out_t * price[1]) / 1_000_000
    finish = ""
    try:
        finish = resp.choices[0].finish_reason or ""
    except Exception:
        pass

    _record_usage(trace_id, model_name, in_t, out_t, cost, course_id, week_no, file_type,
                  task, latency_ms)
    return {
        "text": text,
        "model": model_name,
        "tokens": {"in": in_t, "out": out_t},
        "cost": cost,
        "trace_id": trace_id,
        "latency_ms": latency_ms,
        "finish_reason": finish,
    }


def _record_usage(trace_id, model, in_t, out_t, cost, course_id, week_no, file_type,
                  task="", latency_ms=0):
    """写入用量表；计量失败不阻断生成（生产版此处需告警）。"""
    try:
        from . import store
        store.insert_usage(
            trace_id=trace_id, model=model, in_tokens=in_t, out_tokens=out_t,
            cost=cost, course_id=course_id, week_no=week_no, file_type=file_type,
            task=task, latency_ms=latency_ms)
    except Exception:
        pass


def estimate_tokens(text: str) -> int:
    """粗估 token（中文约 1.5 字/token），仅用于无 usage 时的兜底显示。"""
    return max(1, int(len(text or "") / 1.5))
