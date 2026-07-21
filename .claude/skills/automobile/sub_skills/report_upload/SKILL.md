---
name: report_upload
description: 把回归报告 report.json 原样上传到你自己的留底接口落库（可选能力），接口地址与鉴权全部由环境变量配置。供任意回归流程收尾调用。
---

# report_upload

## 何时使用

回归流程收尾、已生成 `report.json`，需要落库留底时。这是一个**可选**能力：默认不启用，只有配置了 `REPORT_UPLOAD_URL` 才会被 `publish_report.py` 调用。也可用户直接 `/report_upload` 手动调用。

## 用法

```bash
REPORT_UPLOAD_URL=https://your-api.example.com/report-raw \
  python3 scripts/report_upload.py --file <report.json 路径> --order-id <订单号>
```

| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--file` | ✅ | report.json 路径 |
| `--order-id` | ✅ | 业务单号，≤32 字符 |
| `--url` | — | 上传接口地址，覆盖环境变量 `REPORT_UPLOAD_URL` |
| `--cookie` | — | 直接传 cookie 串，跳过自动获取 |

相关环境变量：

| 变量 | 说明 |
|------|------|
| `REPORT_UPLOAD_URL` | 上传接口地址。未配置且未传 `--url` 则报错退出。 |
| `COOKIE_CMD` | 可选。一条输出 cookie 到 stdout 的命令，接口需要登录态时配置。 |
| `COOKIE_DOMAIN` | 可选。附加给 `COOKIE_CMD` 的域名参数（若你的取 cookie 脚本支持）。 |

脚本流程：本地校验（order_id ≤32 字符、报文 ≤256KB 且为合法 JSON 对象）→ 取 cookie（如配置了 `COOKIE_CMD`）→ POST 报文原文 → 判定 `code==0 && data==true` 为成功（退出码 0，否则非 0 并输出原因）。

## 关键约定

- **原样上传**：body 用 `read_bytes()` 字节原文 POST（等价 `curl --data-binary`），不重新序列化。若你的后端以 `@RequestBody String`（或等价方式）原样落库不解析，改动原文会破坏留底。
- **接口地址不写死**：脚本不含任何默认地址，全部由 `REPORT_UPLOAD_URL` / `--url` 提供。响应约定为 `{"code":0,"data":true}`；若你的接口约定不同，改脚本 `_upload()` 的判定即可。
- **不伪造成功**：上传失败或接口不可达时非 0 退出、本地产物不受影响，可手动补传。
