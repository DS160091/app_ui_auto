from .verify_tools import VERIFY_TOOLS, capture_screenshot


def get_custom_tools() -> dict:
    """合并所有自定义工具为 mobilerun custom_tools dict"""
    tools = {}
    tools.update(VERIFY_TOOLS)
    return tools


__all__ = [
    "get_custom_tools",
    "VERIFY_TOOLS",
    "capture_screenshot",
]
