# 环境准备

首次使用前需完整走一遍以下流程。API Key 和模型配置首次运行时会自动提示，无需手动处理。

> 开始前请确认：**被测 App 已安装在测试设备上。** 若被测流程需要登录，请先登录具备相应权限的测试账号；本仓库自带的 demo 示例流程操作 Android 系统自带的「设置」App（演示飞行模式开关），无需安装额外 App、无需登录账号。

---

## 1. 安装 ADB

macOS：

```bash
brew install android-platform-tools
```

Linux：

```bash
sudo apt install adb
```

验证：

```bash
adb version
```

---

## 2. 连接设备（ADB）

> 本节是执行 Skill 时的连接流程：所有 adb 命令均在电脑端自动执行，手机端只需按提示操作，并把屏幕显示的参数（IP、端口、配对码）提供给执行端，无需手动敲命令。

> ⚠️ **关键前提：手机和电脑必须连同一个 WiFi。** 这是无线调试最常见的失败原因——不在同一网络时，`adb pair` / `adb connect` 会一直超时，且报错不会提示是网络问题，极易误判成配对码或端口错误。**开始连接前需先确认两者处于同一 WiFi，确认通过后再继续。**

### 第 0 步：设备准备（首次需要）

在测试机上：

1. 开启**开发者模式**：设置 → 关于手机 → 连续点击版本号。
2. 开启调试：Android 11+ 开启 **无线调试**（设置 → 开发者选项 → 无线调试）；Android 10 及以下开启 **USB 调试**。

### 第 1 步：确认 adb 可用

```bash
adb version
```

