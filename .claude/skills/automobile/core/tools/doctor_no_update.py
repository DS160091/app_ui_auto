"""调用 mobilerun doctor，但跳过 GitHub 版本探活与 Portal 升级下载。

直接跑 `mobilerun doctor` 时 CLI 会拉 GitHub 取最新 Portal 版本；本机落后时
还会自动从 release-assets.githubusercontent.com 下 APK。国内网络默认不可达，
每次预检会卡 30s 左右才超时。

本脚本 monkey-patch 以下出网函数：
- mobilerun.portal.get_version_mapping         → None
- mobilerun.cli.doctor._get_latest_portal_version → None
- mobilerun.cli.main._setup_portal             → no-op（关键）

为什么只 patch 前两个不够（SDK 0.6.0rc3 实测）：
doctor.py 的升级分支判定是 `r_version.status == WARN and installed_ver`。
把版本探活 patch 成 None 后确实进了 WARN 分支，但 installed_ver（本机已装版本，
如 v0.7.9）非空，于是照样调 `_setup_portal(path=None)` → fallback to latest
→ 去 GitHub 下 APK，国内网络卡死。Portal 本就 installed、版本 WARN 可忽略，
故把 _setup_portal 直接拦成 no-op，doctor 跳过下载、继续跑完 Accessibility /
Content Provider / Screenshot 等剩余核心项。

doctor.py 内是运行时局部 `from mobilerun.cli.main import _setup_portal`，故
patch 模块属性 `_main._setup_portal` 能生效。

预检 common_playbook.md §1.5 调用本脚本。
"""

import sys

import mobilerun.cli.doctor as _doctor
import mobilerun.cli.main as _main
import mobilerun.portal as _portal

_portal.get_version_mapping = lambda *a, **kw: None
_doctor._get_latest_portal_version = lambda: None


async def _skip_setup_portal(*a, **kw):
    # Portal 已 installed，版本 WARN 可忽略：跳过升级下载，避免国内网络卡死
    print("  [patched] skip _setup_portal (portal already installed)")
    return None


_main._setup_portal = _skip_setup_portal

from mobilerun.cli.main import cli  # noqa: E402

if __name__ == "__main__":
    sys.argv = ["mobilerun", "doctor"]
    cli()
