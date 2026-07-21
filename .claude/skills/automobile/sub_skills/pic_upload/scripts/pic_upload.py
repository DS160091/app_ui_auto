#!/usr/bin/env python3
"""
pic_upload.py — 把本地图片上传到一个图床/对象存储接口（支持单个文件 / 整个目录批量）——可选能力。

职责单一：仅负责把本地图片 POST 到上传接口，返回可访问的完整 URL。
登录态 cookie（如需要）由调用方获取后通过 stdin / --cookie 传入，本脚本不负责取 cookie。
仅依赖 Python 标准库，直接 python3 运行，无需第三方依赖或虚拟环境。

接口地址由环境变量 PIC_UPLOAD_URL（或 --upload-url）提供，脚本不含默认地址。
本脚本按「响应含 respData.readDomain + respData.filePath」的约定解析返回并拼出 URL；
若你的图床响应格式不同，改 upload_one() 里的解析即可。

用法：
    # 单个图片（cookie JSON 从 stdin 传入，可选）
    PIC_UPLOAD_URL=https://your-media.example.com/upload \
      python3 pic_upload.py --image /path/to/a.png --path-sign <pathSign>
    # 整个目录（自动遍历目录下所有图片）
    PIC_UPLOAD_URL=... python3 pic_upload.py --image /path/to/dir --path-sign <pathSign>

关于文件名：服务端按 UUID 生成远程文件名，接口不支持指定远程名，因此远程名
与本地名无法一致。脚本在每条结果中输出 local -> url 的映射来记录对应关系。

输出（固定 JSON 格式，单个与批量统一为列表）：
    {
      "code": 0,                 // 0 全部成功；-1 存在失败
      "total": 2, "success": 2, "failed": 0,
      "results": [
        {"local": "/path/a.png", "name": "a.png", "url": "https://.../xxx.png", "code": 0, "msg": "success"},
        ...
      ]
    }
"""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import urllib.request
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)

# 上传接口地址，强制留空：必须由调用方通过 --upload-url 或环境变量 PIC_UPLOAD_URL 配置
DEFAULT_UPLOAD_URL = ""
# 上传标识 pathSign，强制留空：必须由调用方通过 --path-sign 或环境变量 PIC_UPLOAD_SIGN 配置
DEFAULT_UPLOAD_SIGN = ""
# 支持上传的图片后缀（依据接口文档：jpg,jpeg,png,gif,bmp）
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".bmp")



def _parse_cookies(raw: str) -> str:
    """把 {"cookies":[{name,value}...]} 格式的 cookie JSON 拼成 Cookie 请求头。"""
    if not raw or not raw.strip():
        return ""
    data = json.loads(raw)
    cookie_list = data.get("cookies") or []
    return "; ".join(
        "{}={}".format(c["name"], c.get("value", "")) for c in cookie_list if c.get("name")
    )


def _build_multipart(img_name: str, content: bytes, content_type: str):
    """用标准库手工拼 multipart/form-data 请求体。"""
    boundary = "----pic-upload-{}".format(uuid.uuid4().hex)
    crlf = b"\r\n"
    parts = []
    # 文件字段 multipartFile
    parts.append("--{}".format(boundary).encode())
    parts.append(
        'Content-Disposition: form-data; name="multipartFile"; filename="{}"'.format(img_name).encode()
    )
    parts.append("Content-Type: {}".format(content_type).encode())
    parts.append(b"")
    parts.append(content)
    parts.append("--{}--".format(boundary).encode())
    parts.append(b"")
    body = crlf.join(parts)
    return body, "multipart/form-data; boundary={}".format(boundary)


def upload_one(image_path: str, cookie_header: str, upload_sign: str, upload_url: str) -> dict:
    """上传单个图片，返回含 local -> url 映射的结果字典。"""
    img_name = os.path.basename(image_path)
    base = {"local": image_path, "name": img_name}
    url = "{}?pathSign={}".format(upload_url, upload_sign)
    logging.info("[图片上传] 开始上传 img_name=%s url=%s", img_name, url)

    if not os.path.isfile(image_path):
        logging.error("[图片上传] 文件不存在 img_name=%s path=%s", img_name, image_path)
        return {**base, "url": None, "code": -1, "msg": "文件不存在: {}".format(image_path)}

    content_type = mimetypes.guess_type(img_name)[0] or "image/png"
    try:
        with open(image_path, "rb") as fp:
            content = fp.read()
        body, multipart_type = _build_multipart(img_name, content, content_type)

        headers = {"Content-Type": multipart_type}
        if cookie_header:
            headers["Cookie"] = cookie_header
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")

        if status != 200:
            logging.error("[图片上传] 接口返回非 200 img_name=%s status=%s", img_name, status)
            return {**base, "url": None, "code": -1, "msg": "上传失败 http_status={}".format(status)}

        data = json.loads(raw)
        resp_data = data.get("respData") or {}
        read_domain = resp_data.get("readDomain")
        file_path = resp_data.get("filePath")
        if not read_domain or not file_path:
            logging.error("[图片上传] 返回缺少 readDomain/filePath img_name=%s resp=%s", img_name, data)
            return {**base, "url": None, "code": -1, "msg": "上传失败: {}".format(data.get("respMsg") or "返回数据异常")}

        final_url = "{}{}".format(read_domain, file_path)
        if not final_url.startswith(("http://", "https://")):
            final_url = "https://" + final_url
        logging.info("[图片上传] 上传成功 img_name=%s url=%s", img_name, final_url)
        return {**base, "url": final_url, "code": 0, "msg": "success"}
    except Exception as e:  # noqa: BLE001
        logging.error("[图片上传] 上传异常 img_name=%s err=%s", img_name, e)
        return {**base, "url": None, "code": -1, "msg": "上传图片异常: {}".format(e)}


