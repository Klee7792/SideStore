"""Apply the zh-Hans translations for the 141 keys added by the LocalizedStringKey pass.

Reads scripts/i18n/translations_zh_Hans.tsv, replaces the verbatim rows inside the
"Pending translation" block with real translations, drops the translated keys from
scripts/i18n/keep_english.txt (keeping the deliberately-English ones), and rewrites
both files in place.  Idempotent: running it twice is a no-op.
"""

from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TSV = SCRIPT_DIR / "translations_zh_Hans.tsv"
KEEP_ENGLISH = SCRIPT_DIR / "keep_english.txt"

# key -> zh-Hans value.  Only keys that are currently verbatim in the pending block
# are touched; keys absent from this map stay in keep_english.txt.
TRANSLATIONS: dict[str, str] = {
    # ---- InfoPlistCustomizationCoreView.swift (section headers) ----
    "APP IDENTITY": "应用身份",
    "VERSIONING": "版本",
    "CAPABILITIES & SHARING": "能力与共享",
    "ALL RAW KEYS": "全部原始键",

    # ---- AnisetteDataView.swift ----
    "PRIMARY CLIENT HEADERS": "主要客户端请求头",
    "Client Info": "客户端信息",
    "User Agent": "用户代理",
    "DEVICE & IDENTITY": "设备与身份",
    "Device Identifier": "设备标识符",
    "Local User ID": "本地用户 ID",
    "Serial Number": "序列号",
    "Routing Info": "路由信息",
    "ENVIRONMENT & LOCALIZATION": "环境与语言",
    "Locale": "语言区域",
    "Time Zone": "时区",
    "Xcode Version": "Xcode 版本",
    "DYNAMIC CRYPTOGRAPHIC TOKENS": "动态加密令牌",
    "One-Time Password (OTP)": "一次性密码（OTP）",
    "Signed HMAC token dynamically calculated by ADI engine per request":
        "由 ADI 引擎按请求动态计算的 HMAC 签名令牌",
    "Machine ID": "机器 ID",
    "Hardware identifier computed from adi.pb and device identity":
        "根据 adi.pb 和设备身份计算出的硬件标识符",
    "Client Time": "客户端时间",
    "ISO8601 UTC timestamp locked to OTP generation time":
        "与 OTP 生成时间绑定的 ISO8601 UTC 时间戳",
    "RAW CONFIGURATION JSON": "原始配置 JSON",
    "REMOTE SERVER SYNC": "远程服务器同步",
    "ACTIONS": "操作",

    # ---- CertificateDetailView.swift ----
    "Certificate ID": "证书 ID",
    "Type Name": "类型名称",
    "Managed": "托管",
    "Platform": "平台",
    "Platform Name": "平台名称",
    "Created By": "创建者",
    "Requester Email": "请求者邮箱",
    "Owner Name": "所有者名称",
    "Owner ID": "所有者 ID",
    "Auto-Rotation": "自动轮换",
    "Subject": "主题",
    "Issuer": "颁发者",
    "Serial Number (hex)": "序列号（十六进制）",
    "Serial Number (dec)": "序列号（十进制）",
    "Valid From": "生效日期",
    "Valid Until": "失效日期",
    "Validity Days": "有效天数",
    "Public Key": "公钥",
    "Signature Algorithm": "签名算法",
    "Has Private Key": "包含私钥",

    # ---- SideSignConfigurationView.swift ----
    "Service": "服务",
    "Header Version": "Header 版本",
    "Auth App": "认证应用",
    "DEVELOPER SERVICES": "开发者服务",
    "Client ID": "客户端 ID",
    "Protocol Version": "协议版本",
    "Services Version": "服务版本",

    # ---- UserCustomizationsView.swift ----
    "Disable All Verifications": "停用全部校验",
    "Bundle Identifier Check": "Bundle Identifier 校验",
    "iOS Version Check": "iOS 版本校验",
    "App Version Check": "应用版本校验",
    "Checksum (SHA-256) Check": "校验和（SHA-256）校验",
    "App File Size Check": "应用文件大小校验",
    "Permission Checks": "权限检查",
    "EMProxy (WireGuard) Server": "EMProxy (WireGuard) 服务器",
    "Restart required to apply changes": "需要重启才能应用更改",
    "Enable Background Keepalive": "启用后台保活",
    "Cellular Refresh": "蜂窝数据刷新",
    "Automatically toggle cellular data via Shortcuts during refresh":
        "刷新期间通过“快捷指令”自动开关蜂窝数据",
    "Turn On Cellular Shortcut": "打开蜂窝数据的快捷指令",
    "Name of the shortcut in Apple Shortcuts app": "“快捷指令”App 中的快捷指令名称",
    "Turn Off Cellular Shortcut": "关闭蜂窝数据的快捷指令",
    "Turn On Base Delay": "打开数据后的基础延迟",
    "Base wait time after turning on data (seconds, ≥ 0)": "打开数据后的基础等待时间（秒，≥ 0）",
    "Turn Off Base Delay": "关闭数据后的基础延迟",
    "Base wait time after turning off data (seconds, ≥ 0)": "关闭数据后的基础等待时间（秒，≥ 0）",
    "Customize AppID": "自定义 AppID",
    "Confirm App Installation": "安装前确认",
    "Prompt for confirmation before installing or importing an app": "安装或导入应用前弹出确认提示",
    "Clear Customizations on Uninstall": "卸载时清除自定义设置",
    "Reset assigned profiles, custom certificates, and metadata when an app is deleted":
        "删除应用时重置已分配的描述文件、自定义证书和元数据",
    "Auto-Launch App After Install": "安装后自动打开应用",
    "Automatically open apps after installation completes": "安装完成后自动打开应用",
    "Auto-Fix AppGroup IDs": "自动修正 AppGroup ID",
    "Customize Provisioning Profile": "自定义描述文件",
    "Prompt to select a provisioning profile before installing": "安装前提示选择描述文件",
    "Prefer Resigned IPA": "优先使用已重新签名的 IPA",
    "Prompt to choose a custom icon before installing": "安装前提示选择自定义图标",
    "Prefer IPA (speed) vs App (storage) efficiency": "优先 IPA（速度）还是 App（存储）效率",
    "Export Resigned IPAs": "导出已重新签名的 IPA",
    "Skip Uncopyable Backup Files": "跳过无法拷贝的备份文件",
    "Prefer Sheet for Info.plist": "Info.plist 使用 sheet 展示",
    "Use sheet instead of dialog": "使用 sheet 而非对话框",
    "Prefer Sheet for Entitlements": "权限使用 sheet 展示",
    "On-Device Anisette": "设备端 Anisette",
    "Run ADI emulation directly on device instead of remote servers":
        "在设备上直接运行 ADI 模拟，而非使用远程服务器",

    # ---- DeveloperOptionsView.swift ----
    "Disable URL Response Caching": "停用 URL 响应缓存",
    "Rotate Logs on Startup": "启动时轮换日志",
    "SideStore Verbose Logging": "SideStore 详细日志",
    "Widget Verbose Logging": "Widget 详细日志",
    "Top Shelf Verbose Logging": "Top Shelf 详细日志",
    "SideSign Verbose Logging": "SideSign 详细日志",
    "Minimuxer Verbose Logging": "Minimuxer 详细日志",
    "Operations Verbose Logging": "操作详细日志",
    "Wipe Database on Next Start": "下次启动时清空数据库",
    "Show WireGuard Settings": "显示 WireGuard 设置",
    "Accept IPv6 Config": "接受 IPv6 配置",
    "Auto Retry RemotePairing Port": "自动重试 RemotePairing 端口",

    # ---- ExperimentalFeaturesView.swift ----
    "Enable Minimuxer Backend Hotswap": "启用 Minimuxer 后端热切换",

    # ---- OperationsLoggingControlView.swift ----
    "Backup App Data": "备份应用数据",
    "Cache App": "缓存应用",
    "Clean Staged App": "清理暂存应用",
    "Deactivate App": "停用应用",
    "Download App": "下载应用",
    "Export Resigned IPA": "导出已重新签名的 IPA",
    "Fetch Provisioning Profiles": "获取描述文件",
    "Preflight Checks": "预检",
    "Prepare App Extension Bundle IDs": "准备应用扩展 Bundle ID",
    "Refresh App": "刷新应用",
    "Remove App": "移除应用",
    "Remove Backup Data": "移除备份数据",
    "Resign App": "重新签名应用",
    "Restore App Data": "恢复应用数据",
    "Send App": "发送应用",
    "Stage App": "暂存应用",
    "Stage Backup App": "暂存备份应用",
    "Update App Certificate": "更新应用证书",
    "User Customization": "用户自定义",
    "Verify App": "校验应用",
    "Verify Certificate": "校验证书",
    "Create IPA": "创建 IPA",
    "Background Refresh Apps": "后台刷新应用",
    "Clear App Cache": "清除应用缓存",
    "Sync App IDs": "同步 App ID",
    "Fetch Source": "获取软件源",
    "Schedule Expiration Warning": "安排到期提醒",

    # ---- DeveloperOptionsView.swift, second pass (#if branches) ----
    "WIDGET OPTIONS": "Widget 选项",
    "TOP SHELF OPTIONS": "Top Shelf 选项",
    "Reload All Widgets": "重新载入全部 Widget",
    "Reload Top Shelf": "重新载入 Top Shelf",
    "Rotate Widget Log": "轮换 Widget 日志",
    "Rotate Top Shelf Log": "轮换 Top Shelf 日志",
}

