# UI 自动化回归测试 — 通用执行 playbook（共享）

> 本文件是**所有回归流程叶子共享的执行约定**，不是 skill，不被路由/`/` 命令触发，
> 而是由各叶子 `SKILL.md` 用相对路径 `core/common_playbook.md` 引用、编排层（Claude）按需读取遵循。
> 与 `setup.md`、`app_cards/*.md` 同属"被引用的共享文档"。
>
> 叶子 playbook 只写**因流程而异**的内容（目录结构、流程阶段、ADB 场景的具体坐标、cases/app_cards/skills）；
> 预检、步骤规则、报告/流水/发布等**通用约定一律以本文件为准**，叶子不重复。
>
> 本文档中相对路径：**共享能力**（`core/`、`reports/`、`screenshots/`、`.env`、`setup.md`）相对 **Skill 共享根 `automobile/`**；
> **本流程定制内容**（`cases/`、`app_cards/`、`skills/`）相对**当次执行的叶子目录**（`LEAF_DIR`）。

## 链路总览

测试链路采用 **Claude 编排 + API Skill + MobileRun UI** 三段式：

- **编排层（Claude）**：读取叶子 `cases/cases.yaml` 中的 goal，按 `[API]` / `[UI]` / `[ADB]` 标记分段执行。段间通过 `order_id` 传递上下文。
- **API 层（Skills）**：`[API]` 步骤匹配叶子 `skills/` 下的子 Skill，由 Claude 直接执行（获取认证、调用接口、解析返回值）。
- **UI 层（MobileRun）**：`[UI]` 步骤拼接为 goal 片段，通过 `GOAL_TEXT` 环境变量传给 `core/runner.py`，由 MobileRun Agent + 视觉模型驱动 App 操作。

共享内核文件：

- `core/runner.py`：UI 执行引擎，接收 `GOAL_TEXT`（单段 UI 操作）与 `LEAF_DIR`（叶子定位）环境变量。
- `core/models.py`：报告数据模型。
- `core/config/config.yaml`：MobileRun、模型、设备和 App Card 配置。
- `core/tools/`：截图工具（`verify_tools.py`）、预检脚本（`doctor_no_update.py`）、报告生成/发布（`generate_report.py` / `publish_report.py`）。

## 1. 预检（Pre-check）

**在执行任何测试步骤之前，必须先完成以下预检。任一项不通过则中断，不执行后续步骤。**

### 1.1 配置检查

1. 读取 `.env` 文件，逐项核对，输出状态表。**必填项须与 `core/runner.py` 的 `CONFIG_FIELDS` 保持一致**（runner 启动时按该表强校验，缺任一必填项即中断）——决策角色与 Executor 各一组模型配置：

```
| 配置项 | 必填 | 状态 |
|--------|:----:|:----:|
| DECISION_API_KEY  | 是 | ✅ / ❌ 空 |
| DECISION_MODEL    | 是 | ✅ / ❌ 空 |
| DECISION_BASE_URL | 是 | ✅ / ❌ 空 |
| EXECUTOR_PROVIDER | 是 | ✅ / ❌ 空 |
| EXECUTOR_MODEL    | 是 | ✅ / ❌ 空 |
| EXECUTOR_API_KEY  | 是 | ✅ / ❌ 空 |
| EXECUTOR_BASE_URL | 是 | ✅ / ❌ 空 |
| TEST_UID          | 是 | ✅ / ❌ 空 |
```

> `TEST_UID` 由需要它的 API 子 skill 使用，runner 本身不校验。是否必填取决于你的叶子流程——示例 demo 叶子离线运行、不需要它，可留空。以你的叶子 `skills/` 实际用到的配置为准。

2. 有缺失时，**提示用户直接编辑 `.env` 文件填入**，给明文件路径和需填的字段，不要通过 CLI 问答逐项收集。
3. 用户填好后通知 Claude，Claude **重新读取 `.env`**，再次输出状态表。
4. 循环直到全部 ✅，输出 `配置检查 ✅ 通过`，进入下一项预检。

### 1.2 模型连通性检查

紧接配置检查之后执行。**预检的探活协议必须与 runner 真实调用对齐**——`runner.py` 通过 mobilerun SDK（基于 llama-index）调用 LLM，按 provider 走不同协议。预检对错协议会出现"预检过、runner 跑挂"的假绿灯。

**对照表（探活端点 / 鉴权头按 provider 区分，Key 一律从 `.env` 读取，不硬编码）：**

| Provider | Base URL 示例 | 探活端点 | 鉴权头 |
|---|---|---|---|
| `OpenAI` / `DeepSeek`（OpenAI 兼容协议） | `https://api.openai.com` | `${BASE}/v1/chat/completions` | `Authorization: Bearer ${KEY}` |
| `Anthropic`（Anthropic 原生协议） | `https://api.anthropic.com` | `${BASE}/v1/messages` | `x-api-key: ${KEY}`（自建/第三方网关若要求 Bearer，则改 `Authorization: Bearer ${KEY}`） |

要点：