def collect_images(path: str) -> list[str]:
    """根据入参解析待上传图片列表：文件→单个（需后缀合法）；目录→遍历目录下所有图片（按文件名排序）。"""
    if os.path.isfile(path):
        # 单文件也按后缀过滤，不符合的不纳入（由 main 统一报错告知用户）
        return [path] if path.lower().endswith(IMAGE_EXTS) else []
    if os.path.isdir(path):
        imgs = []
        for root, _dirs, files in os.walk(path):
            for fn in files:
                if fn.lower().endswith(IMAGE_EXTS):
                    imgs.append(os.path.join(root, fn))
        return sorted(imgs)
    return []



def main() -> int:
    parser = argparse.ArgumentParser(description="上传本地图片到图床/对象存储接口（支持单个文件或目录批量）")
    parser.add_argument("--image", "-i", required=True, help="本地图片路径，或包含图片的目录（目录则遍历上传）")
    parser.add_argument("--cookie", "-c", default=None, help="cookie JSON（{\"cookies\":[{name,value}]} 格式），不传则从 stdin 读取")
    parser.add_argument(
        "--upload-url", "-u", default=os.environ.get("PIC_UPLOAD_URL") or DEFAULT_UPLOAD_URL,
        help="上传接口地址，默认取环境变量 PIC_UPLOAD_URL",
    )
    parser.add_argument(
        "--path-sign", "-p", default=os.environ.get("PIC_UPLOAD_SIGN") or DEFAULT_UPLOAD_SIGN,
        help="上传标识 pathSign，默认取环境变量 PIC_UPLOAD_SIGN，再回退到内置默认值",
    )
    args = parser.parse_args()

    # 上传接口地址为必填，为空则不发起任何请求
    if not args.upload_url or not args.upload_url.strip():
        msg = ("上传接口地址未配置，已终止上传（未发起请求）。"
               "请用 --upload-url <地址> 或 export PIC_UPLOAD_URL=<地址> 配置。")
        logging.error("[图片上传] %s", msg)
        print(msg, file=sys.stderr)
        print(json.dumps({"code": -1, "total": 0, "success": 0, "failed": 0,
                          "results": [], "msg": msg}, ensure_ascii=False))
        return 1

    # 上传标识 pathSign 为必填配置，为空则不发起任何请求，并提示用户如何配置
    if not args.path_sign or not args.path_sign.strip():
        hint = (
            "上传标识 pathSign 未配置，已终止上传（未发起任何请求）。\n"
            "请通过以下任一方式配置后重试：\n"
            "  1) 命令行参数： --path-sign <你的pathSign>\n"
            "  2) 环境变量：   export PIC_UPLOAD_SIGN=<你的pathSign>\n"
            "  3) 修改脚本默认值 DEFAULT_UPLOAD_SIGN\n"
            "pathSign 是你的对象存储/图床接口所需的上传标识，按你所用服务的约定填写。"
        )
        logging.error("[图片上传] pathSign 为空，终止上传")
        print(hint, file=sys.stderr)
        print(json.dumps({"code": -1, "total": 0, "success": 0, "failed": 0,
                          "results": [], "msg": "上传标识 pathSign 未配置，无法发起上传"}, ensure_ascii=False))
        return 1

    raw_cookie = args.cookie if args.cookie is not None else sys.stdin.read()
    try:
        cookie_header = _parse_cookies(raw_cookie)
    except json.JSONDecodeError as e:
        print(json.dumps({"code": -1, "total": 0, "success": 0, "failed": 0,
                          "results": [], "msg": "cookie 不是有效 JSON: {}".format(e)}, ensure_ascii=False))
        return 1

    images = collect_images(args.image)
    if not images:
        # 区分三种情况，给出针对性提示
        if not os.path.exists(args.image):
            msg = "路径不存在: {}".format(args.image)
        elif os.path.isfile(args.image):
            msg = "文件后缀不支持，已终止上传（未发起请求）。仅支持: {}。当前文件: {}".format(
                ", ".join(IMAGE_EXTS), args.image)
        else:
            msg = "目录下未找到支持的图片（{}）: {}".format(", ".join(IMAGE_EXTS), args.image)
        logging.error("[图片上传] %s", msg)
        print(msg, file=sys.stderr)
        print(json.dumps({"code": -1, "total": 0, "success": 0, "failed": 0,
                          "results": [], "msg": msg}, ensure_ascii=False))
        return 1

    logging.info("[图片上传] 待上传图片数量=%d", len(images))
    results = [upload_one(img, cookie_header, args.path_sign, args.upload_url) for img in images]
    success = sum(1 for r in results if r["code"] == 0)
    failed = len(results) - success

    summary = {
        "code": 0 if failed == 0 else -1,
        "total": len(results),
        "success": success,
        "failed": failed,
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
