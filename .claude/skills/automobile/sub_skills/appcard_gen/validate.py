#!/usr/bin/env python3
"""appcard_gen 配置强校验。

执行 /appcard_gen 前由编排层调用：校验用户提前写好的配置文件是否齐全、可用。
任一硬错误 → 退出码 1，编排层必须中断、向用户报错，不得继续生成。

用法:
    python3 validate.py <config.yaml>

输出: JSON（stdout）。{"ok": true, ...} 表示通过；
      {"ok": false, "errors": [...]} 表示有硬错误，必须中断。
      "warnings" 为软提醒，不阻断。
"""
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    print(json.dumps({"ok": False, "errors": ["缺少 PyYAML，先 pip install pyyaml"]}, ensure_ascii=False))
    sys.exit(1)

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
REQUIRED = ["screenshots_dir", "output_path"]


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"ok": False, "errors": ["用法: python3 validate.py <config.yaml>"]}, ensure_ascii=False))
        sys.exit(1)

    cfg_path = sys.argv[1]
    errors, warnings = [], []

    if not os.path.isfile(cfg_path):
        print(json.dumps({"ok": False, "errors": [f"配置文件不存在: {cfg_path}"]}, ensure_ascii=False))
        sys.exit(1)

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        print(json.dumps({"ok": False, "errors": [f"配置 YAML 解析失败: {e}"]}, ensure_ascii=False))
        sys.exit(1)

    if not isinstance(cfg, dict):
        print(json.dumps({"ok": False, "errors": ["配置根节点必须是 key: value 映射"]}, ensure_ascii=False))
        sys.exit(1)

    # 1) 必填字段非空
    for k in REQUIRED:
        v = cfg.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            errors.append(f"必填字段缺失或为空: {k}")

    cfg_dir = os.path.dirname(os.path.abspath(cfg_path))

    def resolve(p):
        """相对路径按配置文件所在目录解析。"""
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(cfg_dir, p))

    # 2) 分辨率格式 WxH
    res = cfg.get("reference_resolution")
    if isinstance(res, str) and not re.fullmatch(r"\s*\d+\s*[xX]\s*\d+\s*", res):
        errors.append(f"reference_resolution 格式应为 宽x高（如 1080x2400），当前: {res!r}")

    # 3) 截图目录存在且含图片
    shots = []
    sdir = cfg.get("screenshots_dir")
    if isinstance(sdir, str) and sdir.strip():
        abs_sdir = resolve(sdir.strip())
        if not os.path.isdir(abs_sdir):
            errors.append(f"screenshots_dir 不是有效目录: {abs_sdir}")
        else:
            shots = sorted(f for f in os.listdir(abs_sdir) if f.lower().endswith(IMG_EXT))
            if not shots:
                errors.append(f"screenshots_dir 内无图片({'/'.join(IMG_EXT)}): {abs_sdir}")

    # 5) 输出路径父目录可写（不存在则提示将自动创建）
    out = cfg.get("output_path")
    abs_out = None
    if isinstance(out, str) and out.strip():
        abs_out = resolve(out.strip())
        parent = os.path.dirname(abs_out)
        if parent and not os.path.isdir(parent):
            warnings.append(f"输出目录不存在，生成时将自动创建: {parent}")
        if os.path.isfile(abs_out):
            warnings.append(f"输出文件已存在，将被覆盖: {abs_out}")

    # 6) pages 映射（可选）与截图对应性检查
    pages = cfg.get("pages")
    if pages is not None:
        if not isinstance(pages, dict):
            errors.append("pages 必须是 文件名: 语义说明 的映射")
        elif shots:
            unknown = [k for k in pages if k not in shots]
            if unknown:
                warnings.append(f"pages 中这些文件名在截图目录里找不到: {unknown}")

    ok = not errors
    # app 短名：优先配置 app_name，否则取输出文件名（不含扩展名）
    app_name = cfg.get("app_name")
    if (not app_name) and abs_out:
        app_name = os.path.splitext(os.path.basename(abs_out))[0]
    result = {
        "ok": ok,
        "errors": errors,
        "warnings": warnings,
        "screenshots": shots,
        "screenshot_count": len(shots),
        "abs_output_path": abs_out,
        "app_name": app_name if ok else None,
        "config": cfg if ok else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