- **OpenAI/DeepSeek 协议**：runner 内部打 `/chat/completions`，Base URL 必须是裸域名（如 `https://api.openai.com`），不能带多余后缀，否则拼出错误路径 → 404。
- **Anthropic 协议**：官方端点用 `x-api-key`。若 `EXECUTOR_BASE_URL` / `DECISION_BASE_URL` 指向自建或第三方兼容网关且要求 Bearer 鉴权，runner 会自动注入 `Authorization: Bearer`（见 `core/runner.py` 对网关端点的判定）；探活时按你的网关要求选择鉴权头。
- **请求体最小化**：`max_tokens=4`、`messages=[{"role":"user","content":"hi"}]`，只为验证连通性和鉴权。
- **失败时输出具体错误**：401/403 = Key 无效或鉴权头不对，404 = 端点路径不对（多半是 Base URL 带了多余后缀），连接超时 = Base URL 不可达，中断。

### 1.3 Python 环境检查

Python 3.10+。验证核心依赖是否就绪（import 是全局包，在任意目录执行均可）：

```bash
python3 -c "import mobilerun; print('✅ MobileRun OK')" \
  && python3 -c "import yaml; print('✅ PyYAML OK')" \
  && python3 -c "import httpx; print('✅ httpx OK')"
```

全部 import 成功则通过。任意 import 失败说明依赖未装齐，**进入 Skill 根目录**（`automobile/`，即 `requirements.txt` 所在目录）安装后重试，仍失败则中断：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.4 ADB 设备连接

确认 adb 可用并连接好测试设备，`adb devices` 出现状态为 `device` 的设备即通过。

**连接参数从 `.env` 读取，不通过 CLI 问答逐项收集。** 配置项分两类，**收集时机不同**：

**A. 持久参数**（不过期，预检到本步时直接读 `.env`）：

| 配置项 | 含义 | 取值 |
|--------|------|------|
| `ADB_SAME_WIFI` | 手机与电脑是否同一 WiFi | 是 / 否 |
| `ADB_ANDROID_11_PLUS` | 手机 Android 是否 ≥ 11 | 是 / 否 |
| `ADB_CONNECT_INFO` | 无线调试**主界面**的 `IP:连接端口` | 如 `172.16.3.187:39101` |

**B. 配对参数**（**有过期时间，绝不在流程一开始就让用户填**）：

| 配置项 | 含义 | 取值 |
|--------|------|------|
| `ADB_PAIR_INFO` | 配对弹窗的 `IP:配对端口`（仅首次配对） | 如 `172.16.3.187:37291` |
| `ADB_PAIR_CODE` | 配对弹窗的 6 位配对码（仅首次配对） | 如 `488589` |

> ⚠️ **配对码 1-2 分钟即过期。** 配对弹窗一打开就开始倒计时，配对码失效后 `adb pair` 必然失败。所以配对参数（B 类）**只有在确认确实需要配对、且即将立刻执行 `adb pair` 的那一刻**才提示用户打开弹窗并填入 `.env`——填完马上读取、马上配对。绝不能在 §1.1～§1.3 或本步一开始就让用户填，否则等前置检查跑完配对码早已过期。

执行逻辑：

1. **校验 `ADB_SAME_WIFI`**：非「是」则中断，提示用户先把手机和电脑连同一 WiFi 再把该项改为 `是`。这是无线调试最常见的失败原因（不同网络会一直超时且不报网络错）。
2. **先尝试直接连接**（不碰配对参数）：若 `ADB_CONNECT_INFO` 非空，先 `ping` 验证可达，再 `adb connect ${ADB_CONNECT_INFO}` → `adb devices`。状态为 `device` 即通过，**结束本步，根本不需要配对**。`ADB_CONNECT_INFO` 为空则提示用户回无线调试主界面看 `IP:端口` 填入 `.env` 后重试本步。
3. **仅当第 2 步连接失败、确认需要首次配对时**（且 `ADB_ANDROID_11_PLUS=是`），才进入配对流程：
   - **此刻**提示用户：打开手机「无线调试 → 使用配对码配对设备」，把弹窗的 `IP:配对端口` 填入 `ADB_PAIR_INFO`、6 位配对码填入 `ADB_PAIR_CODE`，**填完立即通知 Claude**（强调配对码会过期，要快）。
   - Claude 立即读取这两项，执行 `adb pair ${ADB_PAIR_INFO}` 并在提示 `Enter pairing code:` 时输入 `${ADB_PAIR_CODE}`。
   - 若报错（多为配对码已过期 / 端口变化），提示用户**重新点开配对弹窗拿新的配对端口和配对码**重填，再试，不要复用旧值。
   - `Successfully paired` 后用 `ADB_CONNECT_INFO`（主界面端口，与配对端口不同）执行 `adb connect`。
4. **Android 10 及以下**（`ADB_ANDROID_11_PLUS=否`）：走 USB tcpip 方案，按 `setup.md` §2 方式 B 处理（首次须插一次 USB 执行 `adb tcpip 5555`），不涉及配对码。
5. 循环直到 `adb devices` 出现状态为 `device` 的设备。每次需用户补填参数都**给明 `.env` 路径和字段**，填好后通知 Claude 重新读取重试。

