# 扩展：报告后台对接（上传接收 + 存储 + 展示）

> 本框架只负责**产出回归报告并可选地上传**（见主 README「可选公共能力」）。接收上传、落库、在网页展示的后台系统需你自行实现。本文提供一套经过实践的**库表设计与实现思路**作为参考，你可直接照搬或按需裁剪。
>
> 文中所有业务名、订单号、CDN 域名均为示例占位，替换成你自己的即可。

## 1. 设计背景与目标

回归流程执行后产出一份结果报告，需要持久化到数据库，用于后续查询、展示与统计。报告中的截图先上传对象存储/CDN，库里只存链接。

核心矛盾：**报告的整体结构是共通的，但每条回归流程的步骤明细字段各不相同**（不同业务流程各有自己的关键字段）。

设计原则一句话：**共通结构拆成固定列，因流程而异的明细塞进 JSON 列**。不为每个流程单独建表，也不用 EAV。

报告天然是三层固定结构：

```
一份报告 (report)
  └── 多个步骤 (step)
        └── 多张截图 (screenshot)
```

- 报告级汇总（结果、起止时间、总耗时、步骤数）—— 所有流程一致。
- 步骤级骨架（步号、类型、结果、耗时）—— 所有流程一致。
- 截图（CDN 链接、关联步骤）—— 所有流程一致。
- **唯一因流程而异的，是步骤里那段关键信息/明细** → 落 JSON。

## 2. 表结构

### 2.1 回归报告主表 `auto_report`

```sql
CREATE TABLE auto_report (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  order_id      VARCHAR(32)  NOT NULL COMMENT '业务单号',
  run_id        VARCHAR(32)  NOT NULL COMMENT '本次运行标识',
  skill_name    VARCHAR(64)  NOT NULL COMMENT '流程标识',
  business_line VARCHAR(32)  NOT NULL COMMENT '业务线',
  app           VARCHAR(32)  NOT NULL COMMENT 'App',
  category      VARCHAR(32)  NOT NULL COMMENT '品类',
  scene         VARCHAR(32)  NOT NULL COMMENT '场景',
  case_name     VARCHAR(128) NOT NULL COMMENT '用例名',
  priority      VARCHAR(8)   NOT NULL DEFAULT '' COMMENT '优先级 P0/P1...',
  result        VARCHAR(16)  NOT NULL COMMENT 'PASS/FAIL/...',
  total_steps   INT          NOT NULL DEFAULT 0,
  passed_steps  INT          NOT NULL DEFAULT 0,
  start_time    DATETIME     NULL,
  end_time      DATETIME     NULL,
  duration_sec  INT          NOT NULL DEFAULT 0 COMMENT '总耗时(秒)',
  report_url    VARCHAR(512) NULL COMMENT '整份HTML报告快照CDN链接(可选)',
  extra         JSON         NULL COMMENT '流程级特有汇总字段',
  is_deleted    TINYINT      NOT NULL DEFAULT 0,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_order (order_id),
  KEY idx_skill_time (skill_name, created_at)
) COMMENT '回归测试报告主表';
```

### 2.2 报告步骤明细表 `auto_report_step`

```sql
CREATE TABLE auto_report_step (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  report_id     BIGINT       NOT NULL,
  step_no       INT          NOT NULL COMMENT 'goal步号',
  step_type     VARCHAR(8)   NOT NULL COMMENT 'API/UI/ADB',
  description   VARCHAR(512) NOT NULL,
  result        VARCHAR(16)  NOT NULL COMMENT 'PASS/FAIL/SKIP/NA',
  duration_sec  INT          NULL,
  detail        JSON         NULL COMMENT '流程特有明细(API的respCode/respMsg、UI的关键信息等)',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_report (report_id, step_no)
) COMMENT '报告步骤明细表';
```

### 2.3 报告截图表 `auto_report_screenshot`

