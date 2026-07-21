---
name: demo-settings-network
description: 示例叶子 playbook —— 演示如何用 [API]/[UI]/[ADB] 三类步骤编排一条 UI 自动化流程。以 Android 系统设置 App 为被测对象，无任何外部业务依赖。由 automobile 路由层识别诉求后调用执行。
---

# Demo · 系统设置 · 网络与互联网 — 示例 playbook

> 本文件是一个**示例叶子 playbook**，用来演示这个框架怎么写一条回归流程。
> 它操作 Android 自带的「设置」App（`com.android.settings`），不依赖任何账号、接口或内网服务，任何装了 Android 模拟器/真机的人都能跑通。
>
> 由顶层路由 Skill `automobile`（见 `../../../../SKILL.md`）识别诉求后定位到本叶子、设好 `LEAF_DIR` 指向本目录，再读取并遵循执行。
>
> **预检、执行规则、报告等通用约定，一律遵循 [`core/common_playbook.md`](../../../../core/common_playbook.md)（相对 Skill 根 `automobile/`），本文件不重复。** 本文件只写本流程**因流程而异**的内容：目录结构、流程阶段、`[ADB]` 场景坐标，以及本流程的 cases/app_cards/skills。

## 1. 本叶子目录

```
businessLine/demo/settings/network/       # 本叶子（= LEAF_DIR）
├── SKILL.md          本文件（流程 playbook）
├── cases/cases.yaml  本流程回归用例（goal 内 [API]/[UI]/[ADB] 标记步骤类型）
├── app_cards/settings_app.md  设置 App 页面/控件操作手册
└── skills/           本流程 API 子 Skill（mock_precheck —— 一个可离线运行的示例接口）
```

共享内核与产物位于 Skill 根 `automobile/` 下：`core/`（runner/models/config/tools）、`reports/`、`screenshots/`、`.env`。完整结构见路由层 `automobile/SKILL.md`，通用执行约定见 `core/common_playbook.md`。

## 2. 要执行的示例流程

- 被测 App：Android 系统设置（`com.android.settings`）。
- 场景：打开设置 → 进入「网络和互联网」→ 切换飞行模式开关 → 关回，验证开关状态可读可控。
- 流程目标：演示三类步骤如何协作——用 `[API]` 做一次前置检查（示例 mock，返回一个 run_id 当作贯穿上下文的主键），`[UI]` 做视觉驱动的页面操作，`[ADB]` 做 UI 引擎点不中时的直接注入。

| 阶段 | 执行方式 | 操作内容 | 匹配 Skill / 页面 |
|------|----------|----------|-------------------|
| 1. 前置检查 | API | 调用 mock_precheck 生成本次 run 主键 | `skills/mock_precheck.md` |
| 2. 打开设置 | UI | 启动设置 App，停在首页 | 设置首页 |
| 3. 进入网络设置 | UI | 点击「网络和互联网」 | 网络和互联网页 |
| 4. 切换飞行模式 | ADB | 用 adb 切换飞行模式开关并回读状态 | 网络和互联网页 |
| 5. 复位 | UI | 关回飞行模式，截图存档 | 网络和互联网页 |

goal 中每步标注 `[API]` / `[UI]` / `[ADB]`，含义与执行规则见 `core/common_playbook.md` §2。

## 3. 本流程 [ADB] 场景（坐标与根因）

`[ADB]` 步骤的通则、标准执行序与失败即中断规则见 `core/common_playbook.md` §2.3。本示例演示一个最常见的 `[ADB]` 场景：**开关类控件用 UI 视觉点击不稳定，改用 adb 直接读写系统状态**。

### 场景一：切换飞行模式（第 4 步）
- 根因：飞行模式开关是系统级 Switch，不同 ROM 的无障碍节点文案/位置差异大，视觉点击容易点偏或误判状态。用 `adb shell settings` 直接读写 `airplane_mode_on` 更稳、可回读校验。
- 执行序（按 §2.3「失败即中断」规则）：
  1. 读当前状态：`adb -s "$D" shell settings get global airplane_mode_on`（0=关，1=开）。
  2. 切换：`adb -s "$D" shell settings put global airplane_mode_on 1` 并广播 `adb -s "$D" shell am broadcast -a android.intent.action.AIRPLANE_MODE`。
  3. 回读校验：再次 `settings get global airplane_mode_on` 必须等于 1，否则本步失败中断。
  4. 复位在第 5 步做（put 回 0 + 广播）。
- **第 4 步严禁 `[UI]` 点开关**：以 `adb settings` 读写为准，回读值是唯一判定依据，不采信 Manager 自述。

> 说明：这是把「真实项目里点不中的 WebView/系统控件改走 ADB」这一模式，用一个无害的系统开关演示出来。你接入自己的 App 时，把坐标/命令换成你的控件即可。

## 4. 使用方式

本 playbook 不直接对用户暴露入口。用户在 CLI 输入 `/automobile` 后由路由层匹配到本叶子，设好 `LEAF_DIR`，从 `core/common_playbook.md` §1 预检开始执行 → 本流程用例 → 报告。首次运行缺必填配置项时按预检 §1.1 提示填入 `automobile/.env`。执行结果在 `reports/`（报告）和 `screenshots/`（截图）中查看。