> 端口易错点：**配对端口（弹窗）≠ 连接端口（主界面）**，且连接端口在每次重开无线调试 / 手机重启后会变。重连前让用户回主界面看当前 `IP:端口` 更新 `ADB_CONNECT_INFO`。详见 [`setup.md`](../setup.md) §2。

未连通不得进入下一项。

### 1.5 MobileRun Portal 检查

直接跑 `mobilerun doctor` 时，CLI 会请求 GitHub 拉取最新 Portal 版本，并在本机落后时**自动下载新 APK**。国内网络下 `release-assets.githubusercontent.com` 默认不可达，每次预检都会卡在升级超时（约 30s）。

**所以预检走包了一层的脚本，跳过 GitHub 版本探活，其余核心检查照常：**

```bash
python3 core/tools/doctor_no_update.py
```

> 该脚本通过 monkey-patch 把 `mobilerun.portal.get_version_mapping` 和 `mobilerun.cli.doctor._get_latest_portal_version` 替换成"立即返回 `None`"，doctor 内部判定走 `WARN("could not check latest")` 分支、**不再触发 `_setup_portal` 升级动作**。源码见 `core/tools/doctor_no_update.py`。

**判定规则（核心 ✓ 即过，版本 ⚠ 忽略）：**

| 检查项 | 要求 | 备注 |
|---|---|---|
| ADB | ✓ | 必须 |
| Device | ✓ | 必须，状态 online |
| Portal | ✓ | 必须，installed |
| Accessibility | ✓ | 必须，enabled |
| Content Provider | ✓ | 必须，reachable |
| State (content / tcp) | ✓ | 必须 |
| Screenshot (content / tcp) | ✓ | 必须 |
| **Portal Version** | ⚠ 可忽略 | patch 后必为 ⚠ `could not check latest`，无需处理 |
| **SDK Version** | ⚠ 可忽略 | 仅版本提醒 |
| **Keyboard** | ⚠ 可忽略 | 文档说会在需要时自动设置 |

任一**核心**项出现 ✗（如 Portal 未安装、无障碍未开启）时，**跳转到 [`setup.md`](../setup.md) §3「安装 MobileRun Portal」按其流程处理**后重试。核心项未全 ✓ 则中断。

**全部预检通过后，输出预检摘要，进入测试执行。**

## 2. 执行规则

按 goal 中标记顺序逐步执行，每一步必须成功才能继续下一步。

### 2.0 初始化运行上下文（每次执行第一步）

段间状态（当前仅 `order_id`）以状态文件 `reports/run_context.json` 为**唯一可信来源**，不依赖对话记忆传递。开始执行 goal 前先初始化：

1. 生成本次运行的 `run_id`：取当前时间戳，格式 `YYYYMMDD_HHMMSS`（如 `20260720_143022`）。本次流程所有步骤都绑定该 `run_id`。
2. **覆写**（非追加）`reports/run_context.json`，清空上一轮残留（`case_name` 取当前叶子流程名）：

```json
{
  "run_id": "20260720_143022",
  "case_name": "<叶子流程用例名>",
  "order_id": null,
  "order_id_set_at": null
}
```

3. 此后任何步骤读取该文件时，**必须校验文件内 `run_id` 与本次 `run_id` 一致**；不一致说明读到的是其它运行的残留，立即中断报错，绝不使用。
4. **清理旧步骤记录（关键，防重复步）**：`order_id` 在首个产出主键的 API 步（第 1 步，示例 demo 里是 `mock_precheck`）成功后才产生。拿到 `order_id`、建 `reports/{order_id}/` 目录时，**若该目录已存在旧 `steps.jsonl`（同一主键重跑），必须先删除**再写第一行。`steps.jsonl` 是追加写，不清理会把上一轮步骤叠加进本轮报告，导致 `total_steps` 翻倍、步骤重复。

### 2.1 [API] 步骤

1. 匹配 `skills/` 下对应 Skill 文件，按其指令执行。
2. **接口重试（统一适用于 `skills/` 下全部 API Skill，底层接口较复杂特殊处理）**：每个 API Skill 的「调用接口」动作**最多尝试 5 次**（首次 + 最多 4 次重试）。
   - **仅对传输/网关层瞬时失败重试**：curl 非 0 退出、连接/读取超时、HTTP 非 2xx、响应体无法解析为 JSON、顶层 `respCode != 0`、顶层 `errMsg` 非空。每次重试前等待 2~3 秒再重新发起同一请求。
   - **业务码失败严禁重试**：响应可正常解析且顶层 `respCode == 0`/`errMsg` 空，但 `respMsg` 解析后业务码 `code != 0`（含 `data.success != true`）。若这些接口是**非幂等写操作（创建单据 / 提交确认等）**，业务失败重试会造成**重复提交**，直接按第 5 点中断处理，不重试。
   - 5 次尝试后仍为传输/网关层失败 → 视为本步失败，按第 5 点输出最后一次错误并中断（首个 API 步失败时亦不写入 `run_context.json`）。
