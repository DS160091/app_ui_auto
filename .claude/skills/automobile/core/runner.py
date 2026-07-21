"""回归测试主入口"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path

import yaml
from mobilerun import MobileAgent, MobileConfig

from models import TestResult, SuiteReport
from tools import get_custom_tools

logger = logging.getLogger("autotest")


def _patch_sdk_inference_timeout() -> None:
    """收紧 mobilerun SDK 的应用级 LLM 超时。

    根因：mobilerun 的 `acall_with_retries` / `acomplete_with_retries` /
    `astructured_predict_with_retries` 把 `timeout` 默认写死 500 秒，而 Manager /
    Executor 等调用方都不显式传 timeout（见 manager_agent.py:493 等），实际走的就是
    这个 500s。streaming 模式下若网关返回 200 后 SSE 流中途僵死（连接不断但不再
    吐 token），`asyncio.wait_for(stream_chunks(), timeout=500)` 要干等满 500 秒才触发
    TimeoutError，表现为 runner 卡死 8 分钟以上。

    注意：runner 此前在 LLMProfile.kwargs 注入的 timeout 是 llama-index Anthropic
    *客户端构造器* 的底层 HTTP 超时，与这里的 *应用级* asyncio.wait_for 超时是两层，
    .env 的 LLM_TIMEOUT 之前覆盖不到这一层。本函数把应用级默认超时改为 .env 的
    LLM_TIMEOUT，真卡死时 SDK 自身就会超时并按 retries 重试，无需人工 kill。

    实现：调用方都是 `from ...inference import acall_with_retries`，绑定到同一函数
    对象，故改函数对象的 __defaults__（timeout 位于索引 1）即对所有调用方生效。
    """
    try:
        from mobilerun.agent.utils import inference
    except Exception as e:  # SDK 结构变动时不应阻断主流程
        logger.warning("跳过 SDK 超时收紧：导入 inference 失败：%s", e)
        return

    app_timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
    patched = []
    for name in ("acall_with_retries", "acomplete_with_retries", "astructured_predict_with_retries"):
        fn = getattr(inference, name, None)
        if fn is None or not getattr(fn, "__defaults__", None):
            continue
        defaults = list(fn.__defaults__)
        # 期望布局 (retries, timeout, delay, ...)；仅当索引 1 确为旧的 500s 才改，避免误伤。
        if len(defaults) >= 2 and defaults[1] == 500:
            defaults[1] = app_timeout
            fn.__defaults__ = tuple(defaults)
            patched.append(name)
    if patched:
        logger.info("已收紧 SDK 应用级 LLM 超时 → %ss（%s）", app_timeout, ", ".join(patched))

def _patch_skip_portal_update() -> None:
    """跳过 mobilerun 初始化时的 Portal 版本探活与升级下载。

    根因：runner 初始化 SDK（MobileAgent/AndroidDriver.connect）时会跑 portal
    健康检查，调 `get_compatible_portal_version` → `get_version_mapping` 拉 GitHub
    取最新版本；本机版本落后即触发 `setup_portal` 从 release-assets.githubusercontent.com
    下 APK。国内网络不可达，卡死在 "Downloading Portal APK"。

    doctor 走 `doctor_no_update.py` 已 patch 跳过，但 runner 是另一条初始化路径，
    此前没打同款 patch。这里把 `mobilerun.portal.get_version_mapping` 拦成返回 None：
    `get_compatible_portal_version` 随即返回 (None, "", False)，portal.py 的
    `needs_upgrade` 恒为 False，跳过下载。Portal 本就 installed、版本不匹配可忽略。
    """
    try:
        import mobilerun.portal as _portal
        _portal.get_version_mapping = lambda *a, **kw: None
        logger.info("已跳过 Portal 版本探活与升级下载（get_version_mapping → None）")
    except Exception as e:  # SDK 结构变动时不应阻断主流程
        logger.warning("跳过 Portal 升级 patch 失败：%s", e)


ROOT = Path(__file__).resolve().parent          # core/
SKILL_ROOT = ROOT.parent                          # automobile/（共享层根目录）
CONFIG_PATH = ROOT / "config" / "config.yaml"
# 叶子节点（业务线/App/品类/场景）可经 LEAF_DIR 环境变量指定；缺省回退到当前样例叶子。
LEAF_DIR = Path(
    os.environ.get(
        "LEAF_DIR",
        str(SKILL_ROOT / "businessLine" / "demo" / "settings" / "network"),
    )
)
CASES_PATH = LEAF_DIR / "cases" / "cases.yaml"
# .env / reports / screenshots 是最外层共享基础能力，位于 automobile 根目录。
ENV_PATH = SKILL_ROOT / ".env"
REPORT_DIR = SKILL_ROOT / "reports"
DEFAULT_TIMEOUT = 1500

# key: 字段名 → (label, 默认值, 是否隐藏输入)
CONFIG_FIELDS: dict[str, tuple[str, str, bool]] = {
    "DECISION_API_KEY": ("决策模型 API Key（Manager / App Opener / 结构化输出）", "", True),
    "DECISION_MODEL": ("  └─ 模型", "claude-opus-4-8", False),
    "DECISION_BASE_URL": ("  └─ Base URL", "https://api.anthropic.com", False),
    "EXECUTOR_PROVIDER": ("Executor 视觉模型 Provider", "Anthropic", False),
    "EXECUTOR_MODEL": ("  └─ 模型", "claude-sonnet-4-6", False),
    "EXECUTOR_API_KEY": ("  └─ API Key", "", True),
    "EXECUTOR_BASE_URL": ("  └─ Base URL", "https://api.anthropic.com", False),
}

# provider 名 → SDK 约定 env var
PROVIDER_KEY_MAP: dict[str, str] = {
    "OpenAI": "OPENAI_API_KEY",
    "Anthropic": "ANTHROPIC_API_KEY",
    "GoogleGenAI": "GOOGLE_API_KEY",
    "DeepSeek": "DEEPSEEK_API_KEY",
}


def _load_env_file() -> None:
    """从 .env 文件加载环境变量（不覆盖已有的）。"""
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _save_env_file(**kwargs: str) -> None:
    """写入 .env 文件：已有 Key 且非空则保留，否则写入新值。"""
    lines: list[str] = []
    updated: set[str] = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                lines.append(line)
                continue
            key, _, existing_value = stripped.partition("=")
            key = key.strip()
            if key in kwargs and not existing_value.strip().strip('"').strip("'"):
                lines.append(f"{key}={kwargs[key]}")
                updated.add(key)
            else:
                lines.append(line)
    # 追加全新的 Key
    for key, value in kwargs.items():
        if key not in updated:
            lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sync_provider_keys() -> None:
    """将各角色 API Key 映射到 provider SDK 约定的 env var。

    决策角色（manager/app_opener/structured_output）走 Anthropic provider，
    Executor 走 EXECUTOR_PROVIDER；SDK 按 provider 名查对应 env（如 ANTHROPIC_API_KEY），
    故两组 key 都要同步过去。用自建/第三方网关且注入 Bearer 头鉴权时，
    这里同步只为满足 SDK 构造时"provider 必须有 api_key"的校验。
    """
    pairs = [
        ("Anthropic", os.environ.get("DECISION_API_KEY", "")),
        (os.environ.get("EXECUTOR_PROVIDER", ""), os.environ.get("EXECUTOR_API_KEY", "")),
    ]
    for provider, api_key in pairs:
        if not provider or not api_key:
            continue
        target = PROVIDER_KEY_MAP.get(provider)
        if target and target not in os.environ:
            os.environ[target] = api_key


def ensure_config() -> None:
    """确保配置完整：环境变量 → .env → 交互式输入。"""
    _load_env_file()

    missing: dict[str, tuple[str, str, bool]] = {}
    for field, (desc, default, _) in CONFIG_FIELDS.items():
        if not os.environ.get(field):
            missing[field] = (desc, default, CONFIG_FIELDS[field][2])

    if not missing:
        return

    print("🔑 请配置以下参数（有默认值的回车使用默认值，API Key 必填）：\n")
    values: dict[str, str] = {}
    for field, (desc, default, secret) in missing.items():
        while True:
            default_hint = f" [{default}]" if default else ""
            prompt = f"  {desc}{default_hint}:"
            if secret:
                raw = getpass(f"{prompt}\n  > ").strip()
            else:
                raw = input(f"{prompt}\n  > ").strip()
            value = raw if raw else default
            # API Key 字段不允许为空，否则后续流程会因缺失 Key 而中断
            if secret and not value:
                print(f"  ⚠️  {desc} 不能为空，请重新输入。\n")
                continue
            values[field] = value
            break

    _save_env_file(**values)
    for field, value in values.items():
        if value:
            os.environ[field] = value

    print("\n✅ 已保存到 automobile/.env，下次运行无需重新输入。\n")


async def run_case(case: dict, config: MobileConfig) -> TestResult:
    goal = case["goal"]
    case_config = config
    if (ms := case.get("max_steps")) and ms != config.agent.max_steps:
        from dataclasses import replace
        case_config = replace(config, agent=replace(config.agent, max_steps=ms))

    agent = MobileAgent(
        goal=goal,
        config=case_config,
        custom_tools=get_custom_tools(),
        timeout=DEFAULT_TIMEOUT,
    )

    start = time.time()
    step_count = 0
    try:
        handler = agent.run()
        async for ev in handler.stream_events():
            cls = type(ev).__name__
            if cls == "ManagerPlanDetailsEvent":
                step_count += 1
                sub = (getattr(ev, "subgoal", "") or "").strip().replace("\n", " ")
                if len(sub) > 100:
                    sub = sub[:100] + "…"
                # 注意：这是 MobileRun Manager 的「决策轮次」，不是 goal/GOAL_TEXT 的步号。
                # Manager 会把单个 goal 动作拆成多轮决策，故此计数与 cases.yaml 的步号不一一对应。
                logger.info("▶ [Manager 第%d轮决策] subgoal: %s", step_count, sub)
            elif cls == "ExecutorActionEvent":
                desc = (getattr(ev, "description", "") or "").strip().replace("\n", " ")
                if len(desc) > 120:
                    desc = desc[:120] + "…"
                logger.info("  ↳ action: %s", desc)
            elif cls == "ExecutorActionResultEvent":
                ok = "✓" if getattr(ev, "success", False) else "✗"
                summary = (getattr(ev, "summary", "") or "").strip().replace("\n", " ")
                if len(summary) > 120:
                    summary = summary[:120] + "…"
                err = (getattr(ev, "error", "") or "").strip()
                tail = summary if summary else err
                logger.info("  ↳ result %s %s", ok, tail)
        result = await handler
        return TestResult(
            case_name=case["name"],
            passed=result.success,
            failure_reason=result.reason if not result.success else None,
            steps_taken=result.steps,
            duration_seconds=round(time.time() - start, 1),
        )
    except Exception as e:
        return TestResult(
            case_name=case["name"],
            passed=False,
            failure_reason=str(e),
            duration_seconds=round(time.time() - start, 1),
        )


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

    ensure_config()
    _sync_provider_keys()
    _patch_skip_portal_update()
    _patch_sdk_inference_timeout()

    config = MobileConfig.from_yaml(str(CONFIG_PATH))

    # .env 配置覆盖 config.yaml 默认值
    from dataclasses import replace
    llm = config.llm_profiles
    overrides: dict[str, dict[str, str]] = {}
    # manager / app_opener / structured_output 三个决策角色默认走 Anthropic 协议。
    # 决策角色用强推理模型（见 .env DECISION_MODEL，如 claude-opus-4-8）；模型名一律取自配置，代码不写死。
    # 若 LLM_AUTH_BEARER=1（自建/第三方网关要求 Bearer 鉴权），决策角色强制用 Anthropic provider
    # 走 /v1/messages，并在下方注入 Authorization: Bearer 头（官方端点默认用 x-api-key，无需开启）。
    DECISION_ROLES = ("manager", "app_opener", "structured_output")
    decision_base = os.environ.get("DECISION_BASE_URL", "")
    use_bearer = os.environ.get("LLM_AUTH_BEARER", "").strip() in ("1", "true", "True", "yes")
    for role in DECISION_ROLES:
        if use_bearer:
            overrides.setdefault(role, {})["provider"] = "Anthropic"
        if os.environ.get("DECISION_MODEL"):
            overrides.setdefault(role, {})["model"] = os.environ["DECISION_MODEL"]
        if decision_base:
            overrides.setdefault(role, {})["base_url"] = decision_base
    if os.environ.get("EXECUTOR_PROVIDER"):
        overrides.setdefault("executor", {})["provider"] = os.environ["EXECUTOR_PROVIDER"]
    if os.environ.get("EXECUTOR_MODEL"):
        overrides.setdefault("executor", {})["model"] = os.environ["EXECUTOR_MODEL"]
    if os.environ.get("EXECUTOR_BASE_URL"):
        overrides.setdefault("executor", {})["base_url"] = os.environ["EXECUTOR_BASE_URL"]
    # 部分自建/第三方网关走 Bearer 鉴权，而 llama-index 的 Anthropic 默认发 x-api-key（会 401）。
    # 开启 LLM_AUTH_BEARER 后，对用 Anthropic provider 的角色注入 Authorization: Bearer 头。
    decision_key = os.environ.get("DECISION_API_KEY", "")
    exec_provider = os.environ.get("EXECUTOR_PROVIDER", "")
    exec_base = os.environ.get("EXECUTOR_BASE_URL", "")
    exec_key = os.environ.get("EXECUTOR_API_KEY", "")
    # (role, 该角色最终的 provider, base_url, key)
    bearer_targets = [
        (role, "Anthropic", decision_base, decision_key) for role in DECISION_ROLES
    ] + [("executor", exec_provider, exec_base, exec_key)]
    # LLM 单次请求超时与重试上限：llama-index Anthropic 默认 timeout=None（回落 anthropic SDK 的
    # 10 分钟）、max_retries=10，一旦某次连接僵死会无限干等并重试，导致 runner 长时间卡死。
    # LLMProfile.kwargs 会被 to_load_llm_kwargs 原样透传给 Anthropic(...) 构造器（default_headers
    # 已验证可生效），故在此一并注入 timeout/max_retries 覆盖默认值。两值均从 .env 读，带兜底默认。
    llm_timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
    llm_max_retries = int(os.environ.get("LLM_MAX_RETRIES", "2"))
    # 注：llama-index 的 Anthropic 只接受 float 型 timeout（传 httpx.Timeout 会被 pydantic 拒绝）。
    # anthropic SDK 收到 float 后会应用到所有分量（含 read），故标量 llm_timeout 即可覆盖 read 超时。
    for role, provider, base, key in bearer_targets:
        if use_bearer and provider == "Anthropic" and key:
            existing_kwargs = dict(getattr(llm.get(role), "kwargs", {}) or {})
            headers = dict(existing_kwargs.get("default_headers", {}))
            headers["Authorization"] = f"Bearer {key}"
            existing_kwargs["default_headers"] = headers
            existing_kwargs.setdefault("timeout", llm_timeout)
            existing_kwargs.setdefault("max_retries", llm_max_retries)
            overrides.setdefault(role, {})["kwargs"] = existing_kwargs
    if overrides:
        new_profiles = {
            role: replace(profile, **overrides[role]) if role in overrides else profile
            for role, profile in llm.items()
        }
        config = replace(config, llm_profiles=new_profiles)

    logger.info("设备: %s | max_steps: %s | reasoning: %s", config.device.platform, config.agent.max_steps, config.agent.reasoning)

    from async_adbutils import adb
    devices = await adb.device_list()
    if config.device.serial:
        if not any(d.serial == config.device.serial for d in devices):
            logger.error("指定设备 %s 未连接，已连接: %s", config.device.serial, [d.serial for d in devices])
            return
    elif not devices:
        logger.error("无已连接 Android 设备")
        return
    logger.info("设备 %s", config.device.serial or [d.serial for d in devices])

    # 单段模式 — Claude 传入 GOAL_TEXT 时使用，不从 cases.yaml 读
    goal_text = os.environ.get("GOAL_TEXT", "").strip()
    if goal_text:
        max_steps = int(os.environ.get("MAX_STEPS", "40"))
        case = {"name": "ui_segment", "goal": goal_text, "max_steps": max_steps}
        r = await run_case(case, config)
        if not r.passed:
            logger.error("UI 段失败: %s", r.failure_reason)
        return 0 if r.passed else 1

    cases = yaml.safe_load(open(CASES_PATH, encoding="utf-8")).get("cases", [])
    if not cases:
        logger.warning("无用例")
        return
    logger.info("用例数: %s", len(cases))

    results: list[TestResult] = []
    for i, c in enumerate(cases, 1):
        logger.info("[%s/%s] %s", i, len(cases), c["name"])
        r = await run_case(c, config)
        results.append(r)
        logger.info("  %s | steps: %s | %ss%s",
                     "PASS" if r.passed else "FAIL",
                     r.steps_taken, r.duration_seconds,
                     f" | {r.failure_reason}" if r.failure_reason else "")

    total, passed = len(results), sum(1 for r in results if r.passed)
    rate = round(passed / total * 100, 1) if total else 0
    logger.info("结果: %s/%s (%s%%)", passed, total, rate)

    REPORT_DIR.mkdir(exist_ok=True)
    report = SuiteReport(
        timestamp=datetime.now().isoformat(),
        total=total, passed=passed,
        failed=total - passed, pass_rate=rate,
        results=results,
    )
    path = REPORT_DIR / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json.dump(report.model_dump(), open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    logger.info("报告: %s", path)
    return total - passed


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
