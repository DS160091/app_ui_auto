---
name: mock-precheck
description: 示例 API 子 skill —— 演示 [API] 步骤如何工作。完全离线：不请求任何网络，只在本地生成一个 run_id 作为贯穿后续步骤的上下文主键，写入 run_context.json。
---

# mock_precheck — 示例前置检查（离线）

## 触发

goal 中出现 `[API] mock_precheck` 时执行本 Skill。

> 这是一个**示例**，用来演示 `[API]` 步骤的形态：真实项目里这一步通常是调用你自己的接口创建一笔业务单据、拿回一个 `order_id`。这里为了让示例能离线跑通，改成本地生成一个 `run_id` 主键，不发任何请求。接入自己的接口时，参考 `core/common_playbook.md` §2.1 的接口重试/校验/写 run_context 规则替换本文件即可。

## 执行流程

### 1. 生成主键

取当前时间戳生成 `run_id`，格式 `YYYYMMDD_HHMMSS`（如 `20260720_143022`）。

真实项目中，这里应改为调用你的业务接口并从响应中提取 `order_id`。示例接口调用形态（供参考，本 demo 不执行）：

```bash
# 真实项目示例：调用你自己的接口，从返回中解析业务主键
# curl -s -X POST "https://your-api.example.com/create" \
#   -H "Content-Type: application/json" \
#   -d '{"scene":"demo"}'
# 解析响应，提取 order_id / run_id
```

### 2. 校验并写入运行上下文

按 `core/common_playbook.md` §2.0 初始化 `reports/run_context.json`：覆写文件，写入本次 `run_id`、`case_name`（当前叶子用例名）、`order_id`（demo 用 run_id 兜底，真实项目填接口返回的业务单号）。

```json
{
  "run_id": "20260720_143022",
  "case_name": "示例_设置页飞行模式开关回归",
  "order_id": "20260720_143022",
  "order_id_set_at": "2026-07-20T14:30:22"
}
```

### 3. 输出

```
[mock_precheck] ✅ 前置检查完成
  run_id: 20260720_143022
```

> 说明：demo 里用 `run_id` 同时充当 `order_id`，只为让后续「按订单号归档报告/截图」的通用逻辑有一个主键可用。真实项目请用接口返回的业务单号。