3. **写入 order_id**：产出 `order_id`（主键）的步骤成功后校验 `order_id`（非空、格式合理），通过后连同本次 `run_id` 写回 `reports/run_context.json`（更新 `order_id` 与 `order_id_set_at`）。校验不通过视为本步失败。
4. **读取 order_id**：需要 `order_id` 的步骤，从 `reports/run_context.json` 读取，并依次校验：文件存在、`run_id` 与本次一致、`order_id` 非空且格式合法。任一项不满足则中断并报错，**不得凭对话记忆填入**。
5. 仅当 Skill 明确返回成功（`respCode == 0` 或等价标志）时，视为通过，进入下一步。
6. 失败时输出 Skill 返回的错误信息，**立即中断全部流程**，不执行后续步骤。
7. **记录本步结果**：本步执行完（无论成败）后，**追加一行 JSON** 到 `reports/{order_id}/steps.jsonl`（格式见 §2.4）。API 步的 `detail` 里放 Skill 名、入参关键项、respCode、order_id、主/子状态等（自由字段，只做展示）。**漏记则报告缺该步**。

### 2.2 [UI] 步骤

1. 将当前连续的 `[UI]` 步骤拼接为完整 goal 文本，以 `GOAL_TEXT` 环境变量传入 `runner.py`。
   - **必须保留 `cases.yaml` 中的原始步号**：不要把每段 UI 重新从 1 编号。否则该段在 GOAL_TEXT 里的步号与完整用例对不上，日志、报告、人工核对都会错位。
   - **GOAL_TEXT 必须经文件传入，严禁命令行内联拼接（硬约束）**：goal 文本同时含大量中文与 `order_id` 等变量时，用 `export GOAL_TEXT='…中文…$OID…'` 在 bash 命令行内联拼接**会把变量破坏成 UTF-8 代理字符（surrogate）**，注入 prompt 后 mobilerun SDK 调 LLM 立即崩 `UnicodeEncodeError: surrogates not allowed`，Manager 第一轮决策就失败、runner 退出码 1。正确做法：先用 Python/heredoc 把完整 goal（order_id 已替换为实际值）写到临时文件（如 `/tmp/goal_seg<N>.txt`，`encoding='utf-8'`），再 `export GOAL_TEXT="$(cat /tmp/goal_seg<N>.txt)"`。
   - **启动 runner 前必须回读校验 GOAL_TEXT**：`python3 -c "import os;g=os.environ['GOAL_TEXT'];assert g.count('<order_id>')==<预期次数>;assert not any(0xD800<=ord(c)<=0xDFFF for c in g)"`——确认 order_id 出现次数符合预期、且不含任何 surrogate；不通过则不得启动，先修 goal 文件。
2. goal 文本中的 `order_id`，**从 `reports/run_context.json` 读取**（校验同 §2.1 第 4 点），替换为实际值；不从对话记忆取。写入上面第 1 点的临时文件时即完成替换。
3. runner 退出码为 `0` 视为通过；非 `0` 视为失败。
4. 失败时保留 `reports/` 和 `screenshots/` 中的内容，**立即中断全部流程**。
5. **记录本步结果**：本段每个 goal 步执行完后，**逐步追加一行 JSON** 到 `reports/{order_id}/steps.jsonl`（格式见 §2.4）。UI 步的 `detail` 里放通过/失败、失败原因（如有）等；截图不进 steps，由生成器扫 `screenshots/{order_id}/` 目录另行还原为 `screenshots[]`。
6. **goal 步骤编写约定（拆分原则）**：每个 UI 步骤只描述一个原子动作（一次点击、一次输入、一次截图）。**绝不把多个动作塞进一步**——实跑中 Manager 倾向把复合步骤里的业务动作一口气做完、跳过中间的 `capture_screenshot`，导致截图漏截、报告残缺。
   - 例：「切 Tab → 搜索 → 截图 → 点卡片进详情 → 截图」必须拆成「切 Tab」「搜索+截图」「进详情+截图」等独立步骤。
   - 标注「完成后截图」的步骤，要求**先成功调用 `capture_screenshot` 再进入下一步，未截图不得继续**，并在 goal 开头总则里写明这一点。
   - 点击弹窗按钮（如多处出现的「确认」）时，**结合弹窗文案/标题限定在弹窗范围内**，避免误点背景同名主按钮（见叶子 `app_cards/<app>.md` 易误点）。
   - 工具调用参数统一用 **ASCII 双引号** `"`，不要用全角引号 `”`，以防按字面解析时定界符不被识别。
   - 注意：拆分降的是 Manager 单步决策歧义与漏截风险，**不减少 step 总数或总时长**（截图独立成步后 step 数略增），与 429 限流无关。