```sql
CREATE TABLE auto_report_screenshot (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  report_id     BIGINT       NOT NULL,
  step_id       BIGINT       NULL COMMENT '关联步骤,可空',
  step_no       INT          NULL COMMENT '冗余,便于按步排序',
  step_name     VARCHAR(64)  NOT NULL COMMENT '如 01_打开App',
  cdn_url       VARCHAR(512) NOT NULL COMMENT 'CDN链接',
  seq           INT          NOT NULL DEFAULT 0 COMMENT '展示顺序',
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_report (report_id, seq)
) COMMENT '报告截图表';
```

### 2.4 原始报文留底表 `auto_report_raw`

客户端上传的完整 `report.json` 先原样落到此表留底，主表与 step / screenshot 三张表的数据由下游（MQ 消费方或定时任务）解析原始报文后异步写入。上传接口只负责留底，不做解析。

```sql
CREATE TABLE auto_report_raw (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  report_id   BIGINT       NULL COMMENT '关联 auto_report.id,下游解析建主表后回填',
  order_id    VARCHAR(32)  NOT NULL COMMENT '业务单号',
  raw_json    JSON         NOT NULL COMMENT '客户端上传的完整 report.json 原始报文',
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_order (order_id)
) COMMENT '回归报告原始报文留底表';
```

数据流：

```
客户端 → 上传接口 → insert auto_report_raw (留底,report_id 暂空)
                        └→ 下游解析 raw_json → 写 auto_report + step + screenshot
                                                └→ 回填 auto_report_raw.report_id
```

设计要点：
- **接口职责单一**：只校验 JSON 合法性并留底，不解析、不拆表。留底成功即返回成功。
- **report_id 后回填**：留底时主表尚未建立，故可空；下游解析建主表后回填。
- **冷热分离**：大 JSON 独立成表，主表 `auto_report` 保持精瘦，不受原始报文体积拖累。

## 3. 可变明细如何落地

因流程而异的字段全部落在两个 JSON 列：

- `auto_report.extra` —— 流程级特有汇总。
- `auto_report_step.detail` —— 步骤级特有明细。

**示例（某检测步骤的 `detail`）：**

```json
{ "field_a": "99.9", "field_b": 1, "amount": 927.56, "respCode": 0 }
```

不同流程各存自己那套字段。**新增回归流程不改表结构** —— 契合本框架「加流程只改配置」的理念，也符合 schema 演进「只加不删」的习惯。

### 3.1 失败信息为何不放主表

主表**不存失败步数、失败步号、失败原因**。失败步数 = `total_steps - passed_steps`，或直接从 step 表 count 得到，无需单独存列。原因：

- **一份报告可能有多个失败步**：若某流程不采用「失败即中断」、允许跳过失败步继续跑，FAIL 步就不止一个。主表用单个 `failure_step INT` 放不下，会把「失败即中断」这条业务规则焊进表结构，换流程或改中断策略就得改表。
- **避免冗余与不一致**：失败步号、失败描述、失败明细在 `auto_report_step` 里本就有（`result='FAIL'` 的行各自带 `description`、`detail`）。主表再存一份属于双写，易不一致。

要看失败详情，直接查 step 表，天然支持多个失败步：

```sql
SELECT step_no, step_type, description, detail
FROM   auto_report_step
WHERE  report_id = ? AND result = 'FAIL'
ORDER  BY step_no;
```

## 4. 方案选型说明

| 方案 | 是否采用 | 原因 |
|------|:--------:|------|
| 共通固定列 + JSON 明细列 | ✅ 采用 | 结构稳定、加流程零改表、读写直接 |
| 每个流程单独建明细表 | ❌ | 流程数膨胀，每加一条流程要建表+改 DAO；跨流程统计需 UNION 所有表 |
| EAV（一个字段一行） | ❌ | 查询要反复自连接做行转列，字段全字符串丢类型，可读性与性能都差 |

