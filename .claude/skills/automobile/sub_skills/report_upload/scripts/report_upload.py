"""回归报告原始报文上传（留底落库）——可选能力。

把一份完整的 report.json **原样**（字节级，不重新序列化、不改动）POST 到你自己的报告留底接口：

    POST {REPORT_UPLOAD_URL}?orderId={orderId}
    Content-Type: application/json
    body: report.json 全文（合法 JSON 对象，≤256KB）

若后端以 @RequestBody String（或等价方式）原样接收落库、不解析，则 body 必须是字节级原文
（等价 curl --data-binary，而非 -d，避免换行被吞、原文被改）。

接口地址与鉴权全部由环境变量提供，脚本不含任何默认地址：
    - REPORT_UPLOAD_URL  上传接口地址（也可用 --url 传入）。未提供则报错退出。
    - COOKIE_CMD         可选。一条输出 cookie 到 stdout 的命令；接口需要登录态时配置。
    - COOKIE_DOMAIN      可选。传给 COOKIE_CMD 的域名参数（如你的取 cookie 脚本支持 -d）。

约束（超限下游多半直接失败，故本地先校验）：
    - orderId ≤ 32 字符
    - body ≤ 256KB
    - body 必须是合法 JSON 对象

响应：约定 {"code":0,"data":true,"msg":"..."}，code==0 且 data==true 为成功。

用法：
    REPORT_UPLOAD_URL=https://your-api.example.com/report-raw \
      python3 report_upload.py --file <report.json 路径> --order-id <订单号>
    # --url 可覆盖环境变量；--cookie 可直接传 cookie 串跳过自动获取
退出码：0 成功；非 0 失败（stderr 输出原因）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

MAX_ORDER_ID_LEN = 32
MAX_BODY_BYTES = 256 * 1024  # 256KB


def _log(msg: str) -> None:
    print(f"[report_upload] {msg}", flush=True)


def _err(msg: str) -> None:
    print(f"[report_upload] {msg}", file=sys.stderr, flush=True)


def _get_cookie() -> str:
    """按环境变量 COOKIE_CMD 执行一条命令取 cookie（输出到 stdout）。

    COOKIE_CMD 由使用者按自己的登录态方案配置；未配置时返回空串（接口若不需登录态即可）。
    可选 COOKIE_DOMAIN 作为域名参数附加在命令后（若你的取 cookie 脚本支持）。
    命令经 shell 执行，仅执行你在环境变量中自行配置的值。
    """
    cookie_cmd = os.environ.get("COOKIE_CMD", "").strip()
    if not cookie_cmd:
        return ""
    domain = os.environ.get("COOKIE_DOMAIN", "").strip()
    full_cmd = f"{cookie_cmd} {domain}".strip() if domain else cookie_cmd
    r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=20)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit(f"[report_upload] 取 cookie 失败（COOKIE_CMD）：{r.stderr.strip() or '空输出'}")
    return r.stdout.strip()


def _cookie_header(cookie_raw: str) -> str:
    """把 cookie 输入（可能是 {"cookies":[{name,value}...]} JSON，或已是 Cookie 串）
    统一拼成 `k=v; k=v` 的 Cookie 请求头值。"""
    cookie_raw = cookie_raw.strip()
    try:
        obj = json.loads(cookie_raw)
    except ValueError:
        return cookie_raw  # 已经是 Cookie 串，原样用
    items = obj.get("cookies") if isinstance(obj, dict) else None
    if isinstance(items, list):
        return "; ".join(f"{c.get('name')}={c.get('value')}" for c in items
                         if c.get("name") is not None)
    return cookie_raw


def _validate(order_id: str, body: bytes) -> None:
    """上传前本地校验，把可预见的失败挡在请求前。"""
    if not order_id:
        raise SystemExit("[report_upload] order_id 为空")
    if len(order_id) > MAX_ORDER_ID_LEN:
        raise SystemExit(f"[report_upload] order_id 超长：{len(order_id)} > {MAX_ORDER_ID_LEN} 字符")
    if len(body) > MAX_BODY_BYTES:
        raise SystemExit(f"[report_upload] 报文超限：{len(body)} 字节 > {MAX_BODY_BYTES}（256KB）")
    try:
        obj = json.loads(body)
    except ValueError as e:
        raise SystemExit(f"[report_upload] 报文不是合法 JSON：{e}")
    if not isinstance(obj, dict):
        raise SystemExit("[report_upload] 报文顶层必须是 JSON 对象（{...}）")


def _upload(api_url: str, order_id: str, body: bytes, cookie_header: str) -> bool:
    """POST 原始报文，返回是否留底成功（code==0 且 data==true）。"""
    full_url = f"{api_url}?orderId={urllib.parse.quote(order_id)}"
    req = urllib.request.Request(full_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    # req.add_header("Global-Route-Tag", "dstest")
    if cookie_header:
        req.add_header("Cookie", cookie_header)
    _log(f"POST {full_url}（body {len(body)} 字节）")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except Exception as e:
        _err(f"⚠️ 请求失败：{e}")
        return False
    _log(f"响应 HTTP {status}：{raw[:300]}")
    try:
        r = json.loads(raw)
    except ValueError:
        _err("⚠️ 响应非 JSON，无法判定结果")
        return False
    ok = r.get("code") == 0 and r.get("data") is True
    if not ok:
        _err(f"⚠️ 留底未成功：code={r.get('code')} data={r.get('data')} msg={r.get('msg')}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description="上传回归报告原始报文（留底落库）")
    ap.add_argument("--file", required=True, help="report.json 路径")
    ap.add_argument("--order-id", required=True, help="业务单号，≤32 字符")
    ap.add_argument("--url", default="", help="上传接口地址，覆盖环境变量 REPORT_UPLOAD_URL")
    ap.add_argument("--cookie", default="", help="直接传 cookie 串，跳过自动获取")
    args = ap.parse_args()

    api_url = args.url.strip() or os.environ.get("REPORT_UPLOAD_URL", "").strip()
    if not api_url:
        raise SystemExit(
            "[report_upload] 未配置上传接口地址：请设置环境变量 REPORT_UPLOAD_URL 或用 --url 传入")

    src = Path(args.file)
    if not src.exists():
        raise SystemExit(f"[report_upload] 文件不存在：{src}")
    body = src.read_bytes()                 # 字节原样读取，等价 curl --data-binary
    order_id = args.order_id.strip()

    _validate(order_id, body)

    cookie_header = _cookie_header(args.cookie) if args.cookie else _cookie_header(_get_cookie())

    ok = _upload(api_url, order_id, body, cookie_header)
    if ok:
        _log(f"✅ 留底成功 orderId={order_id}")
        return 0
    _err(f"❌ 留底失败 orderId={order_id}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

