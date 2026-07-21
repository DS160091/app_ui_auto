"""回归报告 res-json 生成器（所有流程共用）。

把一次运行散落各处的产物，按 core/config/report_template.json 的固定格式，
拼装成一份 reports/{order_id}/report.json。数据来源：

  报告头
    order_id / run_id / case_name           ← reports/run_context.json
    skill_name/business_line/app/category/scene ← core/config/routes.yaml（按 LEAF_DIR 匹配 leaf_dir）
    priority                                 ← 叶子 cases/cases.yaml（按 case_name 匹配）
    result/total_steps/passed_steps/时间     ← 由 steps 汇总计算
  steps[]                                    ← reports/{order_id}/steps.jsonl（编排层边跑边记）
  screenshots[]                              ← 扫 screenshots/{order_id}/，从文件名 {ts}_{step_name}.png 还原
                                               （cdn_url 留空，由 publish_report.py 传图后回填）

生成后调 report_schema.validate_report 打印告警（只警告、不阻断）。

除结构化 report.json 外，同时按 common_playbook §3.1 渲染一份可直接在浏览器打开的
单文件 HTML 报告 reports/{order_id}/report_{timestamp}.html（内联样式，截图用本地相对
路径引用，不依赖 CDN；HTML 面向人工查看，与上传落库用的 report.json 相互独立）。

用法：
    python3 core/tools/generate_report.py [order_id]
    # order_id 省略时从 reports/run_context.json 读；LEAF_DIR 环境变量必填，指定当前叶子，缺失即中断
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from report_schema import validate_report

ROOT = Path(__file__).resolve().parent            # core/tools/
CORE_ROOT = ROOT.parent                             # core/
SKILL_ROOT = CORE_ROOT.parent                       # automobile/
ROUTES_PATH = CORE_ROOT / "config" / "routes.yaml"
SCREENSHOT_BASE = SKILL_ROOT / "screenshots"
REPORT_BASE = SKILL_ROOT / "reports"
RUN_CONTEXT_PATH = REPORT_BASE / "run_context.json"

# 叶子目录，与 runner.py 保持一致的解析规则。
# LEAF_DIR 决定报告头的业务线/App/品类/场景（经 routes.yaml）与优先级（经 cases.yaml），
# 必须由调用方（路由层）显式设置，指向当前流程叶子目录。缺失时直接中断，
# 不再静默回退到某条固定流程——否则会产出「字段齐全但业务线全错」且校验能通过的报告。
_leaf_env = os.environ.get("LEAF_DIR", "").strip()
if not _leaf_env:
    raise SystemExit(
        "[generate_report] 环境变量 LEAF_DIR 未设置：无法确定当前回归流程叶子目录。\n"
        "  请在调用前 export LEAF_DIR=<绝对路径>（指向 businessLine/<App>/<品类>/<场景>），"
        "由路由层 resolve 得到，不要依赖默认值。"
    )
LEAF_DIR = Path(_leaf_env)


def _log(msg: str) -> None:
    print(f"[generate_report] {msg}", flush=True)


def _resolve_order_id(argv: list[str]) -> str:
    if len(argv) > 1 and argv[1].strip():
        return argv[1].strip()
    try:
        ctx = json.loads(RUN_CONTEXT_PATH.read_text(encoding="utf-8"))
        oid = str(ctx.get("order_id") or "").strip()
        if oid:
            return oid
    except (OSError, ValueError):
        pass
    raise SystemExit("[generate_report] 无法确定 order_id：未传参且 run_context.json 不可用")


def _load_run_context() -> dict:
    try:
        return json.loads(RUN_CONTEXT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_route() -> dict:
    """按当前 LEAF_DIR 匹配 routes.yaml 里的一条 route，取语义字段。"""
    try:
        routes = yaml.safe_load(ROUTES_PATH.read_text(encoding="utf-8")).get("routes", [])
    except (OSError, ValueError, AttributeError):
        return {}
    # LEAF_DIR 是绝对路径，route.leaf_dir 是相对 SKILL_ROOT 的路径
    leaf_rel = ""
    try:
        leaf_rel = str(LEAF_DIR.resolve().relative_to(SKILL_ROOT.resolve()))
    except ValueError:
        leaf_rel = ""
    for r in routes:
        if r.get("leaf_dir", "").rstrip("/") == leaf_rel.rstrip("/"):
            return r
    return {}


def _load_priority(case_name: str) -> str:
    """从叶子 cases/cases.yaml 按 case_name 匹配，取 priority。"""
    cases_path = LEAF_DIR / "cases" / "cases.yaml"
    try:
        cases = yaml.safe_load(cases_path.read_text(encoding="utf-8")).get("cases", [])
    except (OSError, ValueError, AttributeError):
        return ""
    for c in cases:
        if c.get("name") == case_name:
            return str(c.get("priority", "") or "")
    return ""


def _load_steps(order_id: str) -> list[dict]:
    """读 reports/{order_id}/steps.jsonl，每行一个步骤记录。

    该文件由编排层（Claude）在执行每步时追加维护（见叶子 SKILL.md §3.4），
    非本脚本或其它代码生成；本函数只读取。文件不存在时 steps 为空。
    """
    path = REPORT_BASE / order_id / "steps.jsonl"
    if not path.exists():
        _log(f"⚠️ 未找到步骤记录 {path}，steps 将为空（编排层需边跑边记）")
        return []
    steps: list[dict] = []
    for ln, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            steps.append(json.loads(line))
        except ValueError:
            _log(f"⚠️ steps.jsonl 第 {ln} 行非法 JSON，已跳过")
    return steps


def _scan_screenshots(order_id: str) -> list[dict]:
    """扫 screenshots/{order_id}/，从文件名 {ts}_{step_name}.png 还原截图清单。

    按时间戳升序即为截图先后顺序（seq）。cdn_url 先留空，由 publish 回填。
    step_no 无法从文件名可靠推断，置 null，由后台按 seq 展示或人工关联。
    """
    shot_dir = SCREENSHOT_BASE / order_id
    if not shot_dir.is_dir():
        _log(f"⚠️ 截图目录不存在 {shot_dir}，screenshots 将为空")
        return []
    files = sorted(shot_dir.glob("*.png"), key=lambda p: p.name)
    shots: list[dict] = []
    for seq, p in enumerate(files, 1):
        stem = p.stem                       # {ts}_{step_name}
        ts, _, step_name = stem.partition("_")
        if not step_name:                   # 文件名不含下划线，整体当 step_name
            step_name = stem
        shots.append({
            "step_no": None,
            "step_name": step_name,
            "cdn_url": "",                  # 传图后由 publish_report.py 回填
            "seq": seq,
            "local_file": p.name,           # 供 publish 按文件名对齐 CDN（非契约字段，上传前可保留）
        })
    return shots


def _last_step_ts(steps: list[dict]) -> str:
    """取最后一条带 `ts`（ISO8601 完成时刻）的步骤作为 end_time；无则空串。

    steps.jsonl 每行可选带 `ts` 字段（编排层记录本步完成时刻）。倒序找第一条
    非空 ts 即最晚完成时刻，避免末尾若干步漏记 ts 导致 end_time 丢失。
    """
    for s in reversed(steps):
        ts = s.get("ts")
        if isinstance(ts, str) and ts.strip():
            return ts.strip()
    return ""


def _build_report(order_id: str) -> dict:
    ctx = _load_run_context()
    route = _load_route()
    case_name = str(ctx.get("case_name", "") or "")
    steps = _load_steps(order_id)
    screenshots = _scan_screenshots(order_id)

    end_time = _last_step_ts(steps)         # 先从原始步骤（含 ts）取结束时刻

    total_steps = len(steps)
    passed_steps = sum(1 for s in steps if s.get("result") == "PASS")
    # 整体结果：无 FAIL 视为 PASS（SKIP/NA 不算失败）
    result = "FAIL" if any(s.get("result") == "FAIL" for s in steps) else "PASS"
    # 总耗时：各步 duration_sec 之和（null 不计）
    duration_sec = sum(int(s["duration_sec"]) for s in steps
                       if isinstance(s.get("duration_sec"), int))

    # 组装报告用的 steps：只保留契约字段，剥掉仅用于算 end_time 的辅助字段 ts
    _STEP_KEYS = ("step_no", "step_type", "description", "result", "duration_sec", "detail")
    clean_steps = [{k: s.get(k) for k in _STEP_KEYS} for s in steps]

    return {
        "order_id": order_id,
        "run_id": str(ctx.get("run_id", "") or ""),
        "skill_name": str(route.get("skill_name", "") or ""),
        "business_line": str(route.get("business_line", "") or ""),
        "app": str(route.get("app", "") or ""),
        "category": str(route.get("category", "") or ""),
        "scene": str(route.get("scene", "") or ""),
        "case_name": case_name,
        "priority": _load_priority(case_name),
        "result": result,
        "total_steps": total_steps,
        "passed_steps": passed_steps,
        "start_time": str(ctx.get("order_id_set_at", "") or ""),
        "end_time": end_time,               # 取最后一条带 ts 的步骤时刻；无则留空，校验只警告
        "duration_sec": duration_sec,
        "steps": clean_steps,
        "screenshots": screenshots,
    }


_HTML_STYLE = """
    body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; color: #1f2329; }
    h1 { font-size: 22px; }
    h2 { font-size: 18px; margin-top: 28px; border-bottom: 1px solid #e5e6eb; padding-bottom: 6px; }
    table { border-collapse: collapse; width: 100%; margin: 12px 0; }
    th, td { border: 1px solid #e5e6eb; padding: 8px 12px; text-align: left; vertical-align: top; }
    th { background: #f7f8fa; }
    .pass { color: #00a870; font-weight: 600; }
    .fail { color: #e34d59; font-weight: 600; }
    img { max-width: 360px; border: 1px solid #e5e6eb; border-radius: 4px; }
"""


def _esc(v) -> str:
    """转义为 HTML 文本，None/空安全。"""
    return html.escape("" if v is None else str(v))


def _fmt_duration(sec) -> str:
    if not isinstance(sec, int) or sec <= 0:
        return "—"
    if sec < 60:
        return f"{sec}s"
    return f"{sec // 60}m{sec % 60:02d}s"


def _render_html(report: dict) -> str:
    """按 common_playbook §3.1 渲染单文件 HTML 报告。

    截图用本地相对路径 ../../screenshots/{order_id}/{filename} 引用（报告在
    reports/{order_id}/，上跳两级再进 screenshots/{order_id}/），保证在原位置打开即可显示。
    """
    order_id = report["order_id"]
    result = report.get("result", "")
    result_cls = "pass" if result == "PASS" else "fail"

    # 汇总表
    summary_rows = [
        ("用例", report.get("case_name", "")),
        ("流程", f"{report.get('business_line','')} / {report.get('app','')} / "
                 f"{report.get('category','')} / {report.get('scene','')}"),
        ("单号", order_id),
        ("优先级", report.get("priority", "")),
        ("开始时间", report.get("start_time", "")),
        ("结束时间", report.get("end_time", "")),
        ("总耗时", _fmt_duration(report.get("duration_sec"))),
    ]
    summary_html = "\n".join(
        f"    <tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in summary_rows
    )
    summary_html += (
        f"\n    <tr><th>结果</th><td class=\"{result_cls}\">{_esc(result)}</td></tr>"
        f"\n    <tr><th>步骤</th><td>{report.get('passed_steps',0)}/{report.get('total_steps',0)} 通过</td></tr>"
    )

    # 执行明细表
    detail_rows = []
    for s in report.get("steps", []):
        r = s.get("result", "")
        cls = "pass" if r == "PASS" else ("fail" if r == "FAIL" else "")
        detail = s.get("detail")
        detail_txt = json.dumps(detail, ensure_ascii=False) if detail else "—"
        detail_rows.append(
            "    <tr>"
            f"<td>{_esc(s.get('step_no'))}</td>"
            f"<td>{_esc(s.get('step_type'))}</td>"
            f"<td>{_esc(s.get('description'))}</td>"
            f"<td class=\"{cls}\">{_esc(r)}</td>"
            f"<td>{_fmt_duration(s.get('duration_sec'))}</td>"
            f"<td>{_esc(detail_txt)}</td>"
            "</tr>"
        )
    detail_html = "\n".join(detail_rows) or "    <tr><td colspan=\"6\">无步骤记录</td></tr>"

    # 失败详情（仅当有 FAIL 步）
    fail_html = ""
    fails = [s for s in report.get("steps", []) if s.get("result") == "FAIL"]
    if fails:
        blocks = []
        for s in fails:
            detail = s.get("detail")
            reason = ""
            if isinstance(detail, dict):
                reason = detail.get("error") or detail.get("reason") or json.dumps(detail, ensure_ascii=False)
            blocks.append(
                f"  <p><strong>步骤 {_esc(s.get('step_no'))} — {_esc(s.get('description'))}</strong></p>\n"
                f"  <ul><li>失败原因：{_esc(reason or '未记录')}</li>"
                f"<li>order_id：{_esc(order_id)}</li></ul>"
            )
        fail_html = "\n  <h2>失败详情</h2>\n" + "\n".join(blocks)

    # 截图清单（按 seq 顺序，本地相对路径）
    shot_rows = []
    for sh in report.get("screenshots", []):
        fname = sh.get("local_file") or ""
        src = f"../../screenshots/{order_id}/{fname}"
        label = sh.get("step_name") or fname
        shot_rows.append(
            "    <tr>"
            f"<td>{_esc(sh.get('step_no') if sh.get('step_no') is not None else sh.get('seq'))}</td>"
            f"<td><img src=\"{_esc(src)}\" alt=\"{_esc(label)}\"><br>{_esc(label)}</td>"
            "</tr>"
        )
    shot_html = "\n".join(shot_rows) or "    <tr><td colspan=\"2\">无截图</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>回归测试报告 - {_esc(report.get('case_name',''))}</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <h1>回归测试报告</h1>
  <table>
{summary_html}
  </table>

  <h2>执行明细</h2>
  <table>
    <tr><th>#</th><th>类型</th><th>描述</th><th>结果</th><th>耗时</th><th>关键信息</th></tr>
{detail_html}
  </table>
{fail_html}
  <h2>截图清单</h2>
  <table>
    <tr><th>步骤</th><th>截图</th></tr>
{shot_html}
  </table>
</body>
</html>
"""


def main() -> int:
    order_id = _resolve_order_id(sys.argv)
    _log(f"order_id = {order_id} | LEAF_DIR = {LEAF_DIR}")

    report = _build_report(order_id)

    report_dir = REPORT_BASE / order_id
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / "report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"已生成 {out_path}（steps={report['total_steps']} screenshots={len(report['screenshots'])}）")

    # 同步渲染单文件 HTML 报告（common_playbook §3.1，面向人工查看，截图走本地相对路径）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = report_dir / f"report_{ts}.html"
    html_path.write_text(_render_html(report), encoding="utf-8")
    _log(f"已生成 {html_path}")

    # 校验：只警告、不阻断（screenshots 里的 local_file 是非契约辅助字段，校验忽略多余键，不影响）
    warnings = validate_report(report)
    if warnings:
        _log(f"⚠️ 校验发现 {len(warnings)} 处问题（只警告，不阻断上传）：")
        for w in warnings:
            _log(f"    - {w}")
    else:
        _log("✅ 校验通过，无告警")
    return 0


if __name__ == "__main__":
    sys.exit(main())

