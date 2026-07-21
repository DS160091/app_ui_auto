---
name: automobile
description: 移动端 UI 自动化回归测试的总入口（路由层）。识别用户诉求（业务线/App/品类/场景），匹配到对应叶子 playbook 并调用执行。新增回归流程只需加叶子，不改本层与 core。
---

# 移动端 UI 自动化回归测试 — 总路由 Skill

本 Skill 是移动端 UI 自动化回归测试的**总入口与路由层**。它本身不实现具体流程，只做三件事：

1. **识别**用户诉求对应哪条回/归流程（业务线 → App → 品类 → 场景）。
2. **定位**到该流程的叶子目录，设置环境变量 `LEAF_DIR` 指向它。
3. **调用**该叶子的 `SKILL.md`（playbook）：读取并完全遵循其内容执行，共享能力统一走 `core/`。

> 具体某条流程怎么跑，分两层：**通用执行约定**（预检、[API]/[UI]/[ADB] 步骤规则、报告/流水/发布）统一写在 `core/common_playbook.md`，所有叶子共享、不重复；**因流程而异的内容**（流程阶段、ADB 场景坐标、cases/app_cards/skills）写在各**叶子 playbook**。共享执行能力（UI 引擎、截图、报告、报告发布、doctor 预检）在 `core/`，所有叶子共用，新增流程不改。

## 1. 目录结构

```
automobile/                                  # Skill 根（本文件 = 路由层）
├── SKILL.md                                 # ← 本文件：路由
├── setup.md  requirements.txt  .env         # 根级共用（环境/依赖/配置）
├── core/                                    # ← 共享执行内核（所有叶子共用，新增流程不改）
│   ├── common_playbook.md 通用执行约定（预检/步骤规则/报告/流水/发布，所有叶子共享，被引用非 skill）
│   ├── runner.py          UI 执行引擎（接收 GOAL_TEXT + LEAF_DIR）
│   ├── router.py          路由配置类（加载 config/routes.yaml，匹配/解析叶子）
│   ├── config/            配置目录
│   │   ├── config.yaml    MobileRun/模型/设备配置
│   │   └── routes.yaml    流程注册表（结构化配置，唯一事实来源）
│   ├── models.py          报告数据模型
│   └── tools/             截图(verify_tools) + 报告发布(publish_report) + doctor 预检脚本
├── sub_skills/                             # ← automobile 编排调用的公共子 skill（非顶层 slash 命令）
│   ├── pic_upload/         截图批量上传（publish_report 内部调用）
│   ├── report_upload/      报文上传落库（publish_report 内部调用）
│   └── appcard_gen/        App 操作手册生成器（低频人工前置，见 §4 第 3 步）
├── reports/  screenshots/                   # ← 共享产物，按 order_id 归档
└── businessLine/                            # 业务树：业务线 → App → 品类 → 场景
    └── <App>/                          # ② App（如 settings）
        └── <品类>/                          # ③ 品类（如 network）
            └── <场景>/                      # ④ 场景（如 demo）← 叶子节点
                ├── SKILL.md                 该流程的 playbook（怎么跑）
                ├── cases/cases.yaml         该流程回归用例
                ├── app_cards/<app>.md       该 App 页面/控件操作手册
                └── skills/                  该流程 API 子 Skill
```

> `sub_skills/` 下三者是被 automobile 编排调用的公共能力，**不注册为顶层 `/` 命令**：`pic_upload`/`report_upload` 由 `core/tools/publish_report.py` 按路径自动调用；`appcard_gen` 仅在用户于 `/automobile` 会话中明确要求生成手册时触发（见 §4 第 3 步）。

叶子目录 = `businessLine/<App>/<品类>/<场景>/`，每个叶子是一条独立的回归流程，自带一份 `SKILL.md` playbook。

## 2. 流程注册表（结构化配置）

已落地的回归流程登记在结构化配置 **`core/config/routes.yaml`** 中，由路由配置类 **`core/router.py`** 加载、匹配与解析。一切以 `routes.yaml` 为准，新增流程改配置即可（见 §4）。

每条 route 字段：`skill_name`（叶子 playbook 名）、`business_line` / `app` / `category` / `scene`（四维语义）、`leaf_dir`（叶子目录，相对 Skill 根）、`keywords`（兜底关键词）、`description`（一句话描述）。

`router.py` 提供三个命令（均输出 JSON，供路由层调用）：

| 命令 | 作用 |
|------|------|
| `python3 core/router.py list` | 列出全部已注册流程 |
| `python3 core/router.py match "<用户诉求>"` | 关键词打分预筛，返回按得分降序的候选 |
| `python3 core/router.py resolve <skill_name>` | 返回 `skill_name` + 绝对 `leaf_dir`（即 LEAF_DIR）+ `skill_md` 路径 |

