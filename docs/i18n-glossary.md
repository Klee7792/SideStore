# SideStore 简体中文术语对照表

本文件是 SideStore 简体中文（zh-Hans）本地化**唯一**的术语依据。
新增/修改译文前请先查这里；如果这里没有，才需要新增术语（并同步更新本文件）。

适用范围：主 App（`AltStore/` + `SideStore/` + `Shared/` 三个目录，均打进同一个 app bundle）。
本期**不含** `AltWidget/`、`SideBackup/`、`Dependencies/`。

---

## 1. 核心概念术语

| English | 简体中文 | 说明 |
| --- | --- | --- |
| Source | 软件源 | 对应 UI 里的 “Sources” 一律译“软件源”，不要译成“来源/源”。 |
| Add Source | 添加软件源 | |
| Recommended Sources | 推荐软件源 | |
| Pairing File | 配对文件 | 文件名 `.mobiledevicepairing` 不译。 |
| Device Pairing | 设备配对 | |
| Wireless Pairing | 无线配对 | |
| Provisioning Profile | 描述文件 | 文件名 `.mobileprovision` 不译。 |
| Reset Provisioning Profile | 重置描述文件 | |
| Certificate | 证书 | |
| Signing Certificate | 签名证书 | |
| Active Signing Certificate | 当前生效的签名证书 | |
| Team ID | 团队 ID | |
| App ID | App ID | 专有名词，保留原文（含复数 App IDs）。 |
| Bundle ID | Bundle ID | 保留原文；Bundle Identifier 作为标签时同样保留。 |
| Entitlement | 权限 | 不要译成“授权/权益”。 |
| Permissions | 权限 | 与 Entitlement 在中文里同形，需按上下文区分时可用「权限（Entitlement）」。 |
| Privacy Permission | 隐私权限 | |
| App Extension | 应用扩展 | 复数“应用扩展”；单复数在中文不区分时保持同一译法。 |
| App Group | App Group | 保留原文。 |
| UDID | UDID | 保留原文。 |
| Refresh | 刷新 | |
| Refresh Attempts | 刷新记录 | 特指 Settings 里那张刷新历史表。 |
| Revoke | 吊销 | |
| Sideload / sideloading | 侧载 | |
| Sign / signing | 签名 | |
| Resign | 重新签名 | 与 Sign 区分时必须用“重新签名”。 |
| Reinstall | 重新安装 | |
| Activate / Deactivate | 启用 / 停用 | |
| Active / Inactive | 已启用 / 已停用 | |
| Onboarding | 引导流程 | 单独作标题时可简称“引导”。 |
| Toast | 轻提示 | UI 控件名，仅在需要指代控件时使用。 |
| Error Log | 错误日志 | |

---

## 2. 保留英文原文的词

以下词**一律不译**，包括大小写形式：

* 产品与项目名：`SideStore`、`AltStore`、`AltWidget`、`SideBackup`
* 工具与服务：`SideJITServer`、`LocalDevVPN`、`WireGuard`、`minimuxer` / `MINIMUXER`、
  `Anisette` / `ANISETTE`、`SideSign` / `SIDESIGN`、`em_proxy` / `EMProxy`、
  `Patreon`、`Discord`、`GitHub`
* Apple 平台与技术：`Apple ID`、`Apple TV`、`Apple Watch`、`CarPlay`、`iPad`、
  `iPhone`、`Mac`、`Vision Pro`、`Bonjour`、`mDNS`、`iTunes`、`Finder`、
  `Files`（译作“文件”应用时保留引号）、`Keychain`（译作“钥匙串”）、
  `X.509`、`XML`、`Info.plist`、`Mach-O`
* 技术标识符：`ADI`、`adi.pb`、`SideStore.conf`、`BASE64_CERT`、`UUID`、
  `SHA-1`、`SHA-256`、`IPv4`、`IPv6`、`UDP`、`TCP`、`PIN`、`SMS`

> **保留英文的词，大小写必须跟随源码。**
> 原 UI 用全大写作为分区标题的设计语言时（如 `ANISETTE`、`SIDESIGN`、
> `MINIMUXER`），本地化**不要顺手改成 Title Case**：同屏邻近的英文标签会一个全大写、
> 一个首字母大写，视觉上不一致。判断依据就是源码里的字面量长什么样，值就保留什么样。
>
> 中英混排的长标题（如 `MINIMUXER BACKEND` → `MINIMUXER 后端`、
> `WIREGUARD CONFIGURATION` → `WIREGUARD 配置`、
> `EMPROXY & WIREGUARD` → `EMPROXY 与 WIREGUARD`）保留**前半段的原始大小写**，
> 只译后半段。
>
> 反过来，被译成中文的 section header（`ACCOUNT` → 账户、`ADVANCED SETTINGS` →
> 高级设置 等）没有大小写问题，正常译。

