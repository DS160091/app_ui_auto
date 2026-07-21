"""报告发布公共能力（所有回归流程共用，顶层编排只调一次）。

默认行为 = **只生成本地报告**：读 report.json（缺失则先生成）→ 生成 report-json
（.json + .md 两份）落盘。不请求任何网络、不依赖任何外部服务，开箱即用。

可选的「上传发布」是一个**适配层**，仅在 .env 配置了相应变量时才启用：
    - 传图：配置 PIC_UPLOAD_SIGN 后，调 pic_upload 子 skill 批量上传截图并回填 CDN 链接。
            截图上传通常需要登录态，通过 COOKIE_CMD 指定一条「输出 cookie 到 stdout」的命令。
    - 落库：配置 REPORT_UPLOAD_URL 后，调 report_upload 子 skill 把报文原文上传落库。
任一变量未配置，则对应步骤自动跳过（本地产物已生成，可后续手动补传）。

用法：
    python3 core/tools/publish_report.py <order_id>
    # order_id 省略时从 reports/run_context.json 读取

可选 .env 配置：
    PIC_UPLOAD_SIGN     图片上传标识；为空则跳过传图，截图 cdn_url 留空。
    COOKIE_CMD          取登录态 cookie 的命令（输出 cookie 到 stdout）；传图需要时配置。
    REPORT_UPLOAD_URL   报文落库接口地址；为空则跳过落库上传。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from report_schema import validate_report

ROOT = Path(__file__).resolve().parent          # core/tools/
SKILL_ROOT = ROOT.parent.parent                   # automobile/
ENV_PATH = SKILL_ROOT / ".env"
SCREENSHOT_BASE = SKILL_ROOT / "screenshots"
REPORT_BASE = SKILL_ROOT / "reports"
RUN_CONTEXT_PATH = REPORT_BASE / "run_context.json"

# pic_upload / report_upload 均为 automobile 的子 skill，统一收在 automobile/sub_skills/ 下，
# 由 automobile 编排内部调用（不再是可 /pic_upload 单独调用的顶层 skill）。
# SKILL_ROOT = automobile/，故直接锚到 sub_skills/。
PIC_UPLOAD_PY = SKILL_ROOT / "sub_skills" / "pic_upload" / "scripts" / "pic_upload.py"
REPORT_UPLOAD_PY = SKILL_ROOT / "sub_skills" / "report_upload" / "scripts" / "report_upload.py"


def _log(msg: str) -> None:
    print(f"[publish_report] {msg}", flush=True)


def _load_env() -> dict:
    """读取 .env 为 dict（不写进 os.environ，避免污染）。"""
    env = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _resolve_order_id(argv: list) -> str:
    """order_id 优先取命令行参数，否则从 run_context.json 读。"""
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    try:
        ctx = json.loads(RUN_CONTEXT_PATH.read_text(encoding="utf-8"))
        oid = str(ctx.get("order_id") or "").strip()
        if oid:
            return oid
    except (OSError, ValueError):
        pass
    raise SystemExit("[publish_report] 无法确定 order_id：未传参且 run_context.json 不可用")


def _get_cookie(cookie_cmd: str) -> str:
    """按 .env 的 COOKIE_CMD 执行一条命令，取其 stdout 作为 cookie 字符串。

    COOKIE_CMD 由使用者按自己的登录态方案配置（如一条输出 cookie JSON 的脚本）。
    为空时返回空串，调用方据此跳过传图。命令经 shell 执行，仅执行 .env 中你自己配置的值。
    """
    if not cookie_cmd.strip():
        return ""
    r = subprocess.run(cookie_cmd, shell=True, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"[publish_report] 取 cookie 失败（COOKIE_CMD）：{r.stderr.strip() or '空输出'}")
    return r.stdout.strip()


def _upload_images(shot_dir: Path, cookie: str, path_sign: str) -> dict:
    """调 pic_upload 批量上传截图目录，返回其 JSON 结果（含 results[].local/url）。"""
    if not PIC_UPLOAD_PY.exists():
        raise SystemExit(f"[publish_report] 缺少 pic_upload 脚本：{PIC_UPLOAD_PY}")
    if not path_sign:
        raise SystemExit("[publish_report] PIC_UPLOAD_SIGN 为空，无法上传图片（见 .env）")
    cmd = [
        sys.executable, str(PIC_UPLOAD_PY),
        "--image", str(shot_dir),
        "--cookie", cookie,
        "--path-sign", path_sign,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not r.stdout.strip():
        raise SystemExit(f"[publish_report] pic_upload 无输出，stderr：{r.stderr.strip()}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise SystemExit(f"[publish_report] pic_upload 输出非 JSON：{r.stdout[:300]}")


def _fill_cdn_urls(report: dict, upload_result: dict) -> int:
    """把 upload_result 的 local→url 映射回填进 report['screenshots'][*]['cdn_url']。

    映射键用文件名（pic_upload 远程名是 UUID，但 results[].name/local 保留了本地名），
    report.json 的 screenshots[].local_file 存的就是本地文件名，按文件名对齐。
    返回成功回填的张数。
    """
    by_name = {}
    for item in upload_result.get("results", []):
        if item.get("code") == 0 and item.get("url"):
            name = item.get("name") or Path(item.get("local", "")).name
            by_name[name] = item["url"]
    filled = 0
    for shot in report.get("screenshots", []):
        local = shot.get("local_file") or ""
        url = by_name.get(local) or by_name.get(Path(local).name)
        if url:
            shot["cdn_url"] = url
            filled += 1
        else:
            _log(f"⚠️ 截图无对应 CDN 链接：{local}")
    return filled


def _upload_report_json(report_file: Path, order_id: str) -> bool:
    """调独立的 report_upload skill 把报文原样上传落库。

    上传能力已抽成子 skill（automobile/sub_skills/report_upload），此处只负责调用，
    传报文**文件路径**而非 dict——skill 内按字节原文上传（留底语义，不重新序列化）。
    skill 缺失或上传失败均不影响本地产物，返回 False，可后续手动补传。
    """
    if not REPORT_UPLOAD_PY.exists():
        _log(f"未找到 report_upload skill（{REPORT_UPLOAD_PY}），跳过上传"
             f"（本地 report-json 已生成，可后续手动补传）")
        return False
    cmd = [sys.executable, str(REPORT_UPLOAD_PY),
           "--file", str(report_file), "--order-id", order_id]
    # 上传接口地址与 cookie 命令经环境变量透传给 report_upload（其自身也从 env 读，双保险）。
    r = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ})
    for line in (r.stdout + r.stderr).strip().splitlines():
        if line.strip():
            _log(f"  {line}")
    if r.returncode == 0:
        _log("✅ 报文已上传落库")
        return True
    _log("⚠️ 上传 report-json 失败（不影响本地产物，可手动补传）")
    return False


def _write_report_md(report: dict, md_path: Path) -> None:
    """生成人看的 report-json.md：标题 + 一段 JSON 代码块。"""
    pretty = json.dumps(report, ensure_ascii=False, indent=2)
    oid = report.get("order_id", "")
    result = report.get("result", "")
    md = (
        f"# 回归报告 report-json — {oid}\n\n"
        f"- 流程：{report.get('skill_name', '')}\n"
        f"- 结果：{result}（{report.get('passed_steps', 0)}/{report.get('total_steps', 0)} 步通过）\n"
        f"- 截图：{len(report.get('screenshots', []))} 张（CDN 链接已回填）\n\n"
        f"以下为上传接口的 report-json 内容：\n\n"
        f"```json\n{pretty}\n```\n"
    )
    md_path.write_text(md, encoding="utf-8")


def main() -> int:
    env = _load_env()
    order_id = _resolve_order_id(sys.argv)
    _log(f"order_id = {order_id}")

    shot_dir = SCREENSHOT_BASE / order_id
    report_dir = REPORT_BASE / order_id
    src_json = report_dir / "report.json"
    # report.json 不存在时先调生成器按模版生成（生成器职责独立，此处仅兜底触发）
    if not src_json.exists():
        _log(f"report.json 不存在，先调 generate_report 生成：{src_json}")
        gen = subprocess.run(
            [sys.executable, str(ROOT / "generate_report.py"), order_id],
            capture_output=True, text=True, env={**os.environ},
        )
        if gen.stdout.strip():
            for line in gen.stdout.strip().splitlines():
                _log(f"  {line}")
        if not src_json.exists():
            raise SystemExit(
                f"[publish_report] 生成 report.json 失败：{src_json}\n{gen.stderr.strip()}")
    report = json.loads(src_json.read_text(encoding="utf-8"))

    # ── 可选：上传截图并回填 CDN 链接（仅当配置了 PIC_UPLOAD_SIGN）──
    # 未配置时跳过，截图 cdn_url 保持为空，本地报告照常生成（开箱即用的默认路径）。
    path_sign = env.get("PIC_UPLOAD_SIGN", "").strip()
    if path_sign and shot_dir.is_dir():
        cookie = _get_cookie(env.get("COOKIE_CMD", ""))
        _log("上传截图…")
        upload_result = _upload_images(shot_dir, cookie, path_sign)
        (shot_dir / "upload_result.json").write_text(
            json.dumps(upload_result, ensure_ascii=False, indent=2), encoding="utf-8")
        _log(f"上传结果：total={upload_result.get('total')} success={upload_result.get('success')} "
             f"failed={upload_result.get('failed')} → {shot_dir / 'upload_result.json'}")
        filled = _fill_cdn_urls(report, upload_result)
        _log(f"回填 CDN 链接 {filled}/{len(report.get('screenshots', []))} 张")
    else:
        _log("未配置 PIC_UPLOAD_SIGN，跳过截图上传（截图 cdn_url 留空，仅生成本地报告）")

    # 5) 校验（只警告、不阻断），并剥离非契约辅助字段 local_file
    for shot in report.get("screenshots", []):
        shot.pop("local_file", None)
    warnings = validate_report(report)
    if warnings:
        _log(f"⚠️ 校验发现 {len(warnings)} 处问题（只警告，不阻断上传）：")
        for w in warnings:
            _log(f"    - {w}")
    else:
        _log("✅ 校验通过，无告警")

    # 6) 生成 report-json（json + md 两份）
    out_json = report_dir / "report-json.json"
    out_md = report_dir / "report-json.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report_md(report, out_md)
    _log(f"已生成 {out_json}")
    _log(f"已生成 {out_md}")

    # ── 可选：上传 report-json 原文落库（仅当配置了 REPORT_UPLOAD_URL）──
    if env.get("REPORT_UPLOAD_URL", "").strip():
        _upload_report_json(out_json, order_id)
    else:
        _log("未配置 REPORT_UPLOAD_URL，跳过报文落库上传（本地 report-json 已生成）")

    _log("✅ 发布流程结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())



