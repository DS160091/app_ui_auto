# 回归报告 res-json 模版说明

本文件说明 `report_template.json` 这份**空白模版**的字段含义与填充规则。所有回归流程（如 demo 系统设置飞行模式……）上传落库的报告，**结构一律以本模版为准**。

## 设计原则

一句话：**固定字段全流程共用、类型钉死；因流程而异的内容只塞进 `steps[].detail` 这个自由 JSON 字段。**

不同流程之间，报告的**唯一差异**应当只有：

- `steps[]` 数组的长度与内容（步骤数不同）；
- `screenshots[]` 数组的长度与内容（截图数不同）；
- 各 `steps[].detail` 里塞的业务字段（各流程自定，只做展示，不约束结构）。

除此之外的固定字段，全流程结构一致，不增不减。

## 字段说明

### 报告级（顶层固定字段）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| order_id | string | ✅ | 业务单号（如本次运行的 run_id） |
| run_id | string | ✅ | 本次运行标识，格式 `YYYYMMDD_HHMMSS` |
| skill_name | string | ✅ | 流程标识，如 `demo-settings-network` |
| business_line | string | ✅ | 业务线，如 `demo` |
| app | string | ✅ | App，如 `settings` |
| category | string | ✅ | 品类，如 `network` |
| scene | string | ✅ | 场景，如 `飞行模式开关` |
| case_name | string | ✅ | 用例名 |
| priority | string | ✅ | 优先级 P0/P1… |
| result | string | ✅ | 整体结果，`PASS` / `FAIL` |
| total_steps | int | ✅ | 总步数，= `len(steps)` |
| passed_steps | int | ✅ | 通过步数，= steps 中 result 为 PASS 的条数 |
| start_time | string(ISO8601) | ✅ | 起始时间 |
| end_time | string(ISO8601) | ✅ | 结束时间 |
| duration_sec | int | ✅ | 总耗时（秒，整数） |
| steps | array | ✅ | 步骤明细，见下 |
| screenshots | array | ✅ | 截图，见下 |

### steps[] 元素（步骤固定骨架）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| step_no | int | ✅ | goal 步号，以 `cases.yaml` 的原始步号为准 |
| step_type | string | ✅ | `API` / `UI` / `ADB` |
| description | string | ✅ | 步骤描述 |
| result | string | ✅ | `PASS` / `FAIL` / `SKIP` / `NA` |
| duration_sec | int \| null | — | 本步耗时（秒）；未单独计时的步置 null |
| detail | object \| null | — | 本步业务明细，**自由 JSON，只做展示**，内容随步骤而定（如 API 步的 respCode、UI 步的开关状态、失败步的错误原因） |

### screenshots[] 元素（截图固定骨架）

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| step_no | int \| null | — | 关联步号，可空 |
| step_name | string | ✅ | 截图语义名，如 `01_打开App`（取自截图文件名 `{ts}_{step_name}.png`） |
| cdn_url | string | ✅ | 截图 CDN 链接（流程收尾传图后回填） |
| seq | int | ✅ | 展示顺序 |

## 填充约定

- **固定字段**：全部按上表类型填，不缺不改类型。空模版里的 `""` / `0` / `null` 均为占位，生成时须替换为真实值。
- **`steps[].detail`**：自由 JSON 对象，各流程把当前步骤相关的字段（API 的 respCode、UI 的开关状态、失败原因等）塞进去即可，无固定 schema，仅供后台展示。无内容时置 `null`。
- **`steps[]` / `screenshots[]`**：模版里各留一条空壳仅为示意结构，生成时按实际步数/截图数填充，长度因流程而异。
- **`cdn_url`**：生成阶段可先留空，由流程收尾的传图环节（`publish_report.py`）批量上传 CDN 后回填。
- **时间**：统一 ISO8601 字符串；耗时单位秒、整数。

## 一致性说明

本模版是格式的**书面契约**。落地时另有一份等价的可执行校验（Pydantic，`core/tools/report_schema.py`，后续补充）作为机器校验的真相源；两者字段保持一致，本文件供人阅读参照。字段结构见本文件说明。