# Keys that stay verbatim on purpose (all-caps protocol names / Apple header names).
STAY_ENGLISH = {
    "APPLE AUTH (IDMSA)",
    "GRANDSLAM AUTH (GSA)",
    "App ID Key",
}


def main() -> None:
    tsv_lines = TSV.read_text(encoding="utf-8-sig").splitlines()

    # Locate the pending block in the TSV.
    pending_start = None
    for index, line in enumerate(tsv_lines):
        if "Pending translation" in line:
            pending_start = index
    if pending_start is None:
        raise SystemExit("pending block header not found in TSV")

    body = tsv_lines[: pending_start + 1]
    pending = tsv_lines[pending_start + 1 :]

    rewritten: list[str] = []
    applied = 0
    for line in pending:
        if not line.strip() or line.startswith("#"):
            rewritten.append(line)
            continue
        key, _, value = line.partition("\t")
        if key == value and key in TRANSLATIONS:
            rewritten.append(f"{key}\t{TRANSLATIONS[key]}")
            applied += 1
        else:
            rewritten.append(line)

    if applied != len(TRANSLATIONS):
        missing = sorted(set(TRANSLATIONS) - {l.partition("\t")[0] for l in pending})
        raise SystemExit(f"only applied {applied}/{len(TRANSLATIONS)}; unmatched: {missing}")

    TSV.write_text("\n".join(body + rewritten) + "\n", encoding="utf-8")

    # Rewrite keep_english.txt: drop every key we just translated, keep the rest.
    keep_lines = KEEP_ENGLISH.read_text(encoding="utf-8-sig").splitlines()
    out: list[str] = []
    for line in keep_lines:
        candidate = line.lstrip()
        if candidate and not candidate.startswith("#") and candidate in TRANSLATIONS:
            continue
        out.append(line)
    KEEP_ENGLISH.write_text("\n".join(out) + "\n", encoding="utf-8")

    print(f"applied {applied} translations")
    print(f"keep_english.txt: {len(keep_lines)} -> {len(out)} lines")


if __name__ == "__main__":
    main()