> `resolve` 已把相对 `leaf_dir` 解析成绝对路径并校验叶子存在，路由层拿到即可直接用作 `LEAF_DIR`，无需自己拼路径。

## 3. 路由执行规则

用户输入 `/automobile`（可能附带诉求，如"跑一下系统设置飞行模式开关"）后：

1. **预筛候选**：执行 `python3 core/router.py match "<用户诉求原文>"` 取候选列表（带得分）。诉求为空时改用 `list`。
2. **语义定夺**（由 Claude 完成，不只看关键词得分）：
   - 候选**唯一**且语义明确匹配 → 取其 `skill_name`，进入第 3 步。
   - 候选**多个**、或维度不全、或关键词得分相近难以区分 → 用 AskUserQuestion 列出候选（用 `description` 展示）让用户选，不要自行猜测。
   - `match` 返回**全员 0 分**（无任何关键词命中）→ 见第 4 步。
3. **解析并调用叶子 playbook**：
   - 执行 `python3 core/router.py resolve <skill_name>`，从返回 JSON 取 `leaf_dir`（绝对路径）与 `skill_md`。
   - 设置环境变量 `LEAF_DIR` = 该 `leaf_dir`。后续所有 `core/runner.py` 调用都带上这个 `LEAF_DIR`。
   - **读取 `skill_md` 指向的叶子 `SKILL.md`**，从其 §2 预检开始，**完全遵循该 playbook 执行**（预检 → 用例 → 报告 → 流水上报）。叶子内相对路径按其自身约定解析（共享能力相对 Skill 根，定制内容相对叶子）。
   - 本路由层不重复预检/执行/报告逻辑，一切以叶子 playbook 为准。
4. **匹配不到时必须中断（硬约束）**：出现以下任一情况，**立即停止，不得进入第 3 步、不得调用 runner、不得凭空捏造或猜测一个流程执行**：
   - `match` 返回全员 0 分（按用户诉求查不到匹配流程）；
   - `list` 为空（注册表 `routes.yaml` 无任何已登记流程）；
   - 语义定夺后仍无法确定唯一目标、且用户未在 AskUserQuestion 中做出有效选择。

   中断时向用户说明原因，用 `router.py list` 列出当前**所有**已注册流程（为空则如实告知注册表为空），**要求用户重新选择要执行的叶子流程**或按 §4 新增流程后再来。在用户给出明确、唯一的目标流程之前，流程不得继续。

> **为什么是"读取并遵循"而非 slash 调用**：叶子里的 `SKILL.md` 嵌套在子目录中，不会被注册成独立的 `/` 命令；且各叶子共用 `core/`，做成独立顶层 skill 反而无法共享内核。因此路由 = `resolve` 取 `LEAF_DIR` + 读取叶子 playbook 并遵循。

## 4. 如何新增回归流程

实现自己的业务流程时，**只需增改 `businessLine/` 下的叶子和一处路由注册，完全不用动 `core/` 内核、`sub_skills/` 与本路由层**。这是本框架的核心设计：新增流程 = 加声明式文件。

一句话记住各文件职责：**`cases.yaml` 定义「做什么」，`app_cards/` 告诉视觉模型「怎么点」，`skills/` 定义「调什么接口」，`routes.yaml` 让路由「找得到你」**。

### 第一步：建叶子目录

叶子目录按四维组织：`businessLine/<业务线>/<App>/<场景>/`。最省事的方式是复制现有叶子改内容：

```bash
cd businessLine
cp -r demo/settings/network <业务线>/<App>/<场景>
```

### 第二步：填叶子的四类文件（均为声明式文件，不写 Python）

**① `SKILL.md` —— 这条流程的 playbook（说明书）**
- 改 frontmatter 的 `name`（须与 §第三步 routes.yaml 的 `skill_name` 一致）与 `description`。
- **只写因流程而异的内容**：目录结构、流程分几个阶段（每阶段标明走 API/UI/ADB）、`[ADB]` 场景的具体坐标与根因。
- 通用约定（预检、步骤规则、报告）用一句话引用 `core/common_playbook.md`，**不要复制**这些章节。照现有叶子骨架改即可。

**② `cases/cases.yaml` —— 真正要跑的步骤（goal），核心文件**
- 每一步用 `[API]` / `[UI]` / `[ADB]` 标记，编排层按标记分段执行（含义见 `core/common_playbook.md` §2）。
- `[UI]` 步用自然语言描述动作（「点击 xx 按钮」「在 xx 页截图」），交给视觉模型驱动。
- `[ADB]` 步写明具体 adb 命令，用于视觉引擎点不中的控件（WebView / 系统开关等）。
- 「操作」与「截图」务必拆成独立步骤（见 demo 用例开头的总则），避免 Manager 漏截。
- 参考 `demo/settings/network/cases/cases.yaml` 骨架照着改。