不在 PATH → 按 [§1 安装 ADB](#1-安装-adb) 安装后重试。

### 第 2 步：询问手机系统版本

先问用户：**你的手机是 Android 哪个版本？**

- **Android 11 及以上** → 方式 A（无线调试，免数据线，推荐）。
- **Android 10 及以下** → 方式 B（首次插一次 USB）。

### 方式 A：无线调试（Android 11+）

方式 A 分两种场景:**首次配对**每台设备只做一次;之后每次连接都是**重连**。先尝试 A-2 重连,连不上再走 A-1 首次配对。

#### A-1 首次配对（每台设备只做一次）

1. 手机端操作:设置 → 开发者选项 → **无线调试** → 打开 → 点 **使用配对码配对设备**。
2. 记下弹窗显示的 **`IP:配对端口`** 和 **6 位配对码**。
3. 先核验网络可达（确认在同一 WiFi），再配对：

```bash
ping -c 2 <设备IP>     # 不通说明不在同一 WiFi / IP 错误，先解决再继续，不必白等 adb 超时
```

4. ping 通后执行配对（用弹窗里的**配对端口**）：

```bash
adb pair <设备IP>:<配对端口>
# 提示 Enter pairing code: 时输入弹窗显示的 6 位配对码
```

   看到 `Successfully paired` 即配对成功。

5. **回到「无线调试」主界面**，取那里显示的 **`IP:连接端口`**（与配对端口不同）执行连接：

```bash
adb connect <设备IP>:<连接端口>
adb devices
```

> 易错点：**配对端口（弹窗）≠ 连接端口（主界面）**，两者不要混用。配对弹窗约 1-2 分钟超时，`adb pair` 要在它消失前完成，超时就重新点「使用配对码配对设备」拿新配对码。

#### A-2 之后重连（已配对过，日常用这个）

配对是一次性的信任关系，配过就一直有效，**重连不需要再 `adb pair`，直接 `adb connect` 即可**。但有一个关键点：

> **连接端口每次会变。** 每次关闭再打开无线调试、或手机重启后，「无线调试」主界面显示的连接端口通常会变。所以重连前要**回到主界面看当前的 `IP:端口`**，用最新端口连接：

```bash
adb connect <设备IP>:<当前连接端口>
adb devices
```

也可先用 mDNS 自动发现已配对设备的当前端口（手机「无线调试」需开着），免去手动查端口：

```bash
adb mdns services        # 列出局域网内已配对、正在广播的设备及其当前端口
```

输出中形如 `adb-xxxx._adb-tls-connect._tcp` 的条目可直接连：

```bash
adb connect <设备名>._adb-tls-connect._tcp
```

| 重连遇到的情况 | 处理 |
|----------------|------|
| 无线调试一直开着、端口没变 | 直接 `adb connect <IP>:<端口>` |
| 关过无线调试 / 手机重启过 | 仍直接 `adb connect`，但用主界面**新端口**，无需重新配对 |
| 提示 `failed to authenticate` 或始终连不上 | 配对信息已失效，回到 A-1 重新配对一次 |

#### A-3 完整实测示例

一次真实的首次配对全过程（设备 OPPO PDRM00，IP `172.16.3.187`），可照此对照：

1. 先确认是否已有可用连接，均为空说明需要首次配对：

```bash
$ adb mdns services
List of discovered mdns services        # 空：未配对，mDNS 发现不到

$ adb devices -l
List of devices attached                # 空：当前无设备
```

2. 手机「无线调试」→「使用配对码配对设备」，弹窗显示 `172.16.3.187:37291` 和配对码 `488589`。用**配对端口**配对：

```bash
$ adb pair 172.16.3.187:37291
Enter pairing code: 488589
Successfully paired to 172.16.3.187:37291 [guid=adb-78626283-gFIlfC]
```

3. 配对成功后，看手机「无线调试」**主界面**显示的端口（本例为 `39101`，与配对端口 `37291` 不同），用它连接：

```bash
$ adb connect 172.16.3.187:39101
connected to 172.16.3.187:39101

$ adb devices -l
List of devices attached
172.16.3.187:39101     device product:PDRM00 model:PDRM00 device:OP4EA7 transport_id:7
```

   状态为 `device` 即连接成功，MobileRun 刷新设备列表即可接管。

> 实测注意：
> - 部分机型（如本例）**不广播 connect 服务**，`adb mdns services` 始终为空，无法自动发现连接端口，只能看主界面手动连。
> - 配对弹窗每次打开都是**新的配对端口**，且 1-2 分钟超时；若 `adb pair` 报错，重新点「使用配对码配对设备」拿新端口即可。
> - 之后重连只需第 3 步（`adb connect 主界面端口`），不必再做第 2 步配对。


### 方式 B：Android 10 及以下（首次需插一次 USB）

11 以下没有「无线调试」功能，用经典 tcpip 方案，首次须通过 USB 开启端口：

1. 用 USB 线连接电脑，在手机上点「允许 USB 调试授权」。
2. 开启 tcpip 端口：

```bash
adb tcpip 5555
```

3. 拔掉 USB，取设备 IP（设置 → 关于手机 → 状态信息 → IP 地址）后无线连接：

```bash
adb connect <设备IP>:5555
adb devices
```

> 注意：tcpip 模式在**手机重启后失效**，重启后需重新插线执行 `adb tcpip 5555`。

### 第 3 步：验证连接

```bash
adb devices
```

正常输出（状态为 `device` 即连接成功）：

```text
List of devices attached
<设备IP>:<端口>    device
```

为空或状态异常 → 见 [§4 常见问题](#4-常见问题)。

列出 >1 台设备时，在 `automobile/core/config/config.yaml` 指定要用的设备：

```yaml
device:
  serial: "<设备IP>:<端口>"
```

---

## 3. 安装 MobileRun Portal

MobileRun Portal 是运行在 Android 设备上的辅助应用，MobileRun 通过它的无障碍服务与设备交互。

### 3.1 安装 APK

```bash
mobilerun setup
```

该命令会自动下载匹配版本的 Portal APK 并安装到已连接设备。

手动安装：

```bash
adb install -r /path/to/mobilerun-portal.apk
```

### 3.2 启用无障碍服务

Portal 必须开启无障碍服务，MobileRun 才能读取屏幕、驱动操作。按以下步骤操作：

**1. 检查 Portal 应用状态（关键，部分机型默认禁用）**

部分国产 ROM（OPPO/ColorOS、vivo 等）会把侧载且申请无障碍权限的应用默认置于**禁用 + 强制停止**状态，导致它**不出现在无障碍列表里**。先确认状态：

```bash
adb -s <设备IP>:<端口> shell dumpsys package com.mobilerun.portal | grep -E "enabled=|stopped="
```

- 看到 `enabled=1 ... stopped=false` → 状态正常，跳到第 3 步。
- 看到 `enabled=2`（被禁用）或 `stopped=true`（强制停止）→ 先执行第 2 步恢复。

**2. 启用并启动 Portal（仅状态异常时）**

```bash
adb -s <设备IP>:<端口> shell pm enable com.mobilerun.portal
adb -s <设备IP>:<端口> shell monkey -p com.mobilerun.portal -c android.intent.category.LAUNCHER 1
```

再次执行第 1 步的检查命令，确认变为 `enabled=1 ... stopped=false`。此时无障碍列表里才会出现 Mobilerun Portal。

**3. 开启无障碍服务**

在手机上操作（以 ColorOS 13 为例）：

1. 设置 → 系统设置 → 无障碍 → **已下载的应用**（第三方服务在此分组，不在顶部系统功能列表）。
   - 找不到入口时，在设置顶部**搜索「无障碍」**进入。
2. 找到 **Mobilerun Portal** → 打开服务开关。
3. 弹出无障碍权限警告框 → 点 **允许 / 确定**。

也可用 adb 直接拉起无障碍设置页：

```bash
adb -s <设备IP>:<端口> shell am start -a android.settings.ACCESSIBILITY_SETTINGS
```

**4. 验证已启用**

```bash
adb -s <设备IP>:<端口> shell settings get secure accessibility_enabled
# 返回 1 表示无障碍总开关已开
adb -s <设备IP>:<端口> shell settings get secure enabled_accessibility_services
# 输出中应含 com.mobilerun.portal/.service.MobilerunAccessibilityService
```

部分手机（三星、小米等）还需在开发者选项中额外开启 **"USB 调试（安全设置）"**，否则无障碍开关可能无法操作。

### 3.3 验证

```bash
mobilerun doctor
```

应显示 ADB、Device、Portal、Accessibility、Content Provider 等项全部 ✓。其中 **Accessibility 为 ✗** 时回到 3.2 处理；Portal 未安装时执行 `mobilerun setup`。

---

## 4. 常见问题

### adb devices 为空

检查设备与电脑是否在同一网络、无线调试是否已开启、设备 IP 是否正确。

### adb devices 显示 unauthorized

设备未授权：Android 11+ 用 `adb pair` 配对码方式重新配对；Android 10 及以下先通过 USB 连接一次并在手机上允许授权，再执行 `adb tcpip 5555`。

### 无障碍服务无法开启

- 无障碍列表里**看不到 Mobilerun Portal**：多为应用被 ROM 默认禁用，按 3.2 第 1-2 步用 `pm enable` 启用后再找。
- 检查开发者选项中 **"USB 调试（安全设置）"** 是否开启。
- 尝试卸载重装 Portal APK：`adb uninstall com.mobilerun.portal` → 重新执行 `mobilerun setup`。

### 视觉识别失败

检查设备屏幕是否解锁、被测 App 是否在前台、页面是否被系统弹窗或录屏悬浮窗遮挡。