7. **进度轮询节奏（编排层盯后台任务的等待策略）**：`runner.py` 用 `Bash run_in_background=true` 启动后，编排层（Claude）盯它的输出时**统一用固定兜底超时轮询，不做「看到上一条成功就提前推进」之类的自动判断**——实测那种自动判断会被 Manager 的状态幻觉误导（它会谎报已完成某步），导致编排层跟着误判。
   - **超时参数从 `.env` 读取 `POLL_TIMEOUT`（单位秒，默认 30）**：每轮用 `TaskOutput task_id=… block=true timeout=${POLL_TIMEOUT*1000}`（毫秒）取增量输出，固定按这个节奏拉取，不依据日志内容提前返回或跳步。`.env` 未配置时按 30s 兜底。
   - **只回写「增量」新行，绝不重复整屏日志**：`TaskOutput` 每轮返回的是从任务启动到当前的**累积输出**，编排层**只把本轮相对上一轮新增的几行贴回 CLI**（不解读、不据此判断「该推进了」）。把几千字的完整日志每轮重贴一遍，会让用户误以为「刷屏但原地不动 / 卡住了」——这是观感灾难，务必避免。
   - **LLM 请求超时属正常兜底，需主动向用户说明、不得当作卡死**：经网关/远程端点调用时单次 LLM 请求可能耗时数十秒至 `LLM_TIMEOUT` 秒，日志出现 `Attempt 1 timed out after N seconds` 后由 SDK 自动重试并恢复（下一条 `HTTP 200` 即恢复）。首次遇到时应主动告知用户「这是网关偶发慢响应+自动重试，非卡死，最多等约 `LLM_TIMEOUT × (retries+1)` 秒」，避免用户干等误判。
   - 退出轮询的条件只有三个：① 后台任务结束（runner 退出）；② 用户主动喊停；③ 输出里出现明确错误（`UI 段失败` / 报错堆栈）。除此之外即使一时没有新输出也继续下一轮 `TaskOutput`，由 runner 自身的超时/结束来终止，编排层不替它判断。
   - **卡死兜底**：runner.py 已在启动时把 mobilerun SDK 的应用级 LLM 超时从写死的 500s 收紧为 `.env` 的 `LLM_TIMEOUT`（见 `core/runner.py` 的 `_patch_sdk_inference_timeout`），LLM 流式中途僵死时 SDK 会在 `LLM_TIMEOUT` 秒内自己超时并按 retries 重试，**正常情况下无需人工 kill**。仅当某段日志「末尾时间戳」距今已超过 `LLM_TIMEOUT × (retries+1)` 且进程 CPU 持续 0%（`ps -o stat,%cpu`）才判定为真卡死：此时 kill 该 runner，核对已落盘截图与当前 App 页面状态，从**下一个未完成的 goal 步**重启该段（保留原始步号），不重跑已成功步骤。
   - 该值是**编排层查进度的节奏**，与 runner 内部操作 App 的等待无关；如需调整，改 `.env` 里的 `POLL_TIMEOUT` 即可。
8. **段后强制核对补截（硬步骤，杜绝漏截）**：每段 `runner.py` 跑完（无论它报 `request_accomplished success=true` 还是失败），编排层**必须按本段 goal 里所有 `[截图] step_name=...` 列出预期截图清单，逐一核对 `screenshots/{order_id}/` 下是否存在对应 `*_{step_name}.png` 文件**。
   - **绝不以 runner / Manager 的自述为准**：Manager 是自主决策 Agent，对「截图」这种无外部反馈的步骤存在状态幻觉——会把它在内部 plan 标记为「已完成」却**没真正调用 `capture_screenshot` 工具**，并照样回 `success=true`。判定截图是否完成的**唯一依据是磁盘上的文件**。
   - **缺哪张当场补**：核对发现缺失的 `step_name`，由编排层直接 `adb -s "$D" exec-out screencap -p > "screenshots/{order_id}/$(date +%s)_{step_name}.png"` 补截（文件名沿用 `core/tools/verify_tools.py` 的 `{unix_ts}_{step_name}.png` 归档规则），补后再校验文件为有效 PNG（`file` 确认）。**当前页面已离开该步现场时不可补造**——只在 runner 卡在该步之前、页面仍是该步状态时补；若已翻页则如实标注该截图缺失、不伪造。
   - 核对通过（或已补齐）才算本段结束，再进入下一段或 API 步骤。报告「截图清单」与明细表须与磁盘实际文件一致，补截的要注明「Manager 漏截，编排层 adb 补截」。

> **三套编号别混淆**（向用户解释进度时务必区分）：
> 1. **cases.yaml 的 goal 步号**——完整用例的权威编号，报告与人工核对一律以此为准。
> 2. **GOAL_TEXT 的段内步号**——按上面第 1 点要求，必须沿用 goal 原始步号，不重编。
> 3. **CLI 里的 `Step N/上限` 与 `▶ [Manager 第N轮决策]`**——这是 MobileRun **Manager 的决策轮次**，Manager 会把一个 goal 动作拆成多轮，故此数字与 goal 步号**不一一对应**，`上限` 是 `MAX_STEPS`（决策轮次上限），不是 goal 步数。汇报进度时不要拿它冒充 goal 步号。

### 2.3 [ADB] 步骤（编排层直接 adb 注入，不走 MobileRun）

