---
name: pic_upload
description: 把本地图片上传到图床/对象存储接口，支持单个文件或整个目录批量上传，返回可访问的图片 URL。接口地址与鉴权由环境变量配置（可选能力）。
---

# pic_upload

## 用途

把本地图片上传到你配置的上传接口（图床 / 对象存储），返回完整可访问 URL。支持单个文件上传，也支持传入目录后遍历批量上传。

本 skill 职责单一：**只做图片上传**。接口地址由环境变量 `PIC_UPLOAD_URL` 提供，脚本不含默认地址。登录态 cookie（如接口需要）由调用方获取后通过 stdin 或 `--cookie` 传入。脚本仅依赖 Python 标准库，直接 `python3` 运行。

> 本脚本按「响应含 `respData.readDomain` + `respData.filePath`」的约定解析返回并拼出 URL。若你的图床响应格式不同，改 `scripts/pic_upload.py` 的 `upload_one()` 解析逻辑即可。

## 何时使用

- 用户输入 `/pic_upload`，或要求把某张本地图片 / 某个目录下的图片上传拿到 URL。
- 作为报告发布的可选步骤，由 `core/tools/publish_report.py` 在配置了 `PIC_UPLOAD_SIGN` 时调用。

## 执行步骤

```bash
# 单个文件（如接口需要登录态，用 --cookie 或 stdin 传入 cookie JSON）
PIC_UPLOAD_URL=https://your-media.example.com/upload \
  python3 scripts/pic_upload.py --image /path/to/a.png --path-sign <pathSign>

# 整个目录（遍历目录下所有图片，含子目录）
PIC_UPLOAD_URL=https://your-media.example.com/upload \
  python3 scripts/pic_upload.py --image /path/to/dir --path-sign <pathSign>
```

把脚本输出的 `local -> url` 映射展示给用户。

## 参数说明

| 参数 | 短参 | 必填 | 说明 |
|------|------|------|------|
| `--image` | `-i` | 是 | 本地图片路径，或包含图片的目录（目录则遍历上传，支持子目录，按文件名排序） |
| `--upload-url` | `-u` | 否* | 上传接口地址，默认取环境变量 `PIC_UPLOAD_URL` |
| `--cookie` | `-c` | 否 | cookie JSON（`{"cookies":[{name,value}]}` 格式），不传则从 stdin 读取 |
| `--path-sign` | `-p` | 否* | 上传标识 pathSign，默认取环境变量 `PIC_UPLOAD_SIGN` |

\* `--upload-url`（或 `PIC_UPLOAD_URL`）为**必填**，取到空值时脚本不发起任何请求。`--path-sign` 是否必填取决于你的接口是否需要该参数。

## 输出格式

单个与批量统一为列表结构，每条结果带 `local`（本地路径）→ `url` 映射：

```json
{
  "code": 0,
  "total": 2, "success": 2, "failed": 0,
  "results": [
    {"local": "/path/a.png", "name": "a.png", "url": "https://.../xxx.png", "code": 0, "msg": "success"}
  ]
}
```

URL 由接口返回的 `respData.readDomain` + `respData.filePath` 拼接而成。

## 说明

- 支持的图片格式：jpg、jpeg、png、gif、bmp；单文件建议在 100M 以内。
- `PIC_UPLOAD_URL` 或 pathSign 为空时**不发起请求**，按 CLI 提示配置后重试。
- 若上传失败提示无权限/未登录，检查所传 cookie 是否为接口所需的有效登录态。

## 文件说明

- `SKILL.md` - Skill 定义文件
- `scripts/pic_upload.py` - 核心上传逻辑（纯标准库，无第三方依赖，支持单个/批量）