JSON 方案的优势：MySQL 5.7+ 原生支持，一列存整个明细对象，读写直接；真要按明细字段查询时，可对**热点路径**建虚拟列 + 索引按需补救，不必预先拍死结构。

### 4.1 何时需要补虚拟列

JSON 方案唯一的代价是：**频繁按明细字段做筛选/聚合时**，JSON 路径查询比普通列慢、也不够顺手。据此分两种情况：

- **只按订单号/流程查出来展示** → 上面的纯 JSON 设计就够。
- **需要跨报告按明细字段统计**（如「按某明细字段分布」「筛出金额 > X 的单」）→ 把高频被查询的字段从 JSON 里提成**虚拟列 + 索引**（或直接提成固定列），其余仍留 JSON。

## 5. report.json 与库表的映射

客户端上传的 `report.json` 顶层结构与三张表一一对应：

```
report.json
├── 报告级字段        → auto_report          主表
├── steps[]           → auto_report_step     步骤表
└── screenshots[]     → auto_report_screenshot 截图表
```

字段格式的**真相源**是 `core/config/report_template.json`（空白模版）+ `report_template.md`（字段说明），可执行校验为 `core/tools/report_schema.py`。约定：

- 截图 `cdn_url` 由客户端在流程收尾阶段批量上传 CDN 后填入（图不放 base64，只放链接）。
- `steps[].detail` / `extra` 为流程特有明细，结构因流程而异，只放关键字段；大文本（完整响应体/堆栈/HTML）截断或仅留 traceId。
- 时间统一用 ISO8601 字符串；耗时单位秒，整数；未单独计时的步 `duration_sec` 置 null。

### 5.1 脱敏样例（结构示意，数据均为占位）

```json
{
  "order_id": "1000000000000000001",
  "run_id": "20260101_120000",
  "skill_name": "demo-app-settings-network",
  "business_line": "demo",
  "app": "settings",
  "category": "network",
  "scene": "offline",
  "case_name": "示例流程_完整主流程",
  "priority": "P0",
  "result": "FAIL",
  "total_steps": 6,
  "passed_steps": 5,
  "start_time": "2026-01-01T12:00:00",
  "end_time": "2026-01-01T12:05:00",
  "duration_sec": 300,
  "extra": { "field_a": "value_a", "note": "流程级特有汇总字段,结构因流程而异" },
  "steps": [
    { "step_no": 1, "step_type": "API", "description": "示例前置接口下单", "result": "PASS", "duration_sec": 11,
      "detail": { "skill": "mock_precheck", "respCode": 0, "order_id": "1000000000000000001" } },
    { "step_no": 2, "step_type": "UI", "description": "打开 App 并等待首页加载", "result": "PASS", "duration_sec": null,
      "detail": { "note": "并入第3步计时" } },
    { "step_no": 3, "step_type": "UI", "description": "[截图] 01_打开App", "result": "PASS", "duration_sec": 12, "detail": null },
    { "step_no": 4, "step_type": "ADB", "description": "点某宫格(410,830)进入子页", "result": "PASS", "duration_sec": 5,
      "detail": { "cmd": "input tap 410 830", "assert": "出现目标标题" } },
    { "step_no": 5, "step_type": "UI", "description": "[截图] 02_子页", "result": "PASS", "duration_sec": 8, "detail": null },
    { "step_no": 6, "step_type": "UI", "description": "提交操作", "result": "FAIL", "duration_sec": null,
      "detail": { "blocked": true, "reason": "示例:被业务前置条件阻断", "expected": "成功页", "actual": "当前页" } }
  ],
  "screenshots": [
    { "step_no": 3, "step_name": "01_打开App", "cdn_url": "https://cdn.example.com/xxx/screenshot-01.png", "seq": 1 },
    { "step_no": 5, "step_name": "02_子页",    "cdn_url": "https://cdn.example.com/xxx/screenshot-02.png", "seq": 2 }
  ]
}
```