---

## 3. 标准 iOS 界面用词（Apple 官方中文优先）

| English | 简体中文 |
| --- | --- |
| Cancel | 取消 |
| Done | 完成 |
| OK | 好 |
| Continue | 继续 |
| Try Again / Retry | 重试 |
| Copy | 拷贝 |
| Paste | 粘贴 |
| Save | 存储 |
| Delete | 删除 |
| Remove | 移除 |
| Edit | 编辑 |
| Select | 选择 |
| Close | 关闭 |
| Search | 搜索 |
| Share | 共享 |
| Back | 返回 |
| More / Less | 更多 / 收起 |
| None | 无 |
| Allow / Don't Allow | 允许 / 不允许 |
| YES / NO | 是 / 否 |

> **`YES` / `NO` 的两种用法必须区分开**（见
> `SideStore/Views/Components/InfoPlistCustomizationCoreView.swift`）：
>
> 1. **用户可见标签**（`:845-846`、`:916-917` 的 `Text("YES").tag(...)`，分段选择器）
>    → **译**为「是 / 否」。这是纯展示层。
> 2. **数据值**（`:157`、`:844`、`:937`、`:1013` 的 `boolVal ? "YES" : "NO"`、
>    `value == "YES"` 等）→ **不译，也不需要译**：它们是普通 Swift `String` 字面量，
>    既不走 `NSLocalizedString`，也不是 `LocalizedStringKey`，本地化压根不会碰到它们。
>
> 两者互不影响的原因：`.tag(true)` / `.tag("YES")` 携带的是数据，与 `Text` 的展示值
> 分离；本地化只替换 `Text` 的展示值。写回 plist 的路径全程不经过本地化，
> 因此翻译**不会污染写入 plist 的真值**，plist 里仍然写 `YES` / `NO`。

## 4. 导航与功能区块

| English | 简体中文 |
| --- | --- |
| My Apps | 我的应用 |
| Browse | 浏览 |
| Settings | 设置 |
| News | 动态 |
| About | 关于 |
| Sources | 软件源 |
| Backup & Restore | 备份与恢复 |
| Backup | 备份 |
| Restore Backup | 恢复备份 |
| Developer Options | 开发者选项 |
| Experimental Features | 实验性功能 |
| Diagnostics & Tools | 诊断与工具 |
| Advanced Settings | 高级设置 |
| Change App Icon | 更改 App 图标 |
| Theme Manager | 主题管理 |
| Storage Explorer | 存储浏览器 |
| Health Check | 健康检查 |
| Developer Portal | 开发者网站 |
| Network Discovery | 网络发现 |
| Enable JIT | 启用 JIT |

---

## 5. Key 与占位符规则（硬性）

### 5.1 key 必须逐字照抄源码字面量（最重要）

**`.strings` 里的 key 就是源码里那个字符串字面量本身，一个字符都不能改。**
key 是查表的索引——改了 key 就查不到，`NSLocalizedString` / `LocalizedStringKey`
会**静默退回英文**，UI 不会报错，只是悄悄没翻译。

* ✅ 源码 `NSLocalizedString("Cancel", ...)` → `"Cancel" = "取消";`
* ❌ 想当然地"优化"成 `"cancel" = "取消";` → 查不到，UI 显示 `Cancel`
* ❌ 想当然地"顺手修个拼写/大小写" → 同上

这条同样适用于占位符：

* ✅ 源码 `NSLocalizedString("Download %@ %@", ...)` → `"Download %@ %@" = "下载 %1$@ %2$@";`
  —— **key 保持 `%@`，只有 value 改成位置占位符**，这是完全正确的做法。
* ❌ 把 key 也改成 `Download %1$@ %2$@` → 查不到，退回英文。

### 5.2 什么时候 key 和 value 才"两边都用位置占位符"

只有一种情况：key 本身就是位置占位符——**而且是源码里就写成了位置占位符**，
不是我们改的。全项目目前只有一个例子：

* `Shared/Extensions/Bundle+AltStore.swift` 中
  `NSLocalizedString("Version %1$@%2$@", comment: "SideStore Version")`
  → `"Version %1$@%2$@" = "版本 %1$@%2$@";`