部分控件 MobileRun 的交互（`type` 注入 / `tap` 点击）无效，必须由编排层（Claude）在 `runner.py` 之外直接用 `adb` 操作。`cases.yaml` 中标记 `[ADB]` 的步骤即属此类。**具体走 ADB 的场景与坐标见各叶子 `SKILL.md`**（因 App/品类而异），本节只定通则。

> **通则**：WebView（H5）渲染的控件，`uiautomator dump` 抓不到节点、MobileRun 点不中也输不进，一律走 `[ADB]`：能 dump 到坐标的用 bounds 中心，拿不到的截图定位坐标，`adb shell input tap/text` 操作，**每步后 dump 或截图校验流转，不采信 Manager 自述**。
>
> **坐标来源优先级：`app_cards` 标注 > dump 拿 bounds > 截图肉眼估**。① 静态控件（宫格、搜索图标、固定主按钮）先查叶子 `app_cards/<app>.md` 的坐标标注，读一次准一次；② 动态控件（列表卡片、位置会变的）app_card 标不了，dump UI 树拿其 `bounds` 中心（精确像素，非肉眼估）；③ 仅当 app_card 无标注、dump 又抓不到节点（H5 弹窗）时，才 `screencap` 截图肉眼估坐标——最不可靠，注意截图像素宽↔设备宽换算，能避则避。

**设备 id 取 `.env` 的 `ADB_CONNECT_INFO`，下文记为 `$D`。** 三类高频 ADB 动作的标准执行序（叶子场景据此套用，仅坐标不同）：

- **WebView 宫格/按钮点击**：确认当前页（dump 有预期锚点节点）→ `adb -s "$D" shell input tap <cx> <cy>`（坐标查叶子 app_card）→ sleep 2-3 秒后 dump/截图**强制校验跳转**（出现目标页锚点节点）→ 未跳转重试一次，仍失败中断。
- **搜索框输入订单号**（标准 `EditText` + 第三方 IME，MobileRun `type` 写不进，须走 InputManager）：dump 拿 EditText 的 `bounds` 中心 → `adb -s "$D" shell input tap <cx> <cy>` 聚焦 → `adb -s "$D" shell input text "<order_id>"`（order_id 从 `run_context.json` 读，校验同 §2.1 第 4 点）→ 再 dump **回读校验** EditText 的 `text` 逐字符等于 order_id（唯一判定依据，不靠截图/Manager 自述）→ `adb -s "$D" shell input keyevent 66` 发起搜索。
- **H5 弹窗按钮点击**（dump 抓不到弹窗按钮节点）：`adb -s "$D" exec-out screencap -p > /tmp/x.png` 截图定位（注意截图像素宽↔设备宽换算比例）→ `adb -s "$D" shell input tap <cx> <cy>` → sleep 3-4 秒后截图**强制校验页面流转** → 未流转按新截图重定位重试一次，仍失败中断。

> 失败即中断：任一 adb 命令非 0 退出、dump/截图失败、回读 text 不等于 order_id、或点击后页面未流转，立即中断并保留现场，不执行后续步骤。

### 2.3bis 段间状态传递

- 段间 `order_id` 一律经 `reports/run_context.json` 传递（写入见 §2.1 第 3 点，读取见 §2.1 第 4 点 / §2.2 第 2 点），保证各段（API → UI → ADB）取到的是**同一次运行、同一主键**的 id，不会用到上一轮残留，也不依赖对话记忆。
- 上下文异常（文件缺失、`run_id` 不匹配、`order_id` 为空或格式非法、接口返回 404 等）时，先生成执行报告（标记失败原因与当前步骤），再中断并提示用户重新开始。

### 2.4 步骤记录 `steps.jsonl`（报告 steps[] 的唯一数据源）

每个 `[API]`/`[UI]`/`[ADB]` 步执行完（无论成败），编排层**追加一行 JSON** 到 `reports/{order_id}/steps.jsonl`。这是把 §2.1.7、§2.2.5 已要求记录的「本步结果」从对话记忆**落成文件**，收尾时由 `core/tools/generate_report.py` 读取拼成报告的 `steps[]`。

> **谁创建、何时创建**：本文件**由编排层（Claude）创建和维护，无脚本自动生成**（`skills/*.md` 是文档不是代码，API 步由编排层照文档执行，没有统一代码入口可挂钩子）。创建时机 = 第 1 步（首个产出主键的 API 步）成功、拿到 `order_id`、建 `reports/{order_id}/` 目录时写入第一行（同一主键重跑先按 §2.0 第 4 点删旧文件）。此后每步追加一行，全靠编排层自觉——**漏记即缺步**，这是本链路唯一非代码保证的一环。

