"""截图工具 — 设备屏幕留存

注册为 mobilerun MobileAgent 自定义工具。
通过 ctx.driver (DeviceDriver) 操作设备屏幕。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mobilerun.agent.action_context import ActionContext

# core/tools/verify_tools.py → 上跳两级到 automobile/（共享层根目录）。
# screenshots / reports 是最外层共享基础能力，所有叶子节点共用。
SKILL_ROOT = Path(__file__).resolve().parents[2]
SCREENSHOT_BASE = SKILL_ROOT / "screenshots"
RUN_CONTEXT_PATH = SKILL_ROOT / "reports" / "run_context.json"


def _screenshot_dir() -> Path:
    """按当前运行的 order_id 归档截图目录。

    order_id 取自 reports/run_context.json（唯一可信来源）。读不到时
    回退到 screenshots/_no_order/，避免散落在 screenshots/ 根目录。
    """
    order_id = ""
    try:
        ctx = json.loads(RUN_CONTEXT_PATH.read_text(encoding="utf-8"))
        order_id = str(ctx.get("order_id") or "").strip()
    except (OSError, ValueError):
        order_id = ""
    sub = order_id if order_id else "_no_order"
    target = SCREENSHOT_BASE / sub
    target.mkdir(parents=True, exist_ok=True)
    return target


async def capture_screenshot(
    step_name: str = "",
    ctx: ActionContext | None = None,
) -> str:
    """截取当前设备屏幕并保存到本地文件。

    DeviceDriver.screenshot() → bytes，直接写入文件。
    文件按订单号归档：screenshots/{order_id}/{timestamp}_{step_name}.png
    """
    timestamp = int(time.time())
    safe_name = step_name.replace(" ", "_") if step_name else "screenshot"
    filename = f"{timestamp}_{safe_name}.png"
    filepath = _screenshot_dir() / filename

    if ctx is not None and ctx.driver is not None:
        screenshot_bytes: bytes = await ctx.driver.screenshot()
        filepath.write_bytes(screenshot_bytes)
    return str(filepath)


VERIFY_TOOLS: dict = {
    "capture_screenshot": {
        "description": "截取当前屏幕并保存到本地文件",
        "parameters": {
            "step_name": {"type": "string", "description": "步骤名称，用于文件名"},
        },
        "function": capture_screenshot,
    },
}