这个 key 的 `%1$@%2$@` 是在**改源码时写进去的**（为了能抽成静态 key），
所以它天然两边一致。除此之外，**不要为了对齐而改源码里的 key**——
改源码意味着要重新抽取、重新校验，且改错就是静默失翻。

### 5.3 其余硬性规则

1. value 的占位符**数量与类型必须与 key 一致**：`%@`、`%d`、`%ld`、`%lld`、`%f`、
   `%.2f` 一一对应。需要中文语序时用 `%1$@`、`%2$@`、`%3$@`。
2. 同一个字符串内**禁止**混用位置占位符与非位置占位符。
3. 转义：`"` → `\"`，`\` → `\\`，换行 → `\n`。
4. 文件编码一律 **UTF-8 无 BOM**（`scripts/i18n/translations_zh_Hans.tsv` 同样如此）。
5. 译表里如果 value 与 key 相同（有意保留英文），**必须**同时把 key 加进
   `scripts/i18n/keep_english.txt`，否则校验器会判为"漏译"。

### 5.4 片段拼接消息（spacing 陷阱）

有若干错误消息在 Swift 侧是**先分别本地化片段、再拼进另一条已本地化的模板**的，
例如 `SourceError.swift` 的：

* 模板 `The source “%@” contains multiple apps with %@.`
  会被塞入两种片段：`the bundle identifier %@`（拉丁开头）或
  `the same bundle identifier`（纯中文）
* 模板 `The source “%@” contains %@ for %@.`
  会塞入 `duplicate versions`（中文）与"应用名（拉丁）/ `one or more apps`（中文）"

**同一个模板没法在两种片段下都完美处理中英文之间的空格。** 处理约定：

* 优先用**全角括号**把片段包起来，让间距由标点承担、
  与片段自身语言无关：`…包含多个应用（%2$@）。`
  → `（Bundle ID 为 com.example.app）` / `（相同的 Bundle ID）` 都干净。
* 无法用括号时，空格放在**片段通常是拉丁文**的那一侧，
  中文侧不空格：`…中 %3$@ 存在%2$@。`
* **不要**靠给片段加前导/尾随空格来调间距——那会在模板和片段之间产生隐式耦合，
  后来者随手删掉那个空格就又坏了。

改这类条目时请用 `validate_strings.py` 里的 `ns_format()` 把每种分支都实跑一遍再定稿。

校验方式：

```bash
python scripts/i18n/extract_strings.py extract   # 重新抽取（写入 extracted.json）
python scripts/i18n/extract_strings.py render    # 渲染 Localizable.strings
python scripts/i18n/validate_strings.py          # 五道质量关卡，输出 IS_PASS
```

---

## 6. 待办（本期未覆盖）

* **xib 文本（6 条，本期不生效）**：UIKit nib 的文本走 `<NibName>.strings`
  （每张 nib 一张表），不是 `Localizable.strings`。`Localizable.strings` 末尾那 6 条
  （`Become a patron!`、`Follow us on Twitter!`、`Follow us on Instagram!`、
  `Refresh All`、`SIGN OUT`、`Version Notes`）**只是翻译资产，当前不会显示**，
  其中 4 条在 Swift 源码里完全搜不到、只存在于 xib。
  要生效需要：开启 Base Internationalization → 导出各 xib 的 strings →
  **重新建立 key 映射**（ibtool 生成的 key 是 ObjectID，不是这里的文本 key）。
* **带插值的 `Text("...\(...)")`**：共 160 处，需改造为
  `Text("Key") + Text(value)` 或 `String(localized:)` 之后才能翻译。
* **动态 key**：`AltStore/Extensions/String+Localization.swift` 的
  `String(formatted:comment:)` 与 `systemLocalizedString()` 把变量直接当 key 传给
  `NSLocalizedString`，本质不可抽取，本期**未改动该文件**。
  另有 3 处 `NSLocalizedString` 传动态 key（见 `extracted.json` 的
  `report.skipped_dynamic`）。
* **复数/数量变化**：需要 `Localizable.stringsdict`（如 “%d apps” 的单复数）。
* `AltWidget` / `SideBackup` 两个 target 的界面文案。

---

## 7. 维护流程

1. 改 `scripts/i18n/translations_zh_Hans.tsv`（`key <TAB> 译文`，UTF-8）。
2. 若该条目有意保留英文，同时把 key 加进 `scripts/i18n/keep_english.txt`。
3. 跑 `extract` → `render` → `validate_strings.py`，确认 `IS_PASS: YES`。
4. 新术语同步写回本文件第 1、2 节。