**每行字段（与 `core/config/report_template.json` 的 steps[] 元素一致）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| step_no | int | goal 步号，**沿用 `cases.yaml` 原始步号**，不重编 |
| step_type | string | `API` / `UI` / `ADB` |
| description | string | 步骤描述 |
| result | string | `PASS` / `FAIL` / `SKIP` / `NA` |
| duration_sec | int \| null | 本步耗时秒；未单独计时置 null |
| detail | object \| null | 自由 JSON，只做展示。API 步放 respCode/order_id/主子状态等；失败步放错误原因；无内容置 null |
| ts | string \| 省略 | **可选**，本步完成的 ISO8601 时刻。生成器取最后一条带 ts 的步骤作报告 `end_time`；仅此用途，组装报告时会剥离、不进最终 `steps[]`。末步带上即可 |

**示例（两行）：**

```jsonl
{"step_no": 1, "step_type": "API", "description": "mock_precheck 前置检查", "result": "PASS", "duration_sec": 1, "detail": {"skill": "mock_precheck", "code": 0, "order_id": "..."}, "ts": "2026-07-20T10:10:19"}
{"step_no": 6, "step_type": "ADB", "description": "切换飞行模式为开", "result": "PASS", "duration_sec": 2, "detail": {"airplane_mode_on": 1}, "ts": "2026-07-20T10:25:40"}
```

**约定：**
- **初始化时清空**：每次执行 §2.0 覆写 `run_context.json` 的同时，若 `reports/{order_id}/` 已存在旧 `steps.jsonl` 需删除；`order_id` 在首个产出主键的 API 步才产生，故第 1 步成功、拿到 order_id 后即建目录并写第一行。
- **截图不进 steps.jsonl**：截图由生成器扫 `screenshots/{order_id}/` 目录、按文件名 `{ts}_{step_name}.png` 还原为报告的 `screenshots[]`，不在此记录。
- **漏记即缺步**：`steps.jsonl` 是报告步骤的唯一来源，漏写某步则报告缺该步。校验（`report_schema.validate_report`）只警告不阻断，但会提示 total_steps/passed_steps 不一致。

## 3. 报告输出

全部步骤执行完毕后（或任一步骤失败中断时），生成 HTML 执行报告。

**按订单号归档**：截图和报告都按本次 `order_id` 建子目录存放（`order_id` 取自 `reports/run_context.json`）：

- 截图目录：`screenshots/{order_id}/{timestamp}_{step_name}.png`（由 `core/tools/verify_tools.py` 自动按订单号归档）。
- 报告路径：`reports/{order_id}/report_{timestamp}.html`。生成报告前先 `mkdir -p reports/{order_id}`。
- 若 `order_id` 缺失（流程在拿到主键前就失败），截图回退到 `screenshots/_no_order/`，报告写入 `reports/_no_order/report_{timestamp}.html`。
- 报告内截图用相对路径 `../../screenshots/{order_id}/{filename}.png` 引用（报告在 `reports/{order_id}/`，需上跳两级再进 `screenshots/{order_id}/`）。

### 3.1 报告模板