**③ `app_cards/<app>.md` —— 被测 App 的控件操作手册**
- 告诉视觉模型每个页面有哪些关键控件、怎么定位、哪里容易误点（同名按钮、悬浮控件等）。
- 页面多时可用 `appcard_gen` 子 skill 喂截图自动生成初稿（见第三步小节），再人工核对。
- 复用已有 App（页面没变）可直接沿用其手册，跳过生成。

**④ `skills/*.md` —— 你的 `[API]` 步要调的接口**
- demo 里是离线的 `mock_precheck`（只本地生成主键，不发请求），供参考骨架。
- 换成你自己的：写清接口 URL、请求参数、怎么从返回里取 `order_id`（业务主键）、怎么校验成功。
- 接口重试 / 校验 / 写 run_context 的通用规则见 `core/common_playbook.md` §2.1，照它写。

#### （可选）用 appcard_gen 子 skill 自动生成 App 操作手册
   - **何时需要**：本流程的 App 之前没出现过、UI 与已有手册完全不同时，才需要为它生成一份新 `app_cards/<app>.md`。复用已有 App（页面没变）可直接沿用其手册，跳过本步。
   - **这是一个独立的人工前置步骤**，不在 `/automobile` 回归执行链里自动发生，也**不登记 `routes.yaml`**（它造的是手册，不是回归流程）。先采集本流程会经过的每个关键页面/弹窗各一张截图，放进一个目录。
   - 复制 `sub_skills/appcard_gen/appcard_gen.config.yaml` 为自己的配置，填两项：`screenshots_dir`（截图目录）、`output_path`（指向本叶子的 `app_cards/<app>.md`）。
   - 触发方式：在 `/automobile` 会话中**明确告知「生成 appcard」并给出配置路径**，路由层据此读取并遵循 `sub_skills/appcard_gen/SKILL.md` 执行（它会强校验配置，缺项或截图目录无效即中断），通过后由视觉识别逐图套骨架，生成手册到 `output_path`。该子 skill 仅在用户明确要求时才触发，**不参与常规回归诉求的路由匹配**。
   - 生成后对照截图复核一遍易误点（重复文案、同名按钮、悬浮控件），再进入第三步。

### 第三步：注册路由

在 `core/config/routes.yaml` 加一条 route（Router 自动加载，无需改 `router.py` 与本路由层）：

```yaml
apps:
  <你的App代号>:
    package: <Android 包名>       # open_app 启动用的真实包名
    app_label: <App 显示名>

routes:
  - skill_name: <叶子名>          # 必须与叶子 SKILL.md frontmatter 的 name 一致
    business_line: <业务线>
    app: <你的App代号>            # 与上面 apps 的 key 对应
    category: <品类/子类>
    scene: <场景>
    leaf_dir: businessLine/<业务线>/<App>/<场景>   # 相对 skill 根
    keywords: [便于, 诉求, 匹配, 的关键词]
    description: 一句话描述这条流程（供路由展示与确认）
```

### 第四步：验证

```bash
python3 core/router.py list              # 确认新流程已注册、leaf_exists 为 true
python3 core/router.py match "<你的诉求>"   # 确认关键词能匹配到
```

之后在 CLI 输入 `/automobile 跑一下<你的诉求>` 即会走你的流程。

## 5. 配置与依赖（首次运行）

所有流程共用根级 `.env` 与依赖。首次运行前的环境准备（API Key、Base URL、TEST_UID、ADB、依赖安装、MobileRun Portal）统一见各叶子 playbook 的 §2 预检与 `setup.md`；本路由层不重复。配置文件路径：`automobile/.env`、`automobile/core/config/config.yaml`。

**需要你自己填 URL 的地方**（都是可选能力，不配也能跑通最小流程）：

| 场景 | 需配置的变量 | 不配的后果 |
|------|-------------|-----------|
| 用自建 / 第三方兼容网关（而非 Anthropic 官方端点） | `DECISION_BASE_URL`、`EXECUTOR_BASE_URL`（+ 需 Bearer 鉴权时置 `LLM_AUTH_BEARER=1`） | 默认走 `https://api.anthropic.com`，用官方端点无需改 |
| 截图上传到你自己的图床 / 对象存储 | `PIC_UPLOAD_URL` + `PIC_UPLOAD_SIGN`（+ 接口需登录态时配 `COOKIE_CMD`） | 跳过传图，报告 `cdn_url` 留空 |
| 报文原文落库到你自己的接口 | `REPORT_UPLOAD_URL` | 跳过落库，只生成本地报告 |

> 报告上传（传图 / 落库）默认关闭，只有配了上表对应变量才启用，接口约定与调用细节见 `core/common_playbook.md` 报告发布章节。这几个 URL 脚本内均**无默认地址**，空值即安全跳过或报错，不会指向任何预置地址。
