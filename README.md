# Automobile — 移动端 UI 自动化回归测试 Skill

一个基于 [Claude Code](https://claude.com/claude-code) Skill 机制的移动端 UI 自动化回归测试框架。用「Claude 编排 + API 调用 + 视觉驱动 UI」三段式跑通端到端业务流程，底层 UI 操作由 [droidrun/mobilerun](https://github.com/droidrun/mobilerun)（MIT）驱动。

> 声明式扩展：新增一条回归流程只需增加一个「叶子」目录（用例 + App 操作手册 + API 子 skill），无需改动核心引擎。

## 效果展示

> 以下为自建后台对报告的展示效果（后台需自行实现，见 [`docs/backend-integration.md`](docs/backend-integration.md)）。图中业务信息已脱敏。

**报告列表**：按流程 / 订单号 / 结果 / 日期筛选，一览每次回归的结果、通过步数与耗时。

![报告列表](docs/images/list.png)

**报告详情**：顶部通过率与汇总卡片，执行明细逐步列出步骤类型（API / UI / ADB）、结果、耗时与关键信息，底部附截图清单。

![报告详情-汇总与执行明细](docs/images/report1.png)

![报告详情-执行明细与截图清单](docs/images/report2.png)

## 特性

- **三段式链路**：`[API]` 步骤直连接口、`[UI]` 步骤交给视觉模型驱动、`[ADB]` 步骤由编排层直接注入，按用例中的标记自动分段执行。
- **双 Agent 协作**：Manager（决策）+ Executor（视觉定位）协作完成复杂 UI 操作。
- **路由 + 叶子架构**：`core/` 是所有流程共用的执行内核，各条业务流程作为 `businessLine/` 下的叶子独立维护。
- **自动报告**：产出单文件 HTML 报告与结构化 JSON，按订单号归档截图。
- **模型无关**：决策/视觉角色的 provider、模型、端点均可通过 `.env` 配置，支持 Anthropic 官方端点或任意兼容网关。

## 独特优势

**一句话：市面上的移动端 UI 自动化非此即彼——要么人工维护脚本（准但维护量爆炸），要么全依赖 AI（省事但不稳定、爱幻觉）。本框架两头的好处都要：稳定、准确，且维护量极小。**

怎么做到的？两条主流路线各自二选一，我们不做单选：传统脚本化（Appium / UIAutomator，靠选择器定位控件）赢在确定性、输在选择器维护成本；纯视觉 Agent（把整条流程一股脑交给多模态模型）赢在省维护、输在不稳定和状态幻觉。本框架**按每一步的性质分派最合适的执行方式**拿走两者的「准」，**用声明式扩展 + 视觉定位**把维护量压到极小，再**用一套工程化兜底**摁住 Agent 的不稳定。下面五点就是这三件事的展开。

### 1. 声明式扩展：新增一条流程 = 加目录，零改内核

传统框架每接一个新场景都要写 / 改脚本，选择器散落各处、难以复用。这里把「共享执行内核」（`core/`：路由、UI 引擎、报告、预检）与「单条流程」（`businessLine/` 下的叶子）彻底分离。新增一条回归流程只需在叶子里填四类**声明式文件**——`cases.yaml` 定义做什么、`app_cards/` 告诉视觉模型怎么点、`skills/` 定义调什么接口、`routes.yaml` 让路由找得到你——**不写一行 Python，不动 `core/` 与路由层**。Router 自动加载。

### 2. 三段式分派：能用接口/ADB 精确做的，绝不硬交给视觉猜

同一条用例里，`[API]` 步直连接口（快且确定性强，还负责产出业务主键）、`[UI]` 步才交给视觉模型驱动、`[ADB]` 步由编排层直接注入坐标/文本。这样把**确定性高的动作留在确定性通道**，只在真正需要「看屏幕做决策」时才动用视觉模型——比纯视觉 Agent 更稳、更快、更省 token。尤其 WebView / 系统开关这类视觉引擎点不中、输不进的控件，统一走 `[ADB]` 用 dump 拿 bounds 或截图定位，绕开了纯视觉路线的老大难。

### 3. 抗 UI 改版：视觉定位而非写死选择器

`[UI]` 步用自然语言描述动作，由 Manager（决策）+ Executor（视觉定位）双 Agent 协作完成。控件挪了位置、换了样式，只要人眼还认得，流程通常不用改——省掉了传统脚本里最脆、最费维护的选择器维护成本。

### 4. 直面 Agent 幻觉：磁盘是唯一真相源，关键步强制回读核对

自主 Agent 会「谎报完成」——把内部计划标成已完成却没真调工具，还照样返回成功。本框架不轻信 Agent 自述，用一套工程约定兜底：

- **段间状态以状态文件 `run_context.json` 为唯一可信来源**，`order_id` 等上下文不靠对话记忆传递，并用 `run_id` 校验防止读到上一轮残留。
- **截图是否完成，唯一依据是磁盘上的文件**：每段跑完编排层逐一核对预期截图文件，缺哪张当场用 adb 补截，绝不以 Manager 自述为准。
- **ADB 关键动作强制回读校验**：如输入订单号后 dump 回读 `EditText` 的 text 逐字符比对、点击后强制校验页面流转，不通过即中断保留现场。
- **接口重试区分传输层与业务层**：仅对网关/传输瞬时失败重试，非幂等写操作的业务失败绝不重试，避免重复提单。

### 5. 报告可追溯、可落库，且开箱即用

产出单文件 HTML 报告 + 结构化 `report.json`，按订单号归档截图与步骤明细。**默认零网络依赖**，本地直接出报告；配置对应环境变量后可选地把截图传图床、把报告原文落库到自建后台——上传能力是可插拔适配层，脚本内无任何预置地址，不配即安全跳过。

## 环境要求

- Python 3.10+
- [ADB](https://developer.android.com/tools/adb)（Android Debug Bridge）
- 一台开启无线调试的 Android 11+ 测试设备（Android 10 及以下走 USB tcpip，见 `setup.md`）
- 一个可用的 LLM 服务凭证（Anthropic 官方，或任意兼容网关）

## 快速开始

```bash
# 1. 安装依赖
cd .claude/skills/automobile
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key、模型端点、测试设备信息

# 3. 连接设备（详见 setup.md）
adb connect <设备IP>:<端口>
mobilerun doctor      # 确认 Portal / 无障碍 / Content Provider 就绪

# 4. 在 Claude Code 中运行
#    /automobile 跑一下 <你的流程诉求>
```

环境准备的完整步骤（ADB 配对、MobileRun Portal 安装、无障碍授权）见 [`setup.md`](.claude/skills/automobile/setup.md)。

## 目录结构

```
.claude/skills/automobile/
├── SKILL.md                 # 路由层：识别诉求 → 定位叶子 → 调用其 playbook
├── setup.md  requirements.txt  .env.example
├── core/                    # 共享执行内核（所有流程共用，新增流程不改）
│   ├── common_playbook.md   # 通用执行约定（预检 / 步骤规则 / 报告）
│   ├── runner.py            # UI 执行引擎（MobileRun 双 Agent）
│   ├── router.py            # 路由：加载 routes.yaml，匹配/解析叶子
│   ├── config/              # config.yaml（模型/设备）+ routes.yaml（流程注册表）
│   ├── models.py            # 报告数据模型
│   └── tools/               # 截图 / 报告生成 / doctor 预检
├── sub_skills/              # 可选公共能力：见下方「可选公共能力」一节
│   ├── appcard_gen/         # 喂截图自动生成 App 操作手册
│   ├── pic_upload/          # 截图上传到你的图床，拿回可访问 URL
│   └── report_upload/       # 报告原文上传到你的接口落库留底
└── businessLine/            # 业务树：业务线 → App → 品类 → 场景（叶子=一条流程）
    └── <example>/…          # 每个叶子自带 SKILL.md / cases / app_cards / skills
```

## 可选公共能力（sub_skills）

`sub_skills/` 下是三个**独立、可选**的辅助能力，被主流程按需调用，也可单独使用。它们都不是回归流程本身，不进 `businessLine/` 业务树、不登记 `routes.yaml`。默认不配置就完全不启用，不影响跑通最小流程。

| 子 skill | 是什么 | 什么时候用 | 效果 |
|----------|--------|-----------|------|
| **appcard_gen** | App 操作手册生成器 | 接入一个新 App、要写 `app_cards/<app>.md` 又不想手敲时 | 喂一组页面截图，多模态识别每页的可点/可断言控件，套骨架自动生成一份控件手册，人工核对即可用 |
| **pic_upload** | 图片上传器（纯标准库） | 想把报告里的截图存到自己的图床/对象存储、让报告能在线看图时 | 把本地截图（单张或整目录）POST 到你配置的接口，返回可访问 URL，回填进报告的 `cdn_url` |
| **report_upload** | 报告落库器（纯标准库） | 想把每次回归的 `report.json` 原文留底到自己的后台时 | 把报告原文按订单号 POST 到你配置的接口落库，供你自己的后台系统接收、存储与展示 |

> 三者的接口地址、鉴权全部由环境变量提供，脚本内**无任何预置地址**：`pic_upload` 需 `PIC_UPLOAD_URL`(+`PIC_UPLOAD_SIGN`)、`report_upload` 需 `REPORT_UPLOAD_URL`，未配置即安全跳过。报告的「上传截图 / 落库留底」由 `core/tools/publish_report.py` 在配了对应变量时自动串起这两个能力；详见各子 skill 的 `SKILL.md` 与 `core/common_playbook.md` 报告发布章节。
>
> 说明：本框架只负责**产出报告并可选地上传**，接收上传、存储、在网页展示的**后台系统需你自行实现**（上表的接口即对接点）。想自建后台的话，[`docs/backend-integration.md`](docs/backend-integration.md) 提供了一套可直接参考的库表设计与 `report.json` 落库映射思路。

## 如何新增一条回归流程

1. 在 `businessLine/` 下建叶子目录 `<业务线>/<App>/<品类>/<场景>/`（复制现有叶子改内容最省事）。
2. 填该叶子的四类声明式文件（都不写 Python）：
   - `SKILL.md`：这条流程的 playbook，只写因流程而异的内容，通用约定引用 `core/common_playbook.md`。
   - `cases/cases.yaml`：goal 步骤，用 `[API]` / `[UI]` / `[ADB]` 标记分段。
   - `app_cards/<app>.md`：该 App 的页面/控件操作手册。
   - `skills/`：这条流程用到的 API 子 skill。
3. 在 `core/config/routes.yaml` 登记一条 route（skill_name / 四维语义 / leaf_dir / keywords）。

Router 自动加载，无需改 `router.py` 与路由层。

## 致谢

- 底层 UI 驱动基于 [droidrun/mobilerun](https://github.com/droidrun/mobilerun)（MIT License）。

## License

本项目采用 [MIT License](LICENSE)。