报告为单文件 HTML，内联样式，可直接在浏览器打开。结构如下：汇总表（用例 / 优先级 / 起止时间 / 总耗时 / 结果 / 步骤通过数）、执行明细表（# / 类型 / 描述 / 结果 / 耗时 / 关键信息）、失败详情（仅失败时输出，含失败原因 / order_id / 当前页面状态）、截图清单。截图一律用相对路径 `../../screenshots/{order_id}/{filename}.png` 内联引用，保证 HTML 在原位置打开能直接显示图片。

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>回归测试报告 - {case_name}</title>
  <style>
    body { font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; color: #1f2329; }
    h1 { font-size: 22px; }
    h2 { font-size: 18px; margin-top: 28px; border-bottom: 1px solid #e5e6eb; padding-bottom: 6px; }
    table { border-collapse: collapse; width: 100%; margin: 12px 0; }
    th, td { border: 1px solid #e5e6eb; padding: 8px 12px; text-align: left; }
    th { background: #f7f8fa; }
    .pass { color: #00a870; font-weight: 600; }
    .fail { color: #e34d59; font-weight: 600; }
    img { max-width: 360px; border: 1px solid #e5e6eb; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>回归测试报告</h1>
  <table>
    <tr><th>用例</th><td>{case_name}</td></tr>
    <tr><th>优先级</th><td>{priority}</td></tr>
    <tr><th>开始时间</th><td>{start_time}</td></tr>
    <tr><th>结束时间</th><td>{end_time}</td></tr>
    <tr><th>总耗时</th><td>{total_duration}</td></tr>
    <tr><th>结果</th><td class="{pass|fail}">{PASS 或 FAIL}</td></tr>
    <tr><th>步骤</th><td>{passed}/{total} 通过</td></tr>
  </table>
  <h2>执行明细</h2>
  <!-- # / 类型 / 描述 / 结果 / 耗时 / 关键信息；被合并未单独截图的步标注「并入第N步计时」 -->
  <!-- 仅失败时输出「失败详情」：失败原因 / order_id / 当前页面状态 -->
  <h2>截图清单</h2>
  <!-- 每行：步骤号 + <img src="../../screenshots/{order_id}/{ts}_{step_name}.png"> -->
</body>
</html>
```

### 3.2 耗时记录（goal 步维度）

耗时一律按 **cases.yaml 的 goal 步号** 记录，每步一个耗时，单位秒，填入明细表「耗时」列；并在汇总表给出总耗时。口径：

- **API 步**：由编排层（Claude）在调用接口前后各取一次时间戳，差值即本步耗时，精确。
- **UI 步**：以该步**截图文件名前缀的 unix 时间戳**为本步完成时刻，耗时 = 本步完成时刻 − 上一锚点。上一锚点取「上一 goal 步的完成时刻」；若是本 UI 段第一步，则取「该段 `runner.py` 启动时刻」。
- **被 Manager 合并、未单独截图的步**：无法独立切分，耗时栏标注「并入第N步计时」（N 为合并到的那一截图步），不强行编造数字。
- **总耗时**：流程开始（第 1 步 API 起）到最后一步完成的墙钟时间。

> 为什么用截图时间戳而非 runner 内部计时：UI 段成段交给 runner，Manager 会合并/拆分动作，runner 内部无法对应到 goal 步号；截图文件名前缀时间戳是唯一能稳定锚定到 goal 步的时刻来源。该口径下单 UI 步耗时含「上一步完成到本步截图」之间的全部 Manager 决策与执行时间，为近似值，够用于发现异常慢的步骤。

### 3.3 结构化 report.json（发布数据源，自动生成）

结构化报告 `reports/{order_id}/report.json` **由生成器自动产出，不手工拼**：

```bash
python3 core/tools/generate_report.py {order_id}
```

生成器按固定模版 `core/config/report_template.json` 拼装，数据来源：
- **报告头**：`order_id`/`run_id`/`case_name` 取自 `run_context.json`；`skill_name`/`business_line`/`app`/`category`/`scene` 按 `LEAF_DIR` 匹配 `core/config/routes.yaml`；`priority` 按 case_name 匹配 `cases.yaml`；`result`/`total_steps`/`passed_steps`/`duration_sec` 由 steps 汇总算。
- **`steps[]`**：读 §2.4 的 `reports/{order_id}/steps.jsonl`（边跑边记的产物）。
- **`screenshots[]`**：扫 `screenshots/{order_id}/`，按文件名 `{ts}_{step_name}.png` 还原，`cdn_url` 留空、发布阶段回填；并带非契约字段 `local_file` 供 `publish_report.py` 按文件名对齐 CDN（上传前脚本自动剥离）。

关键约定：
- **格式真相源**：字段结构以 `core/config/report_template.json` / `report_template.md` 为准，可执行校验为 `core/tools/report_schema.py`。生成后自动跑校验，**只警告、不阻断**（缺字段 / total_steps / passed_steps / 截图 step_no 对不上会提示）。
- **无需手拼**：报告发布用共享脚本 `core/tools/publish_report.py`，它在 report.json 不存在时会自动先调本生成器，故正常收尾直接跑发布即可；单独调本脚本用于调试或补生成。
- 流程在拿到主键前就失败、无 order_id 时，无 steps.jsonl 与截图目录，发布环节跳过。

## 4. 报告发布（默认只出本地报告，外部上传可选）

**作为整个流程的最后一步，执行报告发布**。这是所有回归流程**共用的公共能力**，由共享脚本 `core/tools/publish_report.py` 实现，叶子不重复实现，编排层只需调用一次：

```bash
python3 core/tools/publish_report.py {order_id}
```

**默认行为 = 只生成本地报告，不请求任何网络、不依赖任何外部服务**，开箱即用：

1. report.json 不存在则先调 §3.3 生成器。
2. 生成 `report-json.json`（机器读）与 `report-json.md`（人看/存档），校验（`report_schema`，只警告不阻断）并剥离辅助字段 `local_file`。

**可选：上传发布（适配层，仅在 `.env` 配置了相应变量时启用）**

- **传图**：配置 `PIC_UPLOAD_SIGN`（+ 可选 `COOKIE_CMD` 取登录态）后，调 `pic_upload` 子 skill 批量上传 `screenshots/{order_id}/` 下截图，把 CDN 链接回填进 `screenshots[].cdn_url`。未配置则跳过，`cdn_url` 留空。
- **落库**：配置 `REPORT_UPLOAD_URL` 后，调 `report_upload` 子 skill 把 `report-json.json` **原文**上传到你自己的接口。未配置则跳过。

> 接入自己的外部平台（图床 / 报告库 / 使用流水）时，在 `.env` 配置对应变量、或在 `publish_report.py` 里增加你自己的发布步骤即可。框架本身不绑定任何特定平台。

约定与失败处理：
- 前置依赖：`reports/{order_id}/report.json` 已由 §3.3 生成。启用传图时还需 `screenshots/{order_id}/` 有截图。
- **图片上传失败**（`upload_result.json` 的 `failed > 0` 或某条 `code != 0`）须在 CLI 如实告知，未传成功的截图其 `cdn_url` 为 `null`。
- **上传失败或接口不可达**不影响本地 report-json 已生成，按脚本提示可手动补传，不伪造成功。
- 流程在拿到 order_id 前就失败、无 order_id 时跳过本节（无截图与 report.json 可发布）。

