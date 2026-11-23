# -*- coding: utf-8 -*-
"""StorCLI GUI - Broadcom MegaRAID StorCLI 图形化管理前端

依赖: Python 3.8+ (含 tkinter), 同目录下的 storcli64.exe / storcli.exe
说明: StorCLI 的大部分操作需要管理员权限; 若以普通权限运行,
      界面右上角可一键"以管理员身份重启"。
"""

import ctypes
import csv
import json
import os
import queue
import re
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_TITLE = "StorCLI GUI"
APP_VERSION = "1.5.4"
MONO_FONT = ("Consolas", 10)
UI_FONT = ("Microsoft YaHei UI", 9)
DANGER_COLOR = "#c62828"
WINDOW_BG = "#f0f0f0"
CONTENT_BG = "#ffffff"
TEXT_FG = "#202124"
SELECT_BG = "#cce8ff"
SELECT_FG = "#111111"
HOVER_BG = "#dbeafe"
CREATE_NO_WINDOW = 0x08000000
DEFAULT_TIMEOUT = 180

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------- 基础工具

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def decode_bytes(data):
    if not data:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", "replace")


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def find_storcli():
    here = base_dir()
    for folder in (here, os.getcwd()):
        for name in ("storcli64.exe", "storcli.exe"):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                return path
    return ""


def fmt_cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def parse_json_output(text):
    i = text.find("{")
    if i < 0:
        raise ValueError("输出中未找到 JSON")
    return json.loads(text[i:])


def command_status(payload):
    try:
        status = payload["Controllers"][0]["Command Status"]
        return status.get("Status", ""), status.get("Description", "")
    except Exception:
        return "", ""


def extract_text_status(out):
    m = re.search(r"^\s*Status\s*=\s*(\w+)", out or "", re.M)
    return m.group(1) if m else ""


def iter_tables(node, path=""):
    """递归遍历 storcli JSON, 找出所有 "对象数组" 形式的表格."""
    if isinstance(node, dict):
        for key, value in node.items():
            sub = f"{path} > {key}" if path else str(key)
            yield from iter_tables(value, sub)
    elif isinstance(node, list) and node and all(isinstance(x, dict) for x in node):
        headers = []
        for row in node:
            for key in row:
                if key not in headers:
                    headers.append(key)
        yield path, headers, node


STATE_COLORS = {
    "green": ("opt", "onln", "online", "good", "jbod", "normal", "success", "active", "ready", "ok"),
    "red": ("offln", "offline", "failed", "missing", "critical", "dgd", "failure", "bad",
            "ubad", "needs attention", "safe-mode", "certificate provision"),
    "orange": ("rbld", "rebuild", "init", "copy", "busy", "transition", "initializing", "puncturing"),
}


def parse_fw_build_time(text):
    m = re.search(r"[Ff]irmware version\s+[\d.\-]+\s+built on\s+([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4})\s+at\s+(\d{2}:\d{2}:\d{2})", text)
    if m:
        return f"{m.group(1)}  {m.group(2)}"
    m = re.search(r"Build date/time:\s*([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\s+\d{2}:\d{2}:\d{2})", text)
    if m:
        return m.group(1)
    m = re.search(r"FW Build Time\s*[:=]\s*([^\r\n]+)", text)
    if m:
        return m.group(1).strip()
    head = "\n".join(text.splitlines()[:200])
    m = re.search(r"([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\s+\d{2}:\d{2}:\d{2})", head)
    if m:
        return m.group(1)
    return ""


def tag_for_state(text):
    low = text.lower()
    for tag, words in STATE_COLORS.items():
        for word in words:
            if word in low:
                return tag
    return ""


# ---------------------------------------------------------------- 中文翻译

STATUS_CN = {"Success": "成功", "Failure": "失败", "Warning": "警告"}

HEADER_CN = {
    "EID:Slt": "背板:槽位", "EID": "背板号", "Slt": "槽位", "DID": "设备ID",
    "State": "状态", "DG": "磁盘组", "Size": "容量", "Intf": "接口", "Med": "介质",
    "SED": "自加密", "PI": "PI", "SeSz": "扇区大小", "Model": "型号", "Sp": "转速类",
    "Type": "类型", "VC": "VD号", "Name": "名称", "Access": "访问", "Consist": "一致性",
    "Slots": "槽位数",
    "PD": "物理盘数", "PS": "电源", "Fans": "风扇", "TSs": "温度传感器", "Alms": "告警",
    "SIM": "SIM", "Port#": "端口", "ProdID": "产品ID", "Status": "状态",
    "VendorSpecific": "厂商自定义", "Port": "端口", "Linkspeed": "链路速度",
    "SAS address": "SAS 地址",
    "DG/VD": "磁盘组/VD号", "TYPE": "RAID 类型", "Access": "访问", "Consist": "一致性",
    "Cache": "缓存策略", "Cac": "缓存", "sCC": "后台CC",
}

STATE_CN = {
    "UGood": "未配置(好)", "UBad": "未配置(坏)", "Onln": "在线", "Offln": "离线",
    "GHS": "全局热备", "DHS": "专用热备", "JBOD": "直通", "Opt": "最优",
    "Dgd": "降级", "Dgrd": "降级", "Pdgd": "部分降级", "Rbld": "重建中", "Init": "初始化中",
    "Failed": "失败", "Missing": "丢失", "OK": "正常", "Recfg": "重配置中",
    "Cpybck": "回拷中", "CpyBck": "回拷中", "Sntze": "擦除中", "Up": "正常",
    "Optl": "最优", "RW": "读写", "RO": "只读", "RWTD": "回写直读",
    "Optimal": "良好", "Yes": "是", "No": "否", "NA": "不适用", "N/A": "不适用",
    "Not supported": "不支持", "Active": "活动", "Unavailable": "不可用",
    "Backplane": "背板", "None": "无", "No PI": "无 PI",
    "WriteThrough": "直写", "WriteBack": "回写", "Disk's Default": "盘默认",
    "Disabled": "已禁用", "Enabled": "已启用", "default": "默认",
    "ON": "开", "OFF": "关",
    "Disable": "禁用", "Supported": "支持", "Not Supported": "不支持",
    "Available": "可用", "Not Available": "不可用",
    "Present": "存在", "Absent": "不存在",
    "Allowed": "允许", "Not Allowed": "不允许",
    "Adaptive": "自适应", "Automatic": "自动", "Maximum": "最大",
    "Maximum with caching": "最大（启用缓存）",
    "Maximum without caching": "最大（禁用缓存）",
    "Controller Defined": "控制器定义", "Continuous": "持续", "Unknown": "未知",
    "Block": "阻止", "Allow": "允许", "Warn & Allow": "警告并允许",
    "Server Storage Cluster": "服务器存储集群",
    "Internal Only": "仅内部", "external only": "仅外部", "all": "全部",
    "Silent": "静音", "No Read Ahead": "不预读",
    "WT": "直写 (WT)", "WB": "回写 (WB)", "RA": "预读 (RA)",
    "Safe-Mode": "安全模式", "Needs Attention": "需要关注",
    "Certificate provision Mode": "证书配置模式",
    "Undefined": "未定义", "RAID-Mode": "RAID 模式", "HBA-Mode": "HBA 模式",
    "JBOD-Mode": "JBOD 模式", "SDS-Mode": "SDS 模式", "eHBA-MODE": "eHBA 模式",
    "HSP": "热备盘", "UGUnsp": "未配置(未指定)", "UGShld": "未配置(Shield)",
    "HSPShld": "热备(Shield)", "CFShld": "配置(Shield)", "CBShld": "回拷(Shield)",
    "UBUnsp": "未配置(坏/未指定)",
    "Inactive": "未激活", "Configured": "已配置", "Not Configured": "未配置",
    "Unsupported": "不支持", "Not Applicable": "不适用",
    "Degraded": "降级", "Attention": "需要关注", "Warning": "警告",
    "Successful": "成功", "Completed": "已完成", "In Progress": "进行中",
    "Unsecured": "未加密", "Unlocked": "未锁定",
}

STATE_CN_CASEFOLD = {str(key).casefold(): value for key, value in STATE_CN.items()}
STATE_CN_NORMALIZED = {
    re.sub(r"[\s_\-]+", " ", str(key).strip()).casefold(): value
    for key, value in STATE_CN.items()
}

DESC_CN = {
    "No VD's have been configured.": "尚未配置任何虚拟驱动器。",
    "No drive found!": "未找到物理盘。",
    "No Controller found": "未找到控制器(需要管理员权限)。",
    "Battery is absent!": "无电池/CacheVault 模块(该卡可能本就不带缓存)。",
    "Couldn't find any foreign Configuration": "未发现外来(Foreign)配置。",
    "Show Drive Information Succeeded.": "物理盘信息读取成功。",
    "Show Drive Smart Info Succeeded.": "SMART 信息读取成功。",
    "Show Drive/Cable Error Counters Failed.": "错误计数读取失败(部分卡型不支持)。",
    "None": "",
}

TITLE_CN = {
    "Enclosure LIST": "背板列表", "Drive Information": "物理盘信息",
    "Virtual Drives": "虚拟驱动器", "Drive Groups": "磁盘组",
    "Properties": "属性", "System Overview": "系统概览", "PD LIST": "物理盘列表",
}


def tr_status(s):
    return STATUS_CN.get(s, s)


def tr_header(h):
    return HEADER_CN.get(h, h)


def tr_state(v):
    s = str(v).strip()
    if s in STATE_CN:
        return STATE_CN[s]
    folded = STATE_CN_CASEFOLD.get(s.casefold())
    if folded:
        return folded
    normalized = re.sub(r"[\s_\-]+", " ", s).casefold()
    mapped = STATE_CN_NORMALIZED.get(normalized)
    if mapped:
        return mapped
    if s.endswith(" hrs"):
        return s[:-4].strip() + " 小时"
    m = re.match(r"^(\d+)C\s+\(([\d.]+)\s*F\)$", s)
    if m:
        return f"{m.group(1)}°C ({m.group(2)}°F)"
    if " Sectors]" in s:
        s = s.replace(" Sectors]", " 扇区]")
    if s.startswith("Port "):
        s = "端口 " + s[5:]
    if "(path" in s:
        s = s.replace("(path", "(路径")
    if s.startswith("Disk "):
        s = "磁盘 " + s[5:]
    m = re.match(r"^([\d:]+)\s*(AM|PM)$", s)
    if m:
        s = ("上午 " if m.group(2) == "AM" else "下午 ") + m.group(1)
    return s


def tr_desc(d):
    d = (d or "").strip()
    if d in DESC_CN:
        return DESC_CN[d]
    for k, v in DESC_CN.items():
        if k and k in d:
            return d.replace(k, v)
    return d


def clean_section_name(p):
    p = str(p).strip()
    p = re.sub(r"^Drive\s+\S+\s+-\s+", "", p)
    p = re.sub(r"^Drive\s+\S+\s+", "", p)
    if re.match(r"^Drive\s+\S+$", p):
        return "物理盘基本信息"
    p = re.sub(r"^Enclosure\s+\S+", "背板", p)
    p = re.sub(r"^PDs for VD\s*\d*", "成员物理盘", p)
    p = re.sub(r"^VD\d+\s*Properties", "虚拟盘属性", p)
    if re.match(r"^/c\d+/v\d+$", p):
        return "虚拟盘基本信息"
    return p


def tr_title(t):
    out = []
    for p in str(t).split(" > "):
        c = clean_section_name(p)
        out.append(SECTION_CN.get(c, TITLE_CN.get(c, c)))
    return " > ".join(out)


SECTION_CN = {
    "Basics": "基本信息", "Version": "版本信息", "Bus": "总线 / 接口",
    "Status": "运行状态", "Scheduled Tasks": "计划任务",
    "State": "运行状态", "Device attributes": "设备属性",
    "Policies/Settings": "策略 / 设置", "Detailed Information": "详细信息",
    "Port Information": "端口信息", "Information": "基本信息", "Inquiry Data": "查询数据",
    "PD LIST": "物理盘列表", "Enclosure LIST": "背板列表",
    "DG LIST": "磁盘组列表", "VD LIST": "虚拟盘列表",
    "Advanced Software Option": "高级软件选项",
    "Supported Drives": "支持的物理盘", "Supported Protocols": "支持的协议",
}

CONTROLLER_SECTION_CN = {
    "Basics": "基本信息",
    "Version": "固件与软件版本",
    "Bus": "总线与接口",
    "Pending Images in Flash": "Flash 中待生效映像",
    "Status": "运行状态",
    "Supported Adapter Operations": "支持的适配器操作",
    "Enterprise Key management": "企业密钥管理 (EKM)",
    "Supported PD Operations": "支持的 PD 操作",
    "Supported VD Operations": "支持的 VD 操作",
    "Advanced Software Option": "高级软件选项",
    "Safe ID": "Safe ID",
    "HwCfg": "硬件配置",
    "Policies": "策略设置",
    "Boot": "启动设置",
    "High Availability": "高可用性",
    "Defaults": "默认设置",
    "Capabilities": "控制器能力",
    "Scheduled Tasks": "计划任务",
    "Secure Boot": "安全启动",
    "Security Protocol properties": "安全协议属性",
    "FOREIGN CONFIGURATION": "外来配置",
    "TOPOLOGY": "磁盘组拓扑",
    "Drive Groups": "磁盘组",
    "Virtual Drives": "虚拟盘",
    "VD LIST": "虚拟盘列表",
    "JBOD LIST": "JBOD 列表",
    "Physical Drives": "物理盘",
    "PD LIST": "物理盘列表",
    "Enclosures": "背板",
    "Enclosure LIST": "背板列表",
    "Cachevault_Info": "CacheVault 信息",
    "Details": "映像明细",
    "BBU Capacity Info": "BBU 容量信息",
    "BBU Design Info": "BBU 设计信息",
    "BBU Firmware Status": "BBU 固件状态",
    "BBU Info": "BBU 信息",
    "BBU Properties": "BBU 属性",
    "BBU Set Property": "BBU 设置属性",
    "Cachevault Learn": "CacheVault 学习信息",
    "Cachevault Properties": "CacheVault 属性",
    "Cachevault Set Property": "CacheVault 设置属性",
    "Connector Mode Info": "连接器模式信息",
    "Controller Properties": "控制器属性",
    "Current OOB Info": "当前 OOB 信息",
    "Default OOB Info": "默认 OOB 信息",
    "Failed NVMe Devices": "失败的 NVMe 设备",
    "FOREIGN PREVIEW": "外来配置预览",
    "FREE SPACE DETAILS": "可用空间明细",
    "Foreign PD List": "外来 PD 列表",
    "Foreign VD List": "外来 VD 列表",
    "Foreign Topology": "外来配置拓扑",
    "HtbProperties": "Hot Spare 属性",
    "Link Configuration": "链路配置",
    "Mux Info": "Mux 信息",
    "PCIe Event Counters": "PCIe 事件计数",
    "Phy Error Counters": "PHY 错误计数",
    "Phy Info": "PHY 信息",
    "Re-host Information": "重新托管信息",
    "SAS Event Counters": "SAS 事件计数",
    "Slot Status Details": "槽位状态明细",
    "SnapDump Details": "SnapDump 明细",
    "SnapDump Properties": "SnapDump 属性",
    "Test Link State": "链路状态测试",
    "UN-CONFIGURED DRIVE LIST": "未配置磁盘列表",
}

PROP_CN = {
    "Controller": "控制器号", "Model": "型号", "Serial Number": "序列号",
    "Current Controller Date/Time": "控制器时间", "Current System Date/time": "系统时间",
    "SAS Address": "SAS 地址", "PCI Address": "PCI 地址", "Mfg Date": "制造日期",
    "Rework Date": "返工日期", "Revision No": "修订号",
    "Firmware Package Build": "固件包版本", "Firmware Version": "固件版本",
    "Firmware Build Time": "固件构建时间",
    "Bios Version": "BIOS 版本", "HII Version": "HII 版本", "HIIA Version": "HIIA 版本",
    "Ctrl-R Version": "Ctrl-R 版本", "CBB Version": "CBB 版本",
    "PSOC FW Version": "PSOC 固件版本", "PSOC Hardware Version": "PSOC 硬件版本",
    "PSOC Part Number": "PSOC 部件号",
    "Preboot CLI Version": "Preboot CLI 版本", "NVDATA Version": "NVDATA 版本",
    "Boot Block Version": "Boot Block 版本", "Driver Name": "驱动名称",
    "Driver Version": "驱动版本",
    "Vendor Id": "厂商 ID", "Device Id": "设备 ID", "SubVendor Id": "子厂商 ID",
    "SubDevice Id": "子设备 ID", "Host Interface": "主机接口", "Device Interface": "设备接口",
    "Bus Number": "总线号", "Device Number": "设备号", "Function Number": "功能号",
    "Domain ID": "域 ID",
    "Controller Status": "控制器状态", "Memory Correctable Errors": "内存可纠正错误",
    "Memory Uncorrectable Errors": "内存不可纠正错误", "ECC Bucket Count": "ECC 计数",
    "BBU Status": "BBU 状态", "Any Offline VD Cache Preserved": "离线 VD 缓存保留",
    "Consistency Check Reoccurrence": "一致性检查周期", "Next Consistency check launch": "下次一致性检查",
    "Patrol Read Reoccurrence": "巡检周期", "Next Patrol Read launch": "下次巡检",
    "Battery learn Reoccurrence": "电池学习周期", "Next Battery Learn": "下次电池学习",
    "OEMID": "OEM",
    "Shield Counter": "屏蔽计数", "Media Error Count": "介质错误计数",
    "Other Error Count": "其他错误计数", "Drive Temperature": "盘温度",
    "Predictive Failure Count": "预测性故障计数", "S.M.A.R.T alert flagged by drive": "S.M.A.R.T 告警",
    "Drive Position": "驱动器位置", "Inquiry Data": "询问数据", "Enclosure position": "背板位置",
    "Connector Name": "连接器名称",
    "Sanitize Support": "Sanitize 支持",
    "SN": "序列号", "Manufacturer Id": "制造商", "Model Number": "型号",
    "NAND Vendor": "NAND 厂商", "FRU/CRU": "FRU/CRU", "WWN": "WWN",
    "Firmware Revision": "固件版本", "Firmware Release Number": "固件发布号",
    "Raw size": "原始容量", "Coerced size": "强制容量", "Non Coerced size": "非强制容量",
    "Device Speed": "设备速度",
    "Connected Port Number": "连接端口",
    "Sequence Number": "内部序号", "Commissioned Spare": "委任热备", "Emergency Spare": "紧急热备",
    "Last Predictive Failure Event Sequence Number": "上次预测故障事件序号",
    "FDE Type": "FDE 类型", "SED Capable": "SED 能力", "SED Enabled": "SED 启用",
    "Secured": "已加密", "Cryptographic Erase Capable": "加密擦除能力",
    "PD Firmware Download in progress": "PD 固件下载进行中",
    "Support PD Firmware Download": "支持 PD 固件下载",
    "Lock Key Assigned": "已分配锁密钥", "Failed to get lock key on bootup": "启动时获取锁密钥失败",
    "Lock key has not been backed up": "锁密钥未备份",
    "Bios was not detected during boot": "启动时未检测到 BIOS",
    "Controller must be rebooted to complete security operation": "需重启控制器以完成安全操作",
    "A rollback operation is in progress": "回滚操作进行中",
    "At least one PFK exists in NVRAM": "NVRAM 中存在 PFK", "SSC Policy is WB": "SSC 策略为 WB",
    "Controller has booted into safe mode": "控制器进入安全模式",
    "Controller shutdown required": "需要关闭控制器",
    "Controller has booted into certificate provision mode": "控制器进入证书供应模式",
    "Physical Drives": "物理盘数量", "Enclosures": "背板数量",
    "Link Speed": "链路速度", "Write Cache": "写缓存",
    "Logical Sector Size": "逻辑扇区大小", "Physical Sector Size": "物理扇区大小",
    "Connector Name": "连接器名称",
    "Successful diagnostics completion on": "诊断完成时间",
    "Sanitize Support": "Sanitize 支持", "Locked": "已锁定",
    "Needs EKM Attention": "需 EKM 关注", "PI Eligible": "PI 资格",
    "Drive is formatted for PI": "盘已按 PI 格式化", "PI type": "PI 类型",
    "Number of bytes of user data in LBA": "LBA 用户数据字节数",
    "Certified": "已认证", "Wide Port Capable": "宽端口能力", "Multipath": "多路径",
    "Device ID": "设备 ID", "Position": "位置", "Enclosure Type": "背板类型",
    "FRU Part Number": "FRU 部件号", "Enclosure Serial Number": "背板序列号",
    "Enclosure Zoning Mode": "分区模式", "Partner Device ID": "伙伴设备 ID",
    "Device Type": "设备类型", "EnclLogicalID": "逻辑 ID",
    "Vendor Identification": "厂商标识", "Product Identification": "产品标识",
    "Product Revision Level": "产品修订版本", "Status": "状态",
    "Strip Size": "条带大小", "Number of Blocks": "块数量",
    "VD has Emulated PD": "使用模拟 PD", "Span Depth": "Span 深度",
    "Number of Drives Per Span": "每 Span 盘数",
    "Write Cache(initial setting)": "写缓存(初始)", "Disk Cache Policy": "盘缓存策略",
    "Encryption": "加密", "Data Protection": "数据保护", "Active Operations": "活动操作",
    "Exposed to OS": "对 OS 暴露", "OS Drive Name": "OS 磁盘名",
    "Creation Date": "创建日期", "Creation Time": "创建时间",
    "Emulation type": "模拟类型", "Cachebypass size": "Cachebypass 大小",
    "Cachebypass Mode": "Cachebypass 模式",
    "Is LD Ready for OS Requests": "LD 就绪", "SCSI NAA Id": "SCSI NAA ID",
    "Unmap Enabled": "Unmap 启用",
}

CONTROLLER_PROP_CN = {
    "Abort CC on Error": "CC 出错时中止",
    "Access Policy": "访问策略",
    "Algorithm": "算法",
    "Alarm": "告警器状态",
    "Alarm Control": "告警器控制",
    "Allow Boot with Preserved Cache": "允许带保留缓存启动",
    "Allow Ctrl Encryption": "允许控制器加密",
    "Allow Mixed Redundancy on Array": "允许阵列使用混合冗余",
    "Auto Enhanced Import": "自动增强导入",
    "Auto Rebuild": "自动重建",
    "Auto detect BackPlane": "自动检测背板",
    "BBU": "BBU",
    "BGI Rate": "BGI 速率",
    "BGI Rate ": "BGI 速率",
    "BIOS Enumerate VDs": "BIOS 枚举 VD 数量",
    "Backend Port Count": "后端端口数",
    "BatteryFRU": "电池 FRU",
    "Battery Warning": "电池警告",
    "Base Algorithm": "基础算法",
    "Block SSD Write Disk Cache Change": "阻止变更 SSD 写盘缓存",
    "Boot Agent": "启动代理",
    "Bootloader Version": "Bootloader 版本",
    "BreakMirror RAID Support": "BreakMirror RAID 支持模式",
    "CC Rate": "CC 速率",
    "CPLD Version": "CPLD 版本",
    "Cache When BBU Bad": "BBU 异常时启用写缓存",
    "CacheVault Flash Size": "CacheVault Flash 容量",
    "Cached IO": "Cached IO",
    "Capability": "能力",
    "Certificate Algorithms": "证书算法",
    "ChipRevision": "芯片修订版",
    "Cluster Active": "集群活动状态",
    "Cluster Permitted": "允许集群",
    "Cluster Support": "集群支持",
    "Coercion Mode": "强制容量模式",
    "Configured": "已配置",
    "Controller in Hard Secure Mode": "控制器处于硬安全模式",
    "Controller in Soft Secure Mode": "控制器处于软安全模式",
    "Ctrl temperature(Degree Celsius)": "控制器温度 (°C)",
    "Ctrl-M Version": "Ctrl-M 版本",
    "Current Personality": "当前控制器模式",
    "Current Size of CacheCade (GB)": "当前 CacheCade 容量 (GB)",
    "Current Size of FW Cache (MB)": "当前固件缓存容量 (MB)",
    "Current": "当前值",
    "Dedicated Hot Spare": "支持专用热备",
    "Dedicated HotSpares Limited": "专用热备数量受限",
    "Default spin down time (mins)": "默认磁盘停转时间 (分钟)",
    "Default": "默认值",
    "Delay Among Spinup Groups (sec)": "磁盘起转组间延迟 (秒)",
    "Delay during POST": "POST 延迟 (秒)",
    "Deny CC": "禁止 CC",
    "Deny Clear": "禁止清除",
    "Deny Force Failed": "禁止强制标记 Failed",
    "Deny Force Good/Bad": "禁止强制标记 Good/Bad",
    "Deny Locate": "禁止定位",
    "Deny Missing Replace": "禁止 Missing 替换",
    "Deny SCSI Passthrough": "禁止 SCSI 直通",
    "Deny SMP Passthrough": "禁止 SMP 直通",
    "Deny STP Passthrough": "禁止 STP 直通",
    "Direct PD Mapping": "直接 PD 映射",
    "Domain Id": "域 ID",
    "Drive Coercion Mode": "磁盘强制容量模式",
    "Dirty LED Shows Drive Activity": "Dirty LED 显示磁盘活动",
    "Disable Join Mirror": "禁用 Join Mirror",
    "Disable Online Controller Reset": "禁用在在线控制器复位",
    "Disable Online PFK Change": "禁用在在线 PFK 变更",
    "Disable Puncturing": "禁用 Puncturing",
    "DisableHII": "禁用 HII",
    "Enable BIOS": "启用 BIOS",
    "Enable Ctrl-R": "启用 Ctrl-R",
    "Enable JBOD": "启用 JBOD",
    "Enable LDBBM": "启用 LDBBM",
    "Enable LED Header": "启用 LED 接口",
    "Enable PreBoot CLI": "启用 PreBoot CLI",
    "Enable SCSI Unmap": "启用 SCSI Unmap",
    "Enable Shield State": "启用 Shield State",
    "Enable Snapdump": "启用 Snapdump",
    "Enable SystemPD": "启用 SystemPD",
    "Enable Web BIOS": "启用 WebBIOS",
    "EnableCrashDump": "启用 CrashDump",
    "EnableLDBBM": "启用 LDBBM",
    "Enterprise Key management": "企业密钥管理 (EKM)",
    "ECC Bucket Leak Rate (hrs)": "ECC Bucket 泄漏率 (小时)",
    "ECC Bucket Size": "ECC Bucket 大小",
    "Expose Enclosure Devices": "向系统暴露背板设备",
    "Extended LD": "扩展 LD",
    "FDE Drive Mix Support": "FDE 磁盘混用支持",
    "FW and Event Time in GMT": "固件和事件时间采用 GMT",
    "FW Package Build": "固件包版本",
    "FW Version": "固件版本",
    "Flash Size": "Flash 容量",
    "Flush Time(Default)": "刷写时间 (默认)",
    "Force Offline": "允许强制离线",
    "Force Online": "允许强制在线",
    "Force Rebuild": "允许强制重建",
    "Foreign Config Import": "支持外来配置导入",
    "Front End Port Count": "前端端口数",
    "Global Hot Spares": "支持全局热备",
    "Headless Mode": "无头模式",
    "Hash Algorithm": "哈希算法",
    "ID": "ID",
    "Image name": "映像名称",
    "IO Policy": "IO 策略",
    "Inactivity Print": "无活动打印",
    "JBOD Drives": "JBOD 磁盘数量",
    "Key Update Pending": "密钥更新待生效",
    "LED Show Drive Activity": "LED 显示磁盘活动",
    "MPT Version": "MPT 版本",
    "Maintain PD Fail History": "保留 PD 故障历史",
    "Max Arms Per VD": "每个 VD 最大 Arm 数",
    "Max Arrays": "最大阵列数",
    "Max Chained Enclosures": "最大级联背板数",
    "Max Configurable CacheCade Size(GB)": "可配置 CacheCade 最大容量 (GB)",
    "Max Data Transfer Size": "最大数据传输大小",
    "Max Drives to Spinup at One Time": "单次最大磁盘起转数",
    "Max Number of VDs": "最大 VD 数",
    "Max Parallel Commands": "最大并行命令数",
    "Max SGE Count": "最大 SGE 数量",
    "Max Spans Per VD": "每个 VD 最大 Span 数",
    "Max Strip Size": "最大条带大小",
    "Max Strips PerIO": "每次 IO 最大条带数",
    "Max Transportable DGs": "最大可迁移磁盘组数",
    "Max VD per array": "每个阵列最大 VD 数",
    "Maximum Controller Nodes": "最大控制器节点数",
    "Maximum number of direct attached drives to spin up in 1 min": "每分钟最大直连磁盘起转数",
    "Measurement Algorithms": "度量算法",
    "Min Strip Size": "最小条带大小",
    "Mix in Enclosure": "背板内磁盘混用",
    "Mix of SAS/SATA of HDD type in VD": "VD 内 HDD 的 SAS/SATA 混用",
    "Mix of SAS/SATA of SSD type in VD": "VD 内 SSD 的 SAS/SATA 混用",
    "Mix of SSD/HDD in VD": "VD 内 SSD/HDD 混用",
    "NCQ": "NCQ",
    "NVRAM Size": "NVRAM 容量",
    "Name": "名称",
    "Number of Certificate algorithm records": "证书算法记录数",
    "Number of Measurement Algorithm Records": "度量算法记录数",
    "NVMe thermal poll Interval": "NVMe 温度轮询间隔",
    "On Board Expander": "板载 Expander",
    "On Board Memory Size": "板载内存容量",
    "PCI Slot Number": "PCI 插槽号",
    "PSOC Version": "PSOC 版本",
    "Patrol Read Rate": "巡检速率",
    "Peer Controller Status": "对端控制器状态",
    "Pending Images in Flash": "Flash 中待生效映像",
    "Performance Metrics": "性能指标",
    "Phy Polarity": "PHY 极性",
    "Phy PolaritySplit": "PHY 极性与拆分",
    "Point In Time Progress": "时间点进度",
    "Power Saving option": "节能选项",
    "Power Savings": "节能",
    "Policies Table": "策略表",
    "Policy": "策略",
    "RAID Level Supported": "支持的 RAID 级别",
    "ROC temperature(Degree Celsius)": "ROC 温度 (°C)",
    "Read Policy": "读策略",
    "Read cache bypass enabled for Parity RAID LDs": "奇偶校验 RAID LD 启用读缓存绕过",
    "Read cache bypass enabled for Parity RAID LDs ": "奇偶校验 RAID LD 启用读缓存绕过",
    "Real Time Scheduler": "实时调度器",
    "Rebuild Rate": "重建速率",
    "Reorder Host Requests": "重排主机请求",
    "Reconstruct Rate": "重构速率",
    "Reconstruction": "支持重构",
    "Remaining Secure Boot Key Slots": "剩余安全启动密钥槽位",
    "Restore Hot Spare on Insertion": "插入磁盘时恢复热备",
    "Revertible Hot Spares": "可恢复热备",
    "Restore HotSpare on Insertion": "插入时恢复热备",
    "SAS Disable": "禁用 SAS",
    "SBR Version": "SBR 版本",
    "SMART Mode": "SMART 模式",
    "Safe ID": "Safe ID",
    "Secure Boot Enabled": "已启用安全启动",
    "Security Protocol": "安全协议",
    "Security Key Assigned": "已分配安全密钥",
    "Self Diagnostic": "自诊断",
    "Serial Debugger": "串口调试",
    "Set Power State For Cfg": "按配置设置电源状态",
    "Slot Group count": "槽位组数量",
    "Slot count": "槽位数量",
    "SlotGroup No": "槽位组编号",
    "Snapshot Enabled": "快照已启用",
    "Spanning": "支持 Spanning",
    "Spin Down Mode": "磁盘停转模式",
    "Stop BIOS on Error": "出错时停止 BIOS",
    "Specification": "规格",
    "SmartPoll Interval for DirectAttached": "直连磁盘 SMART 轮询间隔",
    "Supported Drive FW Download Chunk Size": "磁盘固件下载分块大小",
    "Supported Drives": "支持的磁盘类型",
    "Temperature Sensor for Controller": "控制器温度传感器",
    "Temperature Sensor for ROC": "ROC 温度传感器",
    "Time taken to detect CME": "CME 检测时间",
    "Topology Type": "拓扑类型",
    "Total Locked Foreign PDs": "已锁定外来 PD 数",
    "Total foreign dirve groups": "外来磁盘组总数",
    "Total foreign Drive Groups": "外来磁盘组总数",
    "TPM": "TPM",
    "TTY Log In Flash": "在 Flash 中保存 TTY 日志",
    "Treat Single span R1E as R10": "将单 Span R1E 视为 R10",
    "Un-Certified Hard Disk Drives": "未认证硬盘处理方式",
    "Upgradable CPLD": "CPLD 可升级",
    "Upgradable PSOC": "PSOC 可升级",
    "Upgrade Key": "升级密钥",
    "Use drive activity for locate": "使用磁盘活动指示灯定位",
    "VD PowerSave Policy": "VD 节能策略",
    "Version": "版本",
    "Write Policy": "写策略",
    "ZCR Config": "ZCR 配置",
    "Zero Based Enclosure Enumeration": "背板从 0 开始编号",
    "Available Config": "可用配置",
    "BBU Learn": "BBU 学习",
    "Cache Cade Virtual Drives": "CacheCade 虚拟盘",
    "Cachevault Learn": "CacheVault 学习信息",
    "Clear Sequence Number": "清除序号",
    "CLI Version": "CLI 版本",
    "Connector Mode Info": "连接器模式信息",
    "ContainsCertificate": "包含证书",
    "Controller Properties": "控制器属性",
    "Controller Time": "控制器时间",
    "Current Controller Date/Time": "控制器时间",
    "Current Controller Date/time": "控制器时间",
    "Current System Date/time": "系统时间",
    "Current Config": "当前配置",
    "Current OOB Info": "当前 OOB 信息",
    "DG Drive LIST": "磁盘组成员列表",
    "Default OOB Info": "默认 OOB 信息",
    "Detailed Status": "详细状态",
    "Device_Type": "设备类型",
    "Diag Buffer": "诊断缓冲区",
    "Drive": "磁盘",
    "Event Data": "事件数据",
    "Event Info": "事件信息",
    "Event Qualifier": "事件限定符",
    "Event Trigger Information": "事件触发信息",
    "Event Value": "事件值",
    "Failed NVMe Devices": "失败的 NVMe 设备",
    "FOREIGN PREVIEW": "外来配置预览",
    "FREE SPACE DETAILS": "可用空间明细",
    "Foreign PD List": "外来 PD 列表",
    "Foreign Topology": "外来配置拓扑",
    "Foreign VD List": "外来 VD 列表",
    "GasGaugeStatus": "电量计状态",
    "HtbProperties": "热备属性",
    "IOC LogInfo": "IOC 日志信息",
    "IOC Status": "IOC 状态",
    "Lane Info": "Lane 信息",
    "Lane No": "Lane 编号",
    "LaneInformation": "Lane 信息",
    "LaneNo": "Lane 编号",
    "LaneSpeed": "Lane 速率",
    "Link Configuration": "链路配置",
    "Link No": "链路编号",
    "Message": "消息",
    "Mfg. Date": "制造日期",
    "Mode": "模式",
    "Mux Info": "Mux 信息",
    "Needs Re-hosting": "需要重新托管",
    "Newest Sequence Number": "最新序号",
    "Next Learn": "下次学习",
    "Oldest Sequence Number": "最早序号",
    "Operating system": "操作系统",
    "Operation": "操作",
    "PCIE Link Event Info": "PCIe 链路事件信息",
    "PCIe Event Counters": "PCIe 事件计数",
    "PcieLinkEventInfo": "PCIe 链路事件信息",
    "Pending Config": "待生效配置",
    "Phy Error Counters": "PHY 错误计数",
    "Phy Info": "PHY 信息",
    "Phy No": "PHY 编号",
    "PhyInfo": "PHY 信息",
    "PhyNo": "PHY 编号",
    "Port Number": "端口编号",
    "Premium Feature Key": "高级功能密钥",
    "Product Name": "产品名称",
    "Re-host Information": "重新托管信息",
    "Reboot Sequence Number": "重启序号",
    "SAS Event Counters": "SAS 事件计数",
    "SASLinkSpeed": "SAS 链路速率",
    "Shutdown Sequence Number": "关机序号",
    "Slot Status Details": "槽位状态明细",
    "SlotGroup": "槽位组",
    "SnapDump Details": "SnapDump 明细",
    "SnapDump Properties": "SnapDump 属性",
    "Snapdump Size": "SnapDump 大小",
    "Snapdump time": "SnapDump 时间",
    "Status Code": "状态码",
    "System Time": "系统时间",
    "Temp": "温度",
    "Test Link State": "链路状态测试",
    "TestLinkState": "链路状态测试",
    "Time Remaining": "剩余时间",
    "Total Cache Cade Virtual Drives": "CacheCade 虚拟盘总数",
    "Total Cached Drives": "缓存磁盘总数",
    "Total Drive Count": "磁盘总数",
    "Total Foreign PDs": "外来 PD 总数",
    "Total Free Slots": "空闲槽位总数",
    "Total Slot Count": "槽位总数",
    "Total VD Count": "VD 总数",
    "Trigger Information": "触发信息",
    "UN-CONFIGURED DRIVE LIST": "未配置磁盘列表",
    "Unconfigured Drive Count": "未配置磁盘数",
    "Vendor": "厂商",
    "Wwid": "WWID",
    "Correctable": "可纠正",
    "Uncorrectable": "不可纠正",
    "Curr": "当前值",
    "CurrSpeed": "当前速率",
    "Dflt": "默认",
    "Enbl": "启用",
    "FSpace": "可用空间",
    "FreSpc": "可用空间",
    "MaxAHCIDev": "最大 AHCI 设备数",
    "MaxLD": "最大 LD 数",
    "MaxPCIeDev": "最大 PCIe 设备数",
    "MaxPacketSize": "最大数据包大小",
    "MaxPayloadSize": "最大负载大小",
    "MaxPhyDrv": "最大物理盘数",
    "MaxSpeed": "最大速率",
    "NoVDs": "无 VD",
    "Optm": "最优",
    "Pend": "待生效",
    "RepInProg": "重建进行中",
    "SupSpeed": "支持速率",
    "WBSup": "支持回写",
    "Adv S/W Opt": "高级软件选项",
    "Arr": "阵列",
    "BIOS Version": "BIOS 版本",
    "Cmp": "比较",
    "Conn": "连接",
    "Consist": "一致性",
    "Ctrl": "控制器",
    "Msg": "消息",
}

CONTROLLER_FEATURE_CN = {
    "AES Encryption Algorithm": "AES 加密算法",
    "Allowed Operations": "允许的操作",
    "Boot Time PFK Change": "启动时 PFK 变更",
    "Breakmirror": "BreakMirror",
    "CPLDUpdate": "CPLD 更新",
    "Clear Snapdump": "清除 Snapdump",
    "Config Page Model": "配置页面模式",
    "Ctrl Info Extended": "扩展控制器信息",
    "Debug Queue": "调试队列",
    "Degraded Media": "降级介质",
    "Diagnostic results": "诊断结果",
    "DisableImmediateIO": "禁用 Immediate IO",
    "Drive Crypto Erase": "磁盘加密擦除",
    "Drive FW Download Mask": "磁盘固件下载掩码",
    "Drive Makers Authority": "磁盘厂商权限",
    "DrvActivityLEDSetting": "磁盘活动 LED 设置",
    "Dual Fw Image": "双固件映像",
    "EKM": "EKM",
    "Emergency Spares": "紧急热备",
    "Emulated Drives": "模拟磁盘",
    "Enclosure Enumeration": "背板枚举",
    "Encrypted MFC": "加密 MFC",
    "Enhanced Foreign Import": "增强外来配置导入",
    "Ext Enclosure": "扩展背板",
    "Extended Controller Property": "扩展控制器属性",
    "Extended Drive performance Monitoring": "扩展磁盘性能监控",
    "Extended Sanitize": "扩展 Sanitize",
    "FW Triggered Snapdump": "固件触发的 Snapdump",
    "FastPath": "FastPath",
    "FlushWriteVerify": "Flush Write Verify",
    "Force Personality Change": "强制变更控制器模式",
    "ForceFlash": "强制刷写",
    "ForceTo512e": "强制 512e",
    "IButton less": "无 iButton",
    "Inactivity Print": "无活动打印",
    "JBOD": "JBOD",
    "JBOD Write cache": "JBOD 写缓存",
    "LDPI Type1": "LDPI Type1",
    "LDPI Type2": "LDPI Type2",
    "LDPI Type3": "LDPI Type3",
    "Lane DeviceType": "Lane 设备类型",
    "Lane current speed": "Lane 当前速率",
    "Large QD Support": "大队列深度支持",
    "LargeIOSupport": "大 IO 支持",
    "Ld BBM Info": "LD BBM 信息",
    "Least Latency Mode": "最低延迟模式",
    "Maintenance Mode": "维护模式",
    "Max Rate SATA": "最大 SATA 速率",
    "Multipath": "多路径",
    "NVMe Init Error Device ConnectorIndex": "NVMe 初始化错误设备 ConnectorIndex",
    "NVMe Repair": "NVMe 修复",
    "NVMe Thermal Poll": "NVMe 温度轮询",
    "NVMe Width": "NVMe 宽度",
    "None Mode Params": "None 模式参数",
    "Odd & Even Drive count in RAID1E": "RAID1E 奇数/偶数磁盘数量",
    "OnDemand Snapdump": "按需 Snapdump",
    "PCIe PERST override": "PCIe PERST 覆盖",
    "PCIe Reference Clock override": "PCIe 参考时钟覆盖",
    "PFK": "PFK",
    "PHY current speed": "PHY 当前速率",
    "PI": "PI",
    "PSOC Part Information": "PSOC 部件信息",
    "PSOC Update": "PSOC 更新",
    "Parallel FW Update": "并行固件更新",
    "Parity Read Cache Bypass": "奇偶校验读缓存绕过",
    "Perf Tuning": "性能调优",
    "Phy State Control": "PHY 状态控制",
    "Physical Link Speed": "物理链路速率",
    "Platform Security": "平台安全",
    "Power State": "电源状态",
    "Powersave Max With Cache": "带缓存的最大节能",
    "Report Delay OCR Range": "报告延迟 OCR 范围",
    "Reset Now": "立即复位",
    "SMP Passthru with Port Number": "带端口号的 SMP 直通",
    "SRIOV Options": "SR-IOV 选项",
    "SSC Association": "SSC 关联",
    "SSC WriteBack": "SSC 回写",
    "SSD PatrolRead": "SSD 巡检",
    "SSD Wear Gauge": "SSD 磨损指标",
    "Sanitize": "Sanitize",
    "Secure Boot": "安全启动",
    "Security": "安全功能",
    "SecurityonJBOD": "JBOD 安全功能",
    "Sesmonitoring": "SES 监控",
    "Set Link Speed": "设置链路速率",
    "Shield State": "Shield State",
    "Slow array threshold calculation": "慢阵列阈值计算",
    "Smart Poll Interval for DirectAttached": "直连磁盘 SMART 轮询间隔",
    "SnapDump Preboot Trace Buffer Toggle": "SnapDump 预启动跟踪缓冲区切换",
    "Snapdump": "Snapdump",
    "Start of day PL log capture": "每日起始 PL 日志捕获",
    "Suspend Resume BG ops": "挂起/恢复后台操作",
    "SystemPD": "SystemPD",
    "T10 Power State": "T10 电源状态",
    "Target ID Reuse": "Target ID 重用",
    "Temperature": "温度",
    "Third Party Drive Lock Status": "第三方磁盘锁定状态",
    "Uneven span": "非均匀 Span",
    "Unrecovered Medium Error Count": "未恢复介质错误计数",
    "VD Cachebypass": "VD 缓存绕过",
    "VD Hide": "隐藏 VD",
    "VD Scsi Unmap": "VD SCSI Unmap",
    "VD discardCacheDuringLDDelete": "删除 LD 时丢弃 VD 缓存",
    "VolatileKey": "易失性密钥",
    "Write Buffer 16": "16 字节写缓冲",
    "Write Journal Pinning": "写日志固定",
    "discardCacheDuringLDDelete": "删除 LD 时丢弃缓存",
    "more than 8 Phys": "多于 8 个 PHY",
    "the OCE without adding drives": "无需增加磁盘执行 OCE",
}

CONTROLLER_PHRASE_CN = {
    "Virtual Drives": "虚拟盘",
    "Physical Drives": "物理盘",
    "Drive Groups": "磁盘组",
    "Foreign Drive Groups": "外来磁盘组",
    "Foreign Drives": "外来磁盘",
    "Foreign PDs": "外来 PD",
    "Foreign PD": "外来 PD",
    "Drive Firmware": "磁盘固件",
    "Firmware Download": "固件下载",
    "Link Configuration": "链路配置",
    "Link Status": "链路状态",
    "Power State": "电源状态",
    "Temperature Sensor": "温度传感器",
    "Controller": "控制器",
    "Configuration": "配置",
    "Information": "信息",
    "Properties": "属性",
    "Property": "属性",
    "Preservation": "保留",
    "Diagnostics": "诊断",
    "Diagnostic": "诊断",
    "Sequence Number": "序号",
    "Status": "状态",
    "Details": "明细",
    "Count": "数量",
    "Time": "时间",
    "Speed": "速率",
    "Link": "链路",
    "Power": "电源",
    "Temperature": "温度",
    "Firmware": "固件",
    "Cache": "缓存",
    "Virtual Drive": "虚拟盘",
    "Physical Drive": "物理盘",
    "Drives": "磁盘",
    "Drive": "磁盘",
    "Slots": "槽位",
    "Slot": "槽位",
    "Events": "事件",
    "Event": "事件",
    "Errors": "错误",
    "Error": "错误",
    "Learn": "学习",
    "Current": "当前",
    "Default": "默认",
    "Pending": "待生效",
    "Available": "可用",
    "Newest": "最新",
    "Oldest": "最早",
    "Next": "下次",
    "Total": "总计",
    "Maximum": "最大",
    "Minimum": "最小",
    "Mode": "模式",
    "Type": "类型",
    "Code": "代码",
    "Message": "消息",
    "Operation": "操作",
    "Re-host": "重新托管",
    "hosting": "托管",
    "System": "系统",
    "Log": "日志",
    "Device": "设备",
    "Devices": "设备",
    "Port": "端口",
    "Number": "编号",
    "Access": "访问",
    "Description": "描述",
    "Method": "方法",
    "Result": "结果",
    "Row": "行",
    "Value": "值",
    "Size": "容量",
    "State": "状态",
    "Sealed": "已封装",
    "Empty": "空",
    "Retention": "保留",
    "New": "新",
    "Requested": "请求",
    "Packet": "数据包",
    "Payload": "负载",
    "Set": "设置",
    "Prop": "属性",
    "Data": "数据",
    "Buffer": "缓冲区",
    "Queue": "队列",
    "Max": "最大",
    "Min": "最小",
    "Enable": "启用",
    "Disable": "禁用",
    "Supported": "支持",
    "Width": "宽度",
    "Thermal": "温度",
    "Poll": "轮询",
    "Interval": "间隔",
    "On Demand": "按需",
    "Is": "是否",
    "Config": "配置",
    "Management": "管理",
    "Monitor": "监控",
    "Monitoring": "监控",
    "Recovery": "恢复",
    "Reserved": "保留",
    "Usage": "使用情况",
    "Bbu": "BBU",
    "Cachevault": "CacheVault",
    "Sas": "SAS",
    "Pcie": "PCIe",
    "Nvme": "NVMe",
    "Ioc": "IOC",
    "Phy": "PHY",
    "Vd": "VD",
    "Pd": "PD",
    "Dev": "设备",
    "Fw": "固件",
    "No": "无",
    "VDs": "VD",
    "Version": "版本",
    "Boot": "启动",
    "Info": "信息",
    "Feature": "功能",
    "Unknown": "未知",
    "Hardware": "硬件",
    "Software": "软件",
    "Serial": "串行",
    "Attached": "连接",
    "Identifier": "标识",
    "Capability": "能力",
    "Threshold": "阈值",
    "Limit": "限制",
    "Level": "级别",
    "Policy": "策略",
    "Integrated": "集成",
    "Physical": "物理",
    "Logical": "逻辑",
    "Internal": "内部",
    "External": "外部",
    "Host": "主机",
    "Peer": "对端",
    "Primary": "主",
    "Secondary": "次",
    "Request": "请求",
    "Response": "响应",
    "Command": "命令",
    "Process": "进程",
    "Progress": "进度",
    "Download": "下载",
    "Upload": "上传",
    "Update": "更新",
    "Remaining": "剩余",
}


def normalize_controller_key(text):
    text = re.sub(r"[\s_\-]+", " ", str(text).strip())
    text = re.sub(r"[.:]+$", "", text)
    return text.lower()


CONTROLLER_NORMALIZED_CN = {}
for mapping in (CONTROLLER_SECTION_CN, CONTROLLER_PROP_CN):
    for source, translated in mapping.items():
        CONTROLLER_NORMALIZED_CN.setdefault(
            normalize_controller_key(source), translated)


def tr_prop(k):
    return PROP_CN.get(k, k)


def translate_controller_terms(text):
    result = re.sub(r"[\s_]+", " ", str(text).strip())
    result = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", result)
    for source, translated in sorted(
            CONTROLLER_PHRASE_CN.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])"
        result = re.sub(pattern, translated, result, flags=re.IGNORECASE)
    result = result.replace("-", " ")
    result = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", result)
    return re.sub(r"\s+", " ", result).strip()


def tr_controller_prop(key):
    text = str(key).strip()
    if text in CONTROLLER_PROP_CN:
        return CONTROLLER_PROP_CN[text]
    normalized = normalize_controller_key(text)
    if normalized in CONTROLLER_NORMALIZED_CN:
        return CONTROLLER_NORMALIZED_CN[normalized]
    for prefix, translated in (
            ("Support ", "支持 "), ("Deny ", "禁止 "),
            ("Force ", "强制 "), ("Enable ", "启用 "), ("Disable ", "禁用 "),
            ("Max ", "最大 "), ("Min ", "最小 "), ("Total ", "总计 "),
            ("Current ", "当前 "), ("Default ", "默认 "), ("Pending ", "待生效 "),
            ("Available ", "可用 "), ("Newest ", "最新 "), ("Oldest ", "最早 "),
            ("Next ", "下次 ")):
        if text.startswith(prefix):
            feature = text[len(prefix):]
            translated_feature = CONTROLLER_FEATURE_CN.get(
                feature, translate_controller_terms(feature))
            combined = translated + translated_feature
            return re.sub(
                r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", combined)
    direct = tr_prop(text)
    if direct != text:
        return direct
    return translate_controller_terms(text)


def parse_pd_rows(payload):
    """从 /cX/eall/sall show J 的解析结果里提取物理盘列表."""
    drives = []
    for _title, _headers, rows in iter_tables(payload["Controllers"][0].get("Response Data", {})):
        for row in rows:
            state = size = model = ""
            eid = slt = None
            for key, value in row.items():
                k = str(key).strip().upper()
                if k in ("EID:SLT", "EID:SLOT"):
                    m = re.match(r"\s*(\d+):(\d+)", str(value))
                    if m:
                        eid, slt = m.group(1), m.group(2)
                elif k == "EID":
                    eid = str(value).strip()
                elif k in ("SLT", "SLOT"):
                    slt = str(value).strip()
                elif k == "STATE":
                    state = str(value)
                elif k == "SIZE":
                    size = str(value)
                elif k in ("MODEL", "MODEL NUMBER") and not model:
                    model = str(value)
            if eid is None or slt is None or not str(eid).isdigit() or not str(slt).isdigit():
                continue
            drives.append((eid, slt, size, model, state))
    return drives


def is_ugood(state):
    low = str(state).lower()
    return (("ugood" in low or "unconfigured good" in low
             or ("unconfigured" in low and "good" in low)) and "foreign" not in low)


def row_state_tag(row):
    for key, value in row.items():
        low = key.lower()
        if "state" in low or "status" in low:
            return tag_for_state(str(value))
    return ""


def render_tables(tree, tables, row_data=None, heading_cmd=None):
    """把 iter_tables 的结果渲染进 Treeview, 返回列名列表."""
    tree.delete(*tree.get_children())
    if row_data is not None:
        row_data.clear()
    all_headers = []
    for _title, headers, _rows in tables:
        for h in headers:
            if h not in all_headers:
                all_headers.append(h)
    tree["columns"] = all_headers
    for h in all_headers:
        opts = {"text": tr_header(h)}
        if heading_cmd:
            opts["command"] = heading_cmd(h)
        tree.heading(h, **opts)
        width = max(56, min(240, 10 * len(str(h)) + 24))
        tree.column(h, width=width, anchor="w", stretch=(h == all_headers[-1]))
    multi = len(tables) > 1
    for title, _headers, rows in tables:
        if multi:
            tree.insert("", "end", values=[f"— {tr_title(title)} —"] + [""] * (len(all_headers) - 1),
                        tags=("section",))
        for row in rows:
            values = [tr_state(fmt_cell(row.get(h))) for h in all_headers]
            tag = row_state_tag(row)
            iid = tree.insert("", "end", values=values, tags=(tag,) if tag else ())
            if row_data is not None:
                row_data[iid] = row
    tree.tag_configure("section", font=(UI_FONT[0], UI_FONT[1], "bold"), foreground="#1565c0")
    tree.tag_configure("green", foreground="#0a7d32")
    tree.tag_configure("red", foreground="#c62828")
    tree.tag_configure("orange", foreground="#b26a00")
    return all_headers


def apply_danger_menu_colors(menu):
    """Keep dangerous menu entries red while preserving the pale-blue hover background."""
    menu.configure(activebackground=HOVER_BG, activeforeground=TEXT_FG)
    end = menu.index("end")
    if end is None:
        return
    for index in range(end + 1):
        try:
            if menu.type(index) == "cascade":
                submenu = menu.entrycget(index, "menu")
                if submenu:
                    apply_danger_menu_colors(menu.nametowidget(submenu))
            foreground = str(menu.entrycget(index, "foreground"))
            if foreground.casefold() == DANGER_COLOR.casefold():
                menu.entryconfigure(
                    index, activebackground=HOVER_BG,
                    activeforeground=DANGER_COLOR)
        except tk.TclError:
            continue


def bind_context_menu(widget, build_entries):
    """绑定右键菜单; build_entries() 返回 [(label, cmd), ...], 元素 "-" 表示分隔线."""
    menu = tk.Menu(
        widget, tearoff=0, background=CONTENT_BG, foreground=TEXT_FG,
        activebackground=HOVER_BG, activeforeground=TEXT_FG)

    def popup(event):
        try:
            if isinstance(widget, ttk.Treeview):
                iid = widget.identify_row(event.y)
                if iid:
                    widget.selection_set(iid)
                    widget.focus(iid)
            entries = build_entries()
            if not entries:
                return "break"
            menu.delete(0, "end")
            for item in entries:
                if item == "-":
                    menu.add_separator()
                else:
                    if len(item) > 2 and item[2] == "danger":
                        menu.add_command(label=item[0], command=item[1],
                                         foreground=DANGER_COLOR)
                    else:
                        menu.add_command(label=item[0], command=item[1])
            apply_danger_menu_colors(menu)
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    widget.bind("<Button-3>", popup)


def text_menu_entries(text):
    def copy_sel():
        try:
            sel = text.get("sel.first", "sel.last")
        except tk.TclError:
            return
        text.clipboard_clear()
        text.clipboard_append(sel)

    def copy_all():
        text.clipboard_clear()
        text.clipboard_append(text.get("1.0", "end-1c"))

    def select_all():
        text.tag_add("sel", "1.0", "end")

    return [("复制选中", copy_sel), ("复制全部", copy_all), ("全选", select_all)]


def build_text(parent):
    """带双向滚动条的文本区, 返回 (frame, text)."""
    frame = ttk.Frame(parent)
    text = tk.Text(
        frame, font=MONO_FONT, wrap="none", background=CONTENT_BG,
        foreground=TEXT_FG, insertbackground=TEXT_FG,
        selectbackground=SELECT_BG, selectforeground=SELECT_FG)
    vsb = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    hsb = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
    text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    bind_context_menu(text, lambda: text_menu_entries(text))
    text.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
    return frame, text


def show_result_window(app, title, res, command=""):
    win = tk.Toplevel(app.root)
    win.title(f"{title} - {APP_TITLE}")
    win.geometry("880x560")
    win.transient(app.root)
    top = ttk.Frame(win)
    top.pack(fill="x", padx=10, pady=(8, 4))
    ttk.Label(top, text=f"storcli64 {command}", font=MONO_FONT).pack(anchor="w")
    if res.get("ok"):
        status = tr_status(extract_text_status(res.get("stdout", "")) or (
            "Success" if res.get("code") == 0 else f"ExitCode {res.get('code')}"))
        try:
            st, desc = command_status(parse_json_output(res["stdout"]))
            if st:
                status = tr_status(st) + (f" ({tr_desc(desc)})" if desc and desc != "None" else "")
        except Exception:
            pass
        m = re.search(r"^\s*Description\s*=\s*(.+)$", res.get("stdout", "") or "", re.M)
        if m and "(" not in status:
            status += f" ({tr_desc(m.group(1).strip())})"
        line = f"状态: {status}    耗时: {res.get('elapsed', 0):.1f}s"
    else:
        line = f"执行失败: {res.get('error', '')}"
    ttk.Label(top, text=line, font=UI_FONT).pack(anchor="w", pady=(2, 0))
    _frame, text = build_text(win)
    content = res.get("stdout", "") or ""
    if (res.get("stderr") or "").strip():
        content += "\n--- stderr ---\n" + res["stderr"]
    text.insert("end", content or "(无输出)")
    bar = ttk.Frame(win)
    bar.pack(fill="x", padx=10, pady=(0, 8))

    def copy_all():
        win.clipboard_clear()
        win.clipboard_append(content)

    def save_as():
        path = filedialog.asksaveasfilename(parent=win, defaultextension=".txt",
                                            filetypes=[("文本文件", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

    ttk.Button(bar, text="复制全部", command=copy_all).pack(side="left")
    ttk.Button(bar, text="另存为...", command=save_as).pack(side="left", padx=6)
    ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right")


# ---------------------------------------------------------------- 后台执行线程

class Worker(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app

    def run(self):
        while True:
            job = self.app.cmd_q.get()
            if job is None:
                break
            exe, args, timeout, callback, ctrl, request_id = job
            result = self.execute(exe, args, timeout)
            result["args"] = args
            result["callback"] = callback
            result["ctrl"] = ctrl
            result["request_id"] = request_id
            self.app.result_q.put(result)

    def execute(self, exe, args, timeout):
        if not exe or not os.path.isfile(exe):
            return {"ok": False, "error": f"未找到 StorCLI 可执行文件: {exe or '(未设置)'}"}
        started = time.time()
        try:
            proc = subprocess.run([exe] + list(args), capture_output=True,
                                  timeout=timeout, cwd=os.path.dirname(exe),
                                  creationflags=CREATE_NO_WINDOW)
            return {"ok": True, "stdout": decode_bytes(proc.stdout),
                    "stderr": decode_bytes(proc.stderr),
                    "code": proc.returncode, "elapsed": time.time() - started}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"命令超时 ({timeout}s)", "elapsed": time.time() - started}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "elapsed": time.time() - started}


# ---------------------------------------------------------------- 标签页

class TextTab:
    """纯文本输出标签页(如 概览 = storcli /cX show all)."""

    def __init__(self, parent, app, build_args):
        self.app = app
        self.build_args = build_args
        self._load_seq = 0
        self.frame = ttk.Frame(parent)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="刷新", command=self.load).pack(side="left")
        self.info = ttk.Label(bar, text="", font=UI_FONT)
        self.info.pack(side="left", padx=10)
        self.text_frame, self.text = build_text(self.frame)

    def load(self):
        if self.app.current_ctrl is None:
            self.info.config(text="未选择控制器")
            return
        ctrl = self.app.current_ctrl
        self._load_seq += 1
        seq = self._load_seq
        args = self.build_args(ctrl)
        self.info.config(text="加载中: storcli64 " + " ".join(args))

        def done(res):
            if ctrl != self.app.current_ctrl or seq != self._load_seq:
                return
            self.on_done(res)

        self.app.run_cmd(args, done, timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def on_done(self, res):
        if res.get("ok"):
            content = res["stdout"]
            if res["stderr"].strip():
                content += "\n--- stderr ---\n" + res["stderr"]
            self.text.delete("1.0", "end")
            self.text.insert("end", content)
            status = tr_status(extract_text_status(content))
            self.info.config(
                text=(status + " · " if status else "")
                     + f"{res['elapsed']:.1f}s · {time.strftime('%H:%M:%S')}")
        else:
            self.text.delete("1.0", "end")
            self.text.insert("end", f"[错误] {res.get('error', '')}")
            self.info.config(text="失败")


class DataTab:
    """表格标签页: 以 JSON 模式执行命令并自动解析为表格, 失败则回退纯文本."""

    FILTERS = ("全部", "异常", "正常", "在线", "离线", "未配置", "热备", "重建/初始化")

    def __init__(self, parent, app, build_args, buttons=(), hint="双击行查看详情"):
        self.app = app
        self.build_args = build_args
        self.tables = []
        self.headers = []
        self.row_data = {}
        self.sort_state = {}
        self.loaded_ctrl = None
        self._load_seq = 0
        self.tree_mode = True
        self.raw_text = ""
        self.friendly_text = ""
        self.last_status = ""
        self.last_refresh = ""
        self.hint = hint
        self.button_widgets = {}
        self.frame = ttk.Frame(parent)

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=(6, 3))
        ttk.Button(bar, text="刷新", command=self.load).pack(side="left")
        style = ttk.Style(self.frame)
        style.configure("Danger.TButton", foreground=DANGER_COLOR)
        for item in buttons:
            kw = {}
            if len(item) > 2 and item[2] == "danger":
                kw["style"] = "Danger.TButton"
            button = ttk.Button(bar, text=item[0], command=item[1], **kw)
            button.pack(side="left", padx=(6, 0))
            self.button_widgets[item[0]] = button
        self.info = ttk.Label(bar, text=hint, font=UI_FONT)
        self.info.pack(side="left", padx=10)
        self.mode_btn = ttk.Button(bar, text="原始输出", command=self.toggle_mode, width=10)
        self.mode_btn.pack(side="right")
        ttk.Button(bar, text="导出...", command=self.export_table, width=8).pack(
            side="right", padx=(0, 4))

        filter_bar = ttk.Frame(self.frame)
        filter_bar.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(filter_bar, text="搜索:").pack(side="left")
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(filter_bar, textvariable=self.filter_var, width=28)
        filter_entry.pack(side="left", padx=(4, 8))
        ttk.Label(filter_bar, text="状态:").pack(side="left")
        self.state_filter_var = tk.StringVar(value="全部")
        state_filter = ttk.Combobox(
            filter_bar, textvariable=self.state_filter_var, values=self.FILTERS,
            state="readonly", width=12)
        state_filter.pack(side="left", padx=4)
        ttk.Button(filter_bar, text="清空", command=self.clear_filters, width=6).pack(
            side="left", padx=(4, 8))
        self.selection_label = ttk.Label(filter_bar, text="", font=UI_FONT)
        self.selection_label.pack(side="left", padx=4)
        ttk.Label(filter_bar, text=hint, foreground="#666").pack(side="right")

        self.tree_frame = ttk.Frame(self.frame)
        self.tree = ttk.Treeview(self.tree_frame, show="headings", selectmode="browse")
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.rowconfigure(0, weight=1)
        self.tree_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda _e: self.app.tab_double_click(self))
        self.tree.bind("<<TreeviewSelect>>", self.on_selection_changed)
        self.text_frame, self.text = build_text(self.frame)
        self.text_frame.pack_forget()
        self.tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.filter_var.trace_add("write", lambda *_: self.refresh_table_view())
        state_filter.bind("<<ComboboxSelected>>", lambda _e: self.refresh_table_view())

    def load(self):
        if self.app.current_ctrl is None:
            self.info.config(text="未选择控制器")
            return
        ctrl = self.app.current_ctrl
        if self.loaded_ctrl != ctrl:
            self.tree.delete(*self.tree.get_children())
            self.tree.configure(columns=())
            self.tables = []
            self.headers = []
            self.row_data.clear()
            self.raw_text = ""
            self.friendly_text = ""
            self.loaded_ctrl = ctrl
            if not self.tree_mode:
                self.show_text("正在加载所选控制器的数据...")
        self._load_seq += 1
        seq = self._load_seq
        args = self.build_args(ctrl)
        self.info.config(text="加载中: storcli64 " + " ".join(args) + " J")

        def done(res):
            if ctrl != self.app.current_ctrl or seq != self._load_seq:
                return
            self.on_done(res)

        self.app.run_cmd(args + ["J"], done, timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def on_done(self, res):
        if not res.get("ok"):
            self.raw_text = f"[错误] {res.get('error', '')}"
            self.show_text(self.raw_text)
            self.show_mode(False)
            self.info.config(text="失败")
            return
        self.raw_text = res["stdout"]
        if res["stderr"].strip():
            self.raw_text += "\n--- stderr ---\n" + res["stderr"]
        tables = []
        status_text = ""
        try:
            payload = parse_json_output(res["stdout"])
            status_text, _desc = command_status(payload)
            tables = list(iter_tables(payload["Controllers"][0].get("Response Data", {})))
        except Exception:
            tables = []
        if tables:
            self.tables = tables
            self.sort_state = {}
            self.refresh_table_view()
            self.show_mode(True)
            rows = sum(len(r) for _t, _h, r in tables)
            self.last_status = f"{tr_status(status_text) or '成功'} · {res['elapsed']:.1f}s · {rows} 行"
            self.last_refresh = time.strftime("%H:%M:%S")
            self.info.config(text=f"{self.last_status} · {self.last_refresh}")
        else:
            desc = ""
            try:
                payload = parse_json_output(res["stdout"])
                desc = str(payload["Controllers"][0]["Command Status"].get("Description", ""))
            except Exception:
                desc = ""
            if desc and desc != "None":
                self.friendly_text = (f"状态: {tr_status(status_text) or '-'}\n说明: {tr_desc(desc)}\n\n"
                                      "该页当前没有数据。\n"
                                      "点右上「原始输出」可查看 storcli 原始返回。")
                self.show_text(self.friendly_text)
            else:
                self.friendly_text = ""
                self.show_text(self.raw_text)
            self.show_mode(False)
            brief = tr_desc(desc) if desc and desc != "None" else "无表格数据"
            self.last_refresh = time.strftime("%H:%M:%S")
            self.info.config(
                text=f"{tr_status(status_text) or '完成'} · {brief} · "
                     f"{res['elapsed']:.1f}s · {self.last_refresh}")

    def show_tables(self, tables):
        self.headers = render_tables(self.tree, tables, row_data=self.row_data,
                                     heading_cmd=lambda hh: (lambda: self.sort_by(hh)))
        for header in self.headers:
            ascending = self.sort_state.get(header)
            suffix = " ▲" if ascending is True else " ▼" if ascending is False else ""
            self.tree.heading(
                header, text=tr_header(header) + suffix,
                command=lambda hh=header: self.sort_by(hh))
        self.selection_label.config(text=f"显示 {sum(len(r) for _t, _h, r in tables)} 行 · 未选择")
        self.app.update_data_action_state(self)

    def row_state(self, row):
        for key, value in row.items():
            if "state" in str(key).lower() or "status" in str(key).lower():
                return str(value)
        return ""

    def row_matches(self, title, row):
        query = self.filter_var.get().strip().lower()
        searchable = " ".join(
            [str(title)]
            + [f"{tr_header(str(key))} {fmt_cell(value)}" for key, value in row.items()]
        ).lower()
        if query and query not in searchable:
            return False
        selected_filter = self.state_filter_var.get()
        if selected_filter == "全部":
            return True
        state = self.row_state(row)
        low = state.lower()
        tag = tag_for_state(state)
        if selected_filter == "异常":
            return tag == "red" or any(word in low for word in
                                      ("dgd", "dgrd", "degraded", "failed", "missing", "offln"))
        if selected_filter == "正常":
            return tag == "green" or any(word in low for word in
                                        ("optimal", "optl", "online", "onln", "good", "ok"))
        if selected_filter == "在线":
            return "onln" in low or "online" in low
        if selected_filter == "离线":
            return "offln" in low or "offline" in low
        if selected_filter == "未配置":
            return any(word in low for word in ("ugood", "ubad", "unconfigured"))
        if selected_filter == "热备":
            return any(word in low for word in ("ghs", "dhs", "hsp", "hot spare"))
        if selected_filter == "重建/初始化":
            return tag == "orange" or any(word in low for word in
                                         ("rbld", "rebuild", "init", "copyback"))
        return True

    def refresh_table_view(self):
        if not self.tables:
            return
        tables = self.visible_tables()
        self.show_tables(tables)
        total = sum(len(rows) for _title, _headers, rows in self.tables)
        shown = sum(len(rows) for _title, _headers, rows in tables)
        text = f"显示 {shown}/{total} 行 · 未选择"
        if not shown:
            text = f"没有匹配数据 · 共 {total} 行"
        self.selection_label.config(text=text)
        if self.last_status:
            self.info.config(
                text=f"{self.last_status}" +
                     (f" · {self.last_refresh}" if self.last_refresh else ""))

    def visible_tables(self):
        tables = []
        for title, headers, rows in self.tables:
            filtered = [row for row in rows if self.row_matches(title, row)]
            if filtered:
                tables.append((title, headers, filtered))
        return tables

    def export_table(self):
        if self.tree_mode and not self.tables:
            messagebox.showinfo(APP_TITLE, "当前没有可导出的表格数据。", parent=self.frame)
            return
        path = filedialog.asksaveasfilename(
            parent=self.frame, title="导出表格", defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            if path.lower().endswith(".csv"):
                with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["分组", "项目", "值"])
                    for title, _headers, rows in self.visible_tables():
                        for row in rows:
                            for key, value in row.items():
                                writer.writerow([tr_title(title), tr_header(str(key)),
                                                 tr_state(fmt_cell(value))])
            else:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.raw_text)
            self.info.config(
                text=f"已导出 {os.path.basename(path)} · {time.strftime('%H:%M:%S')}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"导出失败: {exc}", parent=self.frame)

    def clear_filters(self):
        self.filter_var.set("")
        self.state_filter_var.set("全部")
        self.refresh_table_view()

    def on_selection_changed(self, _event=None):
        selection = self.tree.selection()
        row = self.row_data.get(selection[0]) if selection else None
        if row is None:
            self.selection_label.config(
                text=self.selection_label.cget("text").split(" · 选择:", 1)[0] + " · 未选择")
        else:
            state = tr_state(self.row_state(row))
            parts = []
            for key in ("EID:Slt", "DG/VD", "TYPE", "Model", "Name", "Size"):
                if key in row:
                    value = str(tr_state(fmt_cell(row[key]))).strip()
                    if len(value) > 28:
                        value = value[:25] + "..."
                    parts.append(value)
            if not parts:
                parts = [str(tr_state(fmt_cell(v)))[:28]
                         for _k, v in list(row.items())[:3]]
            if state:
                parts.append(state)
            self.selection_label.config(
                text=f"{self.selection_label.cget('text').split(' · 选择:', 1)[0]}"
                     f" · 选择: {' · '.join(parts)}")
        self.app.update_data_action_state(self)

    def state_tag(self, row):
        return row_state_tag(row)

    def sort_by(self, col):
        ascending = self.sort_state.get(col, True)
        self.sort_state[col] = not ascending
        reverse = not ascending

        def key(row):
            v = str(row.get(col, "")).strip()
            if re.fullmatch(r"[\d.]+", v):
                return (0, float(v))
            return (1, v.lower())

        self.tables = [(t, h, sorted(rows, key=key, reverse=reverse))
                       for t, h, rows in self.tables]
        self.refresh_table_view()

    def show_mode(self, tree):
        self.tree_mode = tree
        if tree:
            self.text_frame.pack_forget()
            self.tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.mode_btn.config(text="原始输出")
        else:
            self.tree_frame.pack_forget()
            self.text_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.mode_btn.config(text="表格视图")

    def show_text(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("end", content)

    def toggle_mode(self):
        if self.tree_mode:
            self.show_text(self.raw_text)
            self.show_mode(False)
        elif self.tables:
            self.show_mode(True)
        elif self.friendly_text:
            current = self.text.get("1.0", "end-1c")
            self.show_text(self.raw_text if current == self.friendly_text else self.friendly_text)

    def selected_dict(self):
        if self.loaded_ctrl != self.app.current_ctrl:
            messagebox.showinfo(APP_TITLE, "当前表格不属于已选择的控制器，请刷新后再操作。",
                                parent=self.frame)
            return None
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "请先在列表中选择一行数据。", parent=self.frame)
            return None
        row = self.row_data.get(sel[0])
        if row is None:
            messagebox.showinfo(APP_TITLE, "请选择数据行(不是分组标题行)。", parent=self.frame)
            return None
        return row


class EventsTab:
    SEVERITIES = ("全部", "严重", "警告", "信息")

    def __init__(self, parent, app):
        self.app = app
        self._load_seq = 0
        self.loaded_ctrl = None
        self.rows = []
        self.raw_text = ""
        self.tree_mode = True
        self.frame = ttk.Frame(parent)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=(6, 3))
        ttk.Label(bar, text="最近").pack(side="left")
        self.count_var = tk.StringVar(value="50")
        ttk.Spinbox(bar, from_=10, to=2000, textvariable=self.count_var, width=6).pack(side="left", padx=4)
        ttk.Button(bar, text="查询事件", command=self.load).pack(side="left", padx=4)
        ttk.Button(bar, text="TTY 日志", command=self.load_tty).pack(side="left", padx=4)
        ttk.Button(bar, text="导出...", command=self.save_log).pack(side="left", padx=4)
        self.info = ttk.Label(bar, text="", font=UI_FONT)
        self.info.pack(side="left", padx=10)
        self.view_btn = ttk.Button(bar, text="原始日志", command=self.toggle_mode, width=10)
        self.view_btn.pack(side="right")

        filter_bar = ttk.Frame(self.frame)
        filter_bar.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(filter_bar, text="搜索:").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(filter_bar, textvariable=self.filter_var, width=32).pack(
            side="left", padx=(4, 8))
        ttk.Label(filter_bar, text="级别:").pack(side="left")
        self.severity_var = tk.StringVar(value="全部")
        severity = ttk.Combobox(
            filter_bar, textvariable=self.severity_var, values=self.SEVERITIES,
            state="readonly", width=8)
        severity.pack(side="left", padx=4)
        ttk.Button(filter_bar, text="清空", command=self.clear_filters, width=6).pack(
            side="left", padx=4)
        self.count_label = ttk.Label(filter_bar, text="", font=UI_FONT)
        self.count_label.pack(side="left", padx=8)

        self.tree_frame = ttk.Frame(self.frame)
        self.tree = ttk.Treeview(
            self.tree_frame, show="headings",
            columns=("time", "severity", "object", "message"), selectmode="browse")
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.rowconfigure(0, weight=1)
        self.tree_frame.columnconfigure(0, weight=1)
        for key, label, width in (
                ("time", "时间", 180), ("severity", "级别", 70),
                ("object", "对象", 130), ("message", "事件描述", 680)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=60, anchor="w",
                             stretch=(key == "message"))
        self.tree.tag_configure("critical", foreground="#c62828")
        self.tree.tag_configure("warning", foreground="#b26a00")
        self.text_frame, self.text = build_text(self.frame)
        self.text_frame.pack_forget()
        self.tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.filter_var.trace_add("write", lambda *_: self.render_events())
        severity.bind("<<ComboboxSelected>>", lambda _e: self.render_events())

    def load(self):
        if self.app.current_ctrl is None:
            return
        try:
            count = max(1, int(self.count_var.get()))
        except ValueError:
            count = 50
        self._run([f"/c{self.app.current_ctrl}", "show", "events", f"type=latest={count}"],
                  raw_only=False)

    def load_tty(self):
        if self.app.current_ctrl is None:
            return
        self._run([f"/c{self.app.current_ctrl}", "show", "termlog"], raw_only=True)

    def _run(self, args, raw_only=False):
        ctrl = self.app.current_ctrl
        self.prepare_controller(ctrl)
        self._load_seq += 1
        seq = self._load_seq
        self.info.config(text="加载中...")

        def done(res):
            if ctrl != self.app.current_ctrl or seq != self._load_seq:
                return
            self.on_done(res, raw_only)

        self.app.run_cmd(args, done, timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def prepare_controller(self, ctrl):
        if self.loaded_ctrl == ctrl:
            return
        self.loaded_ctrl = ctrl
        self.rows = []
        self.raw_text = ""
        self.tree.delete(*self.tree.get_children())
        self.text.delete("1.0", "end")
        if ctrl is not None:
            self.text.insert("end", "控制器已切换，请重新查询事件日志。")

    def on_done(self, res, raw_only=False):
        if not res.get("ok"):
            self.raw_text = f"[错误] {res.get('error', '')}"
            self.show_text(self.raw_text)
            self.show_mode(False)
            self.info.config(text="失败")
            return
        self.raw_text = res.get("stdout", "") or ""
        if (res.get("stderr") or "").strip():
            self.raw_text += "\n--- stderr ---\n" + res["stderr"]
        self.rows = [] if raw_only else self.parse_events(self.raw_text)
        if self.rows:
            self.render_events()
            self.show_mode(True)
        else:
            self.show_text(self.raw_text or "(无输出)")
            self.show_mode(False)
        self.info.config(text=f"{res['elapsed']:.1f}s · {time.strftime('%H:%M:%S')}")

    @staticmethod
    def severity_for(text):
        low = text.lower()
        if any(word in low for word in
               ("critical", "fatal", "failed", "failure", "offline", "degraded",
                "missing", "bad", "error", "unrecoverable")):
            return "严重"
        if any(word in low for word in
               ("warning", "rebuild", "foreign", "predictive", "init", "degraded")):
            return "警告"
        return "信息"

    @staticmethod
    def object_for(text):
        patterns = (
            r"\b(?:PD|Drive)\s+(\d+:\d+)", r"\bEID[: ]\s*(\d+)[ /:]Slt\s*(\d+)",
            r"\bVD\s*(\d+)", r"\bDG\s*(\d+)", r"\bController\s*(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(0)
        return "-"

    def parse_events(self, text):
        rows = []
        try:
            payload = parse_json_output(text)
            data = payload["Controllers"][0].get("Response Data", {})
            for _title, headers, table_rows in iter_tables(data):
                for row in table_rows:
                    joined = " ".join(f"{k}={v}" for k, v in row.items())
                    time_value = next(
                        (str(v) for k, v in row.items()
                         if any(word in str(k).lower() for word in ("time", "date"))), "")
                    message = next(
                        (str(v) for k, v in row.items()
                         if any(word in str(k).lower() for word in
                                ("description", "event", "value", "message"))), joined)
                    rows.append((time_value, self.severity_for(message),
                                 self.object_for(message), message))
            if rows:
                return rows
        except Exception:
            pass
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "Event Description" in stripped:
                continue
            if re.match(
                    r"^(CLI Version|Operating system|Controller\s*=|"
                    r"Status\s*=|Description\s*=|[-=+]{3,})",
                    stripped, re.I):
                continue
            timestamp = ""
            message = stripped
            match = re.match(
                r"^(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2})\s+(.+)$",
                stripped)
            if match:
                timestamp, message = match.group(1), match.group(2)
            elif re.match(r"^\d{2}/\d{2}/\d{4}", stripped):
                parts = re.split(r"\s{2,}", stripped, maxsplit=1)
                timestamp = parts[0]
                message = parts[1] if len(parts) > 1 else stripped
            else:
                parts = [p.strip() for p in re.split(r"\s{2,}|\t+", stripped) if p.strip()]
                if len(parts) >= 3:
                    timestamp = parts[0]
                    message = " ".join(parts[1:])
            rows.append((timestamp, self.severity_for(message),
                         self.object_for(message), message))
        return rows

    def render_events(self):
        self.tree.delete(*self.tree.get_children())
        query = self.filter_var.get().strip().lower()
        severity = self.severity_var.get()
        shown = 0
        for time_value, level, obj, message in self.rows:
            text = " ".join((time_value, level, obj, message)).lower()
            if query and query not in text:
                continue
            if severity != "全部" and level != severity:
                continue
            tag = {"严重": "critical", "警告": "warning"}.get(level, "")
            self.tree.insert("", "end", values=(time_value, level, obj, message),
                             tags=(tag,) if tag else ())
            shown += 1
        self.count_label.config(text=f"显示 {shown}/{len(self.rows)} 条")

    def clear_filters(self):
        self.filter_var.set("")
        self.severity_var.set("全部")
        self.render_events()

    def show_text(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("end", content)

    def show_mode(self, tree):
        self.tree_mode = tree
        if tree:
            self.text_frame.pack_forget()
            self.tree_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.view_btn.config(text="原始日志")
        else:
            self.tree_frame.pack_forget()
            self.text_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.view_btn.config(text="表格视图")

    def toggle_mode(self):
        if self.tree_mode:
            self.show_text(self.raw_text or "(尚未查询事件)")
            self.show_mode(False)
        elif self.rows:
            self.render_events()
            self.show_mode(True)
        else:
            self.show_text(self.raw_text or "(尚未查询事件)")

    def save_log(self):
        if not self.raw_text:
            messagebox.showinfo(APP_TITLE, "当前没有可保存的日志。", parent=self.frame)
            return
        path = filedialog.asksaveasfilename(
            parent=self.frame, title="保存事件日志", defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.raw_text)
            self.info.config(text=f"已保存: {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"保存失败: {exc}", parent=self.frame)


class ConsoleTab:
    def __init__(self, parent, app):
        self.app = app
        self.history = []
        self.hist_idx = 0
        self.frame = ttk.Frame(parent)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Label(bar, text="storcli64", font=MONO_FONT).pack(side="left")
        self.entry = ttk.Entry(bar, font=MONO_FONT)
        self.entry.pack(side="left", fill="x", expand=True, padx=6)
        self.entry.bind("<Return>", lambda _e: self.run())
        self.entry.bind("<Up>", self.hist_prev)
        self.entry.bind("<Down>", self.hist_next)
        bind_context_menu(self.entry, lambda: [
            ("粘贴", lambda: self.entry.event_generate("<<Paste>>")),
            ("清空", lambda: self.entry.delete(0, "end"))])
        self.json_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="JSON", variable=self.json_var).pack(side="left")
        ttk.Button(bar, text="执行", command=self.run).pack(side="left", padx=(6, 0))
        self.text_frame, self.text = build_text(self.frame)
        self.append("直接输入 StorCLI 参数并回车执行, 例如:\n"
                    "  /call show\n"
                    "  /c0 show all\n"
                    "  /c0/eall/sall show\n"
                    "  help\n")

    def append(self, s):
        self.text.insert("end", s)
        self.text.see("end")

    def run(self):
        line = self.entry.get().strip()
        if not line:
            return
        if not self.app.require_operation_idle():
            return
        try:
            args = shlex.split(line, posix=False)
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, f"参数解析失败: {exc}", parent=self.frame)
            return
        if self.json_var.get():
            args.append("J")
        self.history.append(line)
        self.hist_idx = len(self.history)
        self.append(f"\n{'-' * 72}\nstorcli64 {line}\n{'-' * 72}\n")
        self.entry.delete(0, "end")
        self.app.run_cmd(args, self.on_done, timeout=DEFAULT_TIMEOUT)

    def on_done(self, res):
        if res.get("ok"):
            self.append(res["stdout"])
            if res["stderr"].strip():
                self.append("\n--- stderr ---\n" + res["stderr"])
        else:
            self.append(f"[错误] {res.get('error', '')}")
        self.append(f"\n({res.get('elapsed', 0):.1f}s)\n")

    def hist_prev(self, _e):
        if not self.history or self.hist_idx <= 0:
            return "break"
        self.hist_idx -= 1
        self.entry.delete(0, "end")
        self.entry.insert(0, self.history[self.hist_idx])
        return "break"

    def hist_next(self, _e):
        if not self.history or self.hist_idx >= len(self.history):
            return "break"
        self.hist_idx += 1
        self.entry.delete(0, "end")
        if self.hist_idx < len(self.history):
            self.entry.insert(0, self.history[self.hist_idx])
        return "break"


# ---------------------------------------------------------------- 创建 VD 对话框

class CreateVdDialog(tk.Toplevel):
    RAID_TYPES = ["RAID0", "RAID1", "RAID5", "RAID6", "RAID10", "RAID50", "RAID60"]
    MIN_DRIVES = {
        "RAID0": 1, "RAID1": 2, "RAID5": 3, "RAID6": 4,
        "RAID10": 4, "RAID50": 6, "RAID60": 8,
    }
    STRIP_SIZES = ["", "8", "16", "32", "64", "128", "256", "512", "1024"]
    WRITE_POLS = ["默认", "WB 回写", "WT 直写"]
    READ_POLS = ["默认", "RA 预读", "NORA 不预读"]
    IO_POLS = ["默认", "Direct 直读直写", "Cached 缓存"]
    PD_CACHE_POLS = ["默认", "启用", "禁用"]

    def __init__(self, app, drives, ctrl):
        super().__init__(app.root)
        self.app = app
        self.drives = drives
        self.ctrl = ctrl
        self.title(f"创建虚拟驱动器 - 控制器 {ctrl}")
        self.geometry("680x760")
        self.transient(app.root)
        form = ttk.Frame(self)
        form.pack(fill="x", padx=10, pady=8)
        ttk.Label(form, text="RAID 级别:").grid(row=0, column=0, sticky="e", pady=3)
        self.raid_var = tk.StringVar(value="RAID1")
        ttk.Combobox(form, textvariable=self.raid_var, values=self.RAID_TYPES,
                     state="readonly", width=10).grid(row=0, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="名称:").grid(row=1, column=0, sticky="e", pady=3)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var, width=14).grid(row=1, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="容量 (MB):").grid(row=2, column=0, sticky="e", pady=3)
        self.size_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.size_var, width=14).grid(row=2, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="留空 = 使用全部容量").grid(row=2, column=2, sticky="w", padx=4)
        ttk.Label(form, text="条带大小 (KB):").grid(row=3, column=0, sticky="e", pady=3)
        self.strip_var = tk.StringVar()
        ttk.Combobox(form, textvariable=self.strip_var, values=self.STRIP_SIZES,
                     width=10).grid(row=3, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="写策略:").grid(row=3, column=2, sticky="e", pady=3)
        self.wp_var = tk.StringVar(value="默认")
        ttk.Combobox(form, textvariable=self.wp_var, values=self.WRITE_POLS,
                     state="readonly", width=12).grid(row=3, column=3, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="读策略:").grid(row=4, column=0, sticky="e", pady=3)
        self.rp_var = tk.StringVar(value="默认")
        ttk.Combobox(form, textvariable=self.rp_var, values=self.READ_POLS,
                     state="readonly", width=12).grid(row=4, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="IO 策略:").grid(row=4, column=2, sticky="e", pady=3)
        self.io_var = tk.StringVar(value="默认")
        ttk.Combobox(form, textvariable=self.io_var, values=self.IO_POLS,
                     state="readonly", width=12).grid(row=4, column=3, sticky="w", padx=6, pady=3)
        ttk.Label(form, text="盘缓存:").grid(row=5, column=0, sticky="e", pady=3)
        self.pdc_var = tk.StringVar(value="默认")
        ttk.Combobox(form, textvariable=self.pdc_var, values=self.PD_CACHE_POLS,
                     state="readonly", width=12).grid(row=5, column=1, sticky="w", padx=6, pady=3)
        self.cbb_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="BBU 缺失时仍回写",
                        variable=self.cbb_var).grid(row=5, column=2, columnspan=2, sticky="w", padx=6, pady=3)
        self.noinit_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="跳过初始化 (noinit)",
                        variable=self.noinit_var).grid(row=6, column=2, columnspan=2, sticky="w", padx=6, pady=3)
        sel_hdr = ttk.Frame(form)
        sel_hdr.grid(row=7, column=0, columnspan=4, sticky="w", pady=(12, 2))
        ttk.Label(sel_hdr, text="可选物理盘(未配置-好), 勾选要使用的盘:").pack(side="left")
        ttk.Button(sel_hdr, text="全选", command=self.select_all, width=6).pack(side="left", padx=(8, 2))
        ttk.Button(sel_hdr, text="清空", command=self.select_none, width=6).pack(side="left")
        box_frame = ttk.Frame(form)
        box_frame.grid(row=8, column=0, columnspan=4, sticky="nsew", pady=2)
        self.canvas = tk.Canvas(
            box_frame, height=170, highlightthickness=0, background=CONTENT_BG)
        box_vsb = ttk.Scrollbar(box_frame, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win_id, width=e.width))
        self.canvas.configure(yscrollcommand=box_vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        box_vsb.pack(side="right", fill="y")
        self.vars = []
        if drives:
            for eid, slt, size, model, state in drives:
                var = tk.BooleanVar(value=False)
                self.vars.append(var)
                cb = tk.Checkbutton(self.inner,
                                    text=f"{eid}:{slt}    {size}    {tr_state(state)}    {model}",
                                    variable=var, command=self.update_preview, font=MONO_FONT,
                                    anchor="w")
                cb.pack(anchor="w", padx=4, pady=1)
                cb.bind("<MouseWheel>", self._on_wheel)
        else:
            ttk.Label(self.inner, text="(没有处于未配置(好)状态的物理盘)").pack(anchor="w", padx=4)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)
        self.preview_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.preview_var, font=MONO_FONT, foreground="#1565c0",
                  wraplength=600, justify="left").grid(row=9, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.validation_var = tk.StringVar(value="")
        self.validation_lbl = ttk.Label(
            form, textvariable=self.validation_var, wraplength=620, justify="left")
        self.validation_lbl.grid(row=10, column=0, columnspan=4, sticky="w", pady=(5, 0))
        self.capacity_var = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.capacity_var, foreground="#555",
                  wraplength=620, justify="left").grid(
                      row=11, column=0, columnspan=4, sticky="w", pady=(3, 0))
        self.raid_var.trace_add("write", lambda *_: self.update_preview())
        self.name_var.trace_add("write", lambda *_: self.update_preview())
        self.size_var.trace_add("write", lambda *_: self.update_preview())
        self.strip_var.trace_add("write", lambda *_: self.update_preview())
        self.wp_var.trace_add("write", lambda *_: self.update_preview())
        self.rp_var.trace_add("write", lambda *_: self.update_preview())
        self.io_var.trace_add("write", lambda *_: self.update_preview())
        self.pdc_var.trace_add("write", lambda *_: self.update_preview())
        self.cbb_var.trace_add("write", lambda *_: self.update_preview())
        self.noinit_var.trace_add("write", lambda *_: self.update_preview())
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="创建", command=self.submit).pack(side="right")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.update_preview()

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def select_all(self):
        for var in self.vars:
            var.set(True)
        self.update_preview()

    def select_none(self):
        for var in self.vars:
            var.set(False)
        self.update_preview()

    def selected_drives(self):
        return [d for d, var in zip(self.drives, self.vars) if var.get()]

    def estimate_capacity(self, raid, selected):
        sizes = [parse_size_bytes(drive[2]) for drive in selected]
        sizes = [size for size in sizes if size > 0]
        if not sizes:
            return 0, 0, 0
        minimum = min(sizes)
        maximum = max(sizes)
        count = len(sizes)
        if raid == "RAID0":
            usable = minimum * count
        elif raid == "RAID1":
            usable = minimum
        elif raid == "RAID5":
            usable = minimum * max(0, count - 1)
        elif raid == "RAID6":
            usable = minimum * max(0, count - 2)
        elif raid == "RAID10":
            usable = minimum * (count // 2)
        elif raid == "RAID50":
            usable = minimum * max(0, count - 2)
        elif raid == "RAID60":
            usable = minimum * max(0, count - 4)
        else:
            usable = minimum * count
        return usable, minimum, maximum

    def validate_selection(self, selected):
        raid = self.raid_var.get()
        errors = []
        warnings = []
        minimum_drives = self.MIN_DRIVES.get(raid, 1)
        if len(selected) < minimum_drives:
            errors.append(f"{raid} 至少需要 {minimum_drives} 块物理盘。")
        if raid in ("RAID10",) and len(selected) % 2:
            errors.append("RAID10 需要偶数块物理盘。")
        usable, minimum, maximum = self.estimate_capacity(raid, selected)
        if minimum and maximum > minimum * 1.01:
            warnings.append(
                f"所选磁盘容量不一致：最小 {fmt_size(minimum)}，最大 {fmt_size(maximum)}。")
        size_text = self.size_var.get().strip()
        if size_text:
            try:
                requested_mb = float(size_text)
                if requested_mb <= 0:
                    errors.append("VD 容量必须大于 0 MB。")
                elif usable and requested_mb * 1000 * 1000 > usable:
                    errors.append(
                        f"请求容量 {requested_mb:g} MB 超过预计可用容量 {fmt_size(usable)}。")
            except ValueError:
                errors.append("VD 容量必须是数字，单位为 MB。")
        name = self.name_var.get().strip()
        if len(name) > 15:
            warnings.append("VD 名称超过 15 个字符，部分控制器可能拒绝或截断。")
        self.capacity_var.set(
            f"已选 {len(selected)} 块 · 原始总容量 "
            f"{fmt_size(sum(parse_size_bytes(drive[2]) for drive in selected))}"
            f" · 预计可用约 {fmt_size(usable) if usable else '-'}")
        return errors, warnings

    def build_args(self):
        if not self.drives:
            return None, "没有可用物理盘。"
        sel = self.selected_drives()
        if not sel:
            return None, "请至少勾选一块物理盘。"
        errors, _warnings = self.validate_selection(sel)
        if errors:
            return None, " ".join(errors)
        drives = ",".join(f"{d[0]}:{d[1]}" for d in sel)
        raid = self.raid_var.get().lower().replace("raid", "r")
        args = [f"/c{self.ctrl}", "add", "vd", raid, f"drives={drives}"]
        name = self.name_var.get().strip()
        size = self.size_var.get().strip()
        strip = self.strip_var.get().strip()
        if name:
            args.append(f"name={name}")
        if size:
            args.append(f"size={size}")
        if strip:
            args.append(f"strip={strip}")
        wp = self.wp_var.get()
        if wp.startswith("WB"):
            args.append("wb")
        elif wp.startswith("WT"):
            args.append("wt")
        rp = self.rp_var.get()
        if rp.startswith("RA"):
            args.append("ra")
        elif rp.startswith("NORA"):
            args.append("nora")
        iop = self.io_var.get()
        if iop.startswith("Direct"):
            args.append("direct")
        elif iop.startswith("Cached"):
            args.append("cached")
        pdc = self.pdc_var.get()
        if pdc == "启用":
            args.append("pdcache=on")
        elif pdc == "禁用":
            args.append("pdcache=off")
        if self.cbb_var.get():
            args.append("cachedbadbbu")
        if self.noinit_var.get():
            args.append("noinit")
        return args, None

    def update_preview(self):
        selected = self.selected_drives()
        errors, warnings = self.validate_selection(selected)
        args, err = self.build_args()
        self.preview_var.set(("storcli64 " + " ".join(args)) if args else "")
        messages = errors or ([err] if err and err not in errors else [])
        if messages:
            self.validation_var.set("无法创建: " + " ".join(messages))
            self.validation_lbl.config(foreground=DANGER_COLOR)
        elif warnings:
            self.validation_var.set("注意: " + " ".join(warnings))
            self.validation_lbl.config(foreground="#b26a00")
        else:
            self.validation_var.set("配置检查通过")
            self.validation_lbl.config(foreground="#0a7d32")

    def submit(self):
        args, err = self.build_args()
        if err:
            messagebox.showinfo("创建虚拟驱动器", err, parent=self)
            return
        cmd = "storcli64 " + " ".join(args)
        if not messagebox.askyesno("创建虚拟驱动器",
                                   f"将执行:\n\n{cmd}\n\n确认创建虚拟驱动器?", parent=self):
            return
        self.app.run_exclusive_cmd(args, self.on_done, "创建虚拟驱动器",
                                   timeout=DEFAULT_TIMEOUT, ctrl=self.ctrl)

    def on_done(self, res):
        ok = self.app.report_action("创建虚拟驱动器", res)
        if ok:
            self.app.tab_vd.load()
            self.destroy()


def parse_size_bytes(text):
    m = re.match(r"^\s*([\d.]+)\s*(KB|MB|GB|TB|PB)", str(text), re.I)
    if not m:
        return 0
    val = float(m.group(1))
    mult = {"KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9,
            "TB": 10 ** 12, "PB": 10 ** 15}[m.group(2).upper()]
    return int(val * mult)


def fmt_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if num < 1000 or unit == "PB":
            return f"{int(num)} B" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1000.0
    return f"{num:.1f} PB"


class OverviewTab:
    """概览页: MSM 主界面风格的仪表盘 + 物理盘/背板表, 可切换原始输出."""

    STATE_COLORS_HEX = {"green": "#0a7d32", "red": "#c62828", "orange": "#b26a00"}

    def __init__(self, parent, app):
        self.app = app
        self.raw_text = ""
        self.tree_mode = True
        self.fw_build_time = ""
        self._rd = None
        self.loaded_ctrl = None
        self._load_seq = 0
        self.frame = ttk.Frame(parent)
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="刷新", command=self.load).pack(side="left")
        self.info = ttk.Label(bar, text="", font=UI_FONT)
        self.info.pack(side="left", padx=10)
        self.mode_btn = ttk.Button(bar, text="原始输出", command=self.toggle_mode, width=10)
        self.mode_btn.pack(side="right")

        self.dash = ttk.Frame(self.frame)
        self.dash.pack(fill="x", padx=6)
        for col in range(3):
            self.dash.columnconfigure(col, weight=1, uniform="dash")

        pf = ttk.LabelFrame(self.dash, text="属性")
        pf.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=(0, 6))
        self.prop_labels = {}
        for i, (key, text) in enumerate([
                ("status", "状态:"), ("encl", "背板:"), ("pd", "物理盘:"),
                ("dg", "磁盘组:"), ("vd", "虚拟盘:"),
                ("model", "型号:"), ("sn", "序列号:")]):
            ttk.Label(pf, text=text, font=UI_FONT).grid(row=i, column=0, sticky="w", padx=8, pady=1)
            lbl = ttk.Label(pf, text="-", font=UI_FONT)
            lbl.grid(row=i, column=1, sticky="w", padx=8, pady=1)
            self.prop_labels[key] = lbl
        pf.columnconfigure(1, weight=1)

        uf = ttk.LabelFrame(self.dash, text="容量使用")
        uf.grid(row=0, column=1, sticky="nsew", padx=3, pady=(0, 6))
        self.pie_canvas = tk.Canvas(
            uf, width=140, height=140, highlightthickness=0,
            background=WINDOW_BG)
        self.pie_canvas.pack(side="left", padx=6, pady=6)
        leg = ttk.Frame(uf)
        leg.pack(side="left", fill="y", padx=4, pady=6)
        self.cap_total_lbl = ttk.Label(leg, text="总容量: -", font=UI_FONT)
        self.cap_total_lbl.pack(anchor="w", pady=2)
        self.cap_cfg_lbl = ttk.Label(leg, text="已配置: -", font=UI_FONT, foreground="#1565c0")
        self.cap_cfg_lbl.pack(anchor="w", pady=2)
        self.cap_unc_lbl = ttk.Label(leg, text="未配置: -", font=UI_FONT, foreground="#607d8b")
        self.cap_unc_lbl.pack(anchor="w", pady=2)

        bf = ttk.LabelFrame(self.dash, text="后台操作")
        bf.grid(row=0, column=2, sticky="nsew", padx=(3, 0), pady=(0, 6))
        self.bg_vd_lbl = ttk.Label(bf, text="虚拟盘进行中操作: -", font=UI_FONT)
        self.bg_vd_lbl.pack(anchor="w", padx=10, pady=8)
        self.bg_pd_lbl = ttk.Label(bf, text="物理盘进行中操作: -", font=UI_FONT)
        self.bg_pd_lbl.pack(anchor="w", padx=10, pady=8)

        af = ttk.LabelFrame(self.dash, text="高级软件选项")
        af.grid(row=1, column=0, sticky="nsew", padx=(0, 3), pady=(0, 6))
        self.aso_text = tk.Text(
            af, height=5, font=MONO_FONT, wrap="word",
            borderwidth=0, highlightthickness=0, state="disabled",
            background=CONTENT_BG, foreground=TEXT_FG,
            selectbackground=SELECT_BG, selectforeground=SELECT_FG)
        self.aso_text.pack(fill="both", expand=True, padx=6, pady=4)

        xf = ttk.LabelFrame(self.dash, text="快捷操作")
        xf.grid(row=1, column=1, sticky="nsew", padx=3, pady=(0, 6))
        for i, (text, cmd) in enumerate([
                ("创建虚拟驱动器", self.app.create_vd),
                ("控制器固件更新...", self.app.ctrl_fw),
                ("物理盘固件更新...", self.app.pd_fw),
                ("关闭报警", self.app.op_alarm_off),
                ("重新扫描", self.app.op_rescan)]):
            ttk.Button(xf, text=text, command=cmd).grid(
                row=i, column=0, sticky="w", padx=8, pady=1)

        vf = ttk.LabelFrame(self.dash, text="固件版本信息")
        vf.grid(row=1, column=2, sticky="nsew", padx=(3, 0), pady=(0, 6))
        self.kv_tree = ttk.Treeview(vf, show="headings", columns=("item", "value"), height=6)
        kv_vsb = ttk.Scrollbar(vf, orient="vertical", command=self.kv_tree.yview)
        self.kv_tree.configure(yscrollcommand=kv_vsb.set)
        self.kv_tree.pack(side="left", fill="both", expand=True)
        kv_vsb.pack(side="right", fill="y")
        self.kv_tree.heading("item", text="项目")
        self.kv_tree.heading("value", text="值")
        self.kv_tree.column("item", width=140, anchor="w", stretch=False)
        self.kv_tree.column("value", width=260, anchor="w")

        self.tbl_wrap = ttk.LabelFrame(self.frame, text="物理盘 / 背板")
        self.tbl_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.tbl_tree = ttk.Treeview(self.tbl_wrap, show="headings")
        tbl_vsb = ttk.Scrollbar(self.tbl_wrap, orient="vertical", command=self.tbl_tree.yview)
        self.tbl_tree.configure(yscrollcommand=tbl_vsb.set)
        self.tbl_tree.pack(side="left", fill="both", expand=True)
        tbl_vsb.pack(side="right", fill="y")

        self.text_frame, self.text = build_text(self.frame)
        self.text_frame.pack_forget()

    def load(self):
        if self.app.current_ctrl is None:
            self.info.config(text="未选择控制器")
            return
        ctrl = self.app.current_ctrl
        if self.loaded_ctrl != ctrl:
            self.loaded_ctrl = ctrl
            self._rd = None
            self.raw_text = ""
            self.fw_build_time = ""
            self.tbl_tree.delete(*self.tbl_tree.get_children())
            self.tbl_tree.configure(columns=())
            self.kv_tree.delete(*self.kv_tree.get_children())
            for lbl in self.prop_labels.values():
                lbl.config(text="-", foreground="")
            self.cap_total_lbl.config(text="总容量: -")
            self.cap_cfg_lbl.config(text="已配置: -")
            self.cap_unc_lbl.config(text="未配置: -")
            self.bg_vd_lbl.config(text="虚拟盘进行中操作: -")
            self.bg_pd_lbl.config(text="物理盘进行中操作: -")
            self.aso_text.config(state="normal")
            self.aso_text.delete("1.0", "end")
            self.aso_text.config(state="disabled")
            self.draw_pie(0, 0)
            if not self.tree_mode:
                self.show_text("正在加载所选控制器的数据...")
        self._load_seq += 1
        seq = self._load_seq
        self.info.config(text="加载中...")
        self.app.run_cmd([f"/c{ctrl}", "show", "all", "J"],
                         lambda res: self._main_done(res, ctrl, seq),
                         timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def _main_done(self, res, ctrl, seq):
        if ctrl != self.app.current_ctrl or seq != self._load_seq:
            return
        self.on_done(res, ctrl, seq)

    def _run_aux(self, args, ctrl, seq, callback):
        def done(res):
            if ctrl != self.app.current_ctrl or seq != self._load_seq:
                return
            callback(res)
        self.app.run_cmd(args, done, timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def on_done(self, res, ctrl, seq):
        if not res.get("ok"):
            self.raw_text = f"[错误] {res.get('error', '')}"
            self.show_text(self.raw_text)
            self.show_mode(False)
            self.info.config(text="失败")
            return
        rd = {}
        status_text = ""
        try:
            payload = parse_json_output(res["stdout"])
            status_text, _d = command_status(payload)
            rd = payload["Controllers"][0].get("Response Data", {}) or {}
        except Exception:
            rd = {}
        if not isinstance(rd, dict) or not rd:
            self.raw_text = res["stdout"]
            self.show_text(self.raw_text)
            self.show_mode(False)
            self.info.config(text=f"{res['elapsed']:.1f}s")
            return
        self._rd = rd
        self.update_props(rd)
        self.update_usage(rd)
        self.update_bg_pd(rd)
        self.update_aso(rd)
        self.render_kv(rd)
        tables = []
        for key in ("PD LIST", "Enclosure LIST"):
            rows = rd.get(key)
            if isinstance(rows, list) and rows:
                headers = []
                for row in rows:
                    for hkey in row:
                        if hkey not in headers:
                            headers.append(hkey)
                tables.append((key, headers, rows))
        render_tables(self.tbl_tree, tables)
        self.show_mode(True)
        self.info.config(
            text=f"{tr_status(status_text) or '成功'} · {res['elapsed']:.1f}s · "
                 f"{time.strftime('%H:%M:%S')}")
        self._run_aux([f"/c{ctrl}", "show", "all"], ctrl, seq, self.on_raw)
        self._run_aux([f"/c{ctrl}", "show", "termlog"], ctrl, seq, self.on_termlog)
        self._run_aux([f"/c{ctrl}", "/vall", "show", "J"], ctrl, seq, self.on_vd)

    def update_props(self, rd):
        basics = rd.get("Basics")
        basics = basics if isinstance(basics, dict) else {}
        pds = rd.get("PD LIST")
        pds = pds if isinstance(pds, list) else []
        encls = rd.get("Enclosure LIST")
        encls = encls if isinstance(encls, list) else []
        dgs = set()
        for row in pds:
            dg = str(row.get("DG", "")).strip()
            if dg and dg not in ("-", "255"):
                dgs.add(dg)
        st = ""
        stsec = rd.get("Status")
        if isinstance(stsec, dict):
            st = str(stsec.get("Controller Status", ""))
        lbl = self.prop_labels["status"]
        lbl.config(text=tr_state(st) or "-")
        lbl.config(foreground=self.STATE_COLORS_HEX.get(tag_for_state(st), ""))
        self.prop_labels["encl"].config(text=str(len(encls)))
        self.prop_labels["pd"].config(text=str(len(pds)))
        self.prop_labels["dg"].config(text=str(len(dgs)))
        self.prop_labels["model"].config(text=str(basics.get("Model", "-")))
        self.prop_labels["sn"].config(text=str(basics.get("Serial Number", "-")))

    def update_usage(self, rd):
        pds = rd.get("PD LIST")
        pds = pds if isinstance(pds, list) else []
        total = cfg = 0
        for row in pds:
            size = parse_size_bytes(row.get("Size"))
            total += size
            low = str(row.get("State", "")).lower()
            if not (low.startswith("ugood") or low.startswith("ubad") or "jbod" in low):
                cfg += size
        unc = total - cfg
        self.cap_total_lbl.config(text=f"总容量: {fmt_size(total)}")
        self.cap_cfg_lbl.config(text=f"已配置: {fmt_size(cfg)}")
        self.cap_unc_lbl.config(text=f"未配置: {fmt_size(unc)}")
        self.draw_pie(cfg, unc)

    def draw_pie(self, cfg, unc):
        c = self.pie_canvas
        c.delete("all")
        total = cfg + unc
        x0, y0, x1, y1 = 8, 4, 132, 128
        if total <= 0:
            c.create_oval(x0, y0, x1, y1, fill="#cfd8dc", outline="")
            c.create_text(70, 134, text="无容量", font=UI_FONT)
            return
        c.create_oval(x0, y0, x1, y1, fill="#90a4ae", outline="")
        ext = 360.0 * cfg / total
        if ext > 0:
            c.create_arc(x0, y0, x1, y1, start=90, extent=-ext, fill="#1565c0", outline="")
        c.create_text(70, 134, text=f"已配置 {int(round(100.0 * cfg / total))}%", font=UI_FONT)

    def update_bg_pd(self, rd):
        pds = rd.get("PD LIST")
        pds = pds if isinstance(pds, list) else []
        busy = sum(1 for row in pds
                   if tag_for_state(str(row.get("State", ""))) == "orange")
        self.bg_pd_lbl.config(text=f"物理盘进行中操作 (重建/初始化等): {busy}")

    def on_vd(self, res):
        if not res.get("ok"):
            self.prop_labels["vd"].config(text="-")
            self.bg_vd_lbl.config(text="虚拟盘进行中操作: -")
            return
        try:
            payload = parse_json_output(res["stdout"])
            rd = payload["Controllers"][0].get("Response Data", {}) or {}
        except Exception:
            rd = {}
        vds = rd.get("VD LIST")
        if not isinstance(vds, list):
            vds = rd.get("Virtual Drives")
        vds = vds if isinstance(vds, list) else []
        self.prop_labels["vd"].config(text=str(len(vds)))
        busy = sum(1 for row in vds
                   if tag_for_state(str(row.get("State", ""))) == "orange")
        self.bg_vd_lbl.config(text=f"虚拟盘进行中操作 (初始化/回拷等): {busy}")

    def update_aso(self, rd):
        aso = rd.get("Advanced Software Option")
        lines = []
        if isinstance(aso, dict):
            aso = [aso]
        if isinstance(aso, list):
            for item in aso:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("Adv S/W Opt", "")).strip()
                rest = [str(v).strip() for k, v in item.items()
                        if k.strip() != "Adv S/W Opt" and str(v).strip()
                        and str(v).strip() != "-"]
                lines.append(f"{name}: {' '.join(rest)}" if rest else name)
        self.aso_text.config(state="normal")
        self.aso_text.delete("1.0", "end")
        self.aso_text.insert("end", "\n".join(lines) if lines else "(无)")
        self.aso_text.config(state="disabled")

    def render_kv(self, rd):
        self.kv_tree.delete(*self.kv_tree.get_children())
        data = rd.get("Version")
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (list, dict)):
                    continue
                self.kv_tree.insert("", "end", values=(tr_prop(key), tr_state(fmt_cell(value))))
            if self.fw_build_time:
                self.kv_tree.insert("", "end", values=("固件构建时间", self.fw_build_time))

    def on_termlog(self, res):
        try:
            import tempfile
            dump = os.path.join(tempfile.gettempdir(), "storcli_gui_termlog.txt")
            with open(dump, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(res.get("stdout", "") or "")
                if res.get("stderr"):
                    fh.write("\n--- stderr ---\n" + (res.get("stderr") or ""))
                if res.get("error"):
                    fh.write("\n--- error ---\n" + str(res.get("error")))
        except Exception:
            pass
        if not res.get("ok") or self._rd is None:
            return
        bt = parse_fw_build_time(res.get("stdout", "") or "")
        if bt and bt != self.fw_build_time:
            self.fw_build_time = bt
            self.render_kv(self._rd)

    def on_raw(self, res):
        if res.get("ok"):
            self.raw_text = res["stdout"]
            if res["stderr"].strip():
                self.raw_text += "\n--- stderr ---\n" + res["stderr"]
            if not self.tree_mode:
                self.show_text(self.raw_text)

    def show_mode(self, tree):
        self.tree_mode = tree
        if tree:
            self.text_frame.pack_forget()
            self.dash.pack(fill="x", padx=6)
            self.tbl_wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.mode_btn.config(text="原始输出")
        else:
            self.dash.pack_forget()
            self.tbl_wrap.pack_forget()
            self.text_frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
            self.mode_btn.config(text="表格视图")

    def show_text(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("end", content)

    def toggle_mode(self):
        if self.tree_mode:
            self.show_text(self.raw_text or "(尚未获取原始输出)")
            self.show_mode(False)
        else:
            self.show_mode(True)


class ControllerTab:
    """控制器详情页: 关键摘要、分层属性、搜索与原始 JSON."""

    SUMMARY_FIELDS = (
        ("model", "型号"),
        ("status", "控制器状态"),
        ("serial", "序列号"),
        ("firmware", "固件版本"),
        ("driver", "驱动版本"),
        ("resources", "连接资源"),
    )
    SUMMARY_LAYOUT = (
        (0, 0, 2),  # 型号跨两列
        (0, 2, 1),
        (0, 3, 1),
        (1, 0, 1),
        (1, 1, 1),
        (1, 2, 2),  # 连接资源跨两列
    )
    OVERVIEW_GROUPS = (
        ("基本信息", (
            ("controller_no", "控制器编号"),
            ("overview_model", "型号"),
            ("overview_serial", "序列号"),
            ("personality", "当前模式"),
            ("controller_time", "控制器时间"),
        )),
        ("固件与驱动", (
            ("fw_package", "固件包版本"),
            ("fw_version", "固件版本"),
            ("bios_version", "BIOS 版本"),
            ("driver_name", "驱动名称"),
            ("driver_version", "驱动版本"),
        )),
        ("硬件与缓存", (
            ("chip_revision", "芯片修订版"),
            ("onboard_memory", "板载内存"),
            ("flash_size", "Flash 容量"),
            ("nvram_size", "NVRAM 容量"),
            ("roc_temp", "ROC 温度"),
            ("controller_temp", "控制器温度"),
        )),
        ("资源与健康", (
            ("overview_status", "控制器状态"),
            ("overview_resources", "存储资源"),
            ("memory_correctable", "可纠正内存错误"),
            ("memory_uncorrectable", "不可纠正内存错误"),
            ("bbu_status", "BBU 状态"),
            ("cachevault_state", "CacheVault 状态"),
        )),
    )

    def __init__(self, parent, app):
        self.app = app
        self.loaded_ctrl = None
        self._load_seq = 0
        self.raw_text = ""
        self.records = []
        self.tree_mode = True
        self.frame = ttk.Frame(parent)

        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=6, pady=6)
        ttk.Button(bar, text="刷新", command=self.load).pack(side="left")
        self.filter_label = ttk.Label(bar, text="筛选:")
        self.filter_label.pack(side="left", padx=(10, 4))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(bar, textvariable=self.filter_var, width=24)
        self.filter_entry.pack(side="left")
        self.info = ttk.Label(bar, text="", font=UI_FONT)
        self.info.pack(side="left", padx=10)

        self.view_nb = ttk.Notebook(self.frame)
        self.view_nb.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.overview_page = ttk.Frame(self.view_nb)
        self.detail_page = ttk.Frame(self.view_nb)
        self.raw_page = ttk.Frame(self.view_nb)
        self.view_nb.add(self.overview_page, text="概览")
        self.view_nb.add(self.detail_page, text="详细属性")
        self.view_nb.add(self.raw_page, text="原始 JSON")
        self.view_nb.bind("<<NotebookTabChanged>>", self.on_view_changed)

        self.summary = ttk.Frame(self.overview_page)
        self.summary.pack(fill="x", padx=6, pady=6)
        self.summary_values = {}
        for col in range(4):
            self.summary.columnconfigure(col, weight=1, uniform="summary")
        for row in range(2):
            self.summary.rowconfigure(row, weight=1)
        for (key, label), (row, col, span) in zip(self.SUMMARY_FIELDS, self.SUMMARY_LAYOUT):
            card = ttk.LabelFrame(self.summary, text=label)
            card.grid(
                row=row, column=col, columnspan=span, sticky="nsew",
                padx=(0 if col == 0 else 3, 0), pady=(0 if row == 0 else 3, 0))
            value = ttk.Label(card, text="-",
                              font=(UI_FONT[0], UI_FONT[1] + 1, "bold"),
                              wraplength=300 if span == 2 else 140,
                              justify="left", anchor="w")
            value.pack(fill="x", padx=8, pady=(6, 8))
            self.summary_values[key] = value

        self.overview_wrap = ttk.LabelFrame(self.overview_page, text="系统概览")
        self.overview_wrap.pack(fill="x", padx=6, pady=(0, 6))
        self.overview_grid = ttk.Frame(self.overview_wrap)
        self.overview_grid.pack(fill="x", padx=4, pady=4)
        self.overview_grid.columnconfigure(0, weight=1, uniform="overview")
        self.overview_grid.columnconfigure(1, weight=1, uniform="overview")
        self.overview_values = {}
        for index, (title, fields) in enumerate(self.OVERVIEW_GROUPS):
            group = ttk.LabelFrame(self.overview_grid, text=title, padding=(6, 4))
            group.grid(row=index // 2, column=index % 2, sticky="nsew",
                       padx=(0 if index % 2 == 0 else 3, 0), pady=(0, 3))
            group.columnconfigure(1, weight=1)
            for row, (key, label_text) in enumerate(fields):
                ttk.Label(group, text=f"{label_text}:").grid(
                    row=row, column=0, sticky="nw", padx=(0, 8), pady=1)
                value = ttk.Label(group, text="-", wraplength=330, justify="left")
                value.grid(row=row, column=1, sticky="nw", pady=1)
                self.overview_values[key] = value

        self.detail_wrap = ttk.LabelFrame(self.detail_page, text="控制器详细属性")
        self.detail_wrap.pack(fill="both", expand=True, padx=6, pady=6)
        self.tree_frame = ttk.Frame(self.detail_wrap)
        self.tree = ttk.Treeview(
            self.tree_frame, show="tree headings", columns=("value",),
            selectmode="browse")
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree_frame.rowconfigure(0, weight=1)
        self.tree_frame.columnconfigure(0, weight=1)
        self.tree_frame.pack(fill="both", expand=True)
        self.tree.heading("#0", text="项目")
        self.tree.heading("value", text="值")
        self.tree.column("#0", width=380, minwidth=220, anchor="w")
        self.tree.column("value", width=700, minwidth=260, anchor="w", stretch=True)
        self.tree.tag_configure("section", font=(UI_FONT[0], UI_FONT[1], "bold"),
                                foreground="#1565c0")
        self.tree.tag_configure("green", foreground="#0a7d32")
        self.tree.tag_configure("red", foreground="#c62828")
        self.tree.tag_configure("orange", foreground="#b26a00")

        raw_bar = ttk.Frame(self.raw_page)
        raw_bar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(raw_bar, text="另存为...", command=self.save_raw).pack(side="left")
        self.text_frame, self.text = build_text(self.raw_page)

        bind_context_menu(self.tree, lambda: [
            ("复制值", self.copy_selected),
            ("复制项目与值", self.copy_selected_pair),
            "-",
            ("全部展开", lambda: self.set_all_open(True)),
            ("全部折叠", lambda: self.set_all_open(False)),
        ])
        self.filter_var.trace_add("write", lambda *_: self.render_details())
        self.on_view_changed()

    def load(self):
        if self.app.current_ctrl is None:
            self.info.config(text="未选择控制器")
            return
        ctrl = self.app.current_ctrl
        if self.loaded_ctrl != ctrl:
            self.loaded_ctrl = ctrl
            self.raw_text = ""
            self.records = []
            self.tree.delete(*self.tree.get_children())
            self.view_nb.select(self.overview_page)
            for label in self.summary_values.values():
                label.config(text="-", foreground="")
            for label in self.overview_values.values():
                label.config(text="-", foreground="")
            if not self.tree_mode:
                self.show_text("正在加载所选控制器的数据...")
        self._load_seq += 1
        seq = self._load_seq
        self.info.config(text="加载中...")
        args = [f"/c{ctrl}", "show", "all", "J"]
        self.app.run_cmd(
            args, lambda res: self._on_result(res, ctrl, seq),
            timeout=DEFAULT_TIMEOUT, ctrl=ctrl)

    def on_view_changed(self, _event=None):
        try:
            detail_active = self.view_nb.index(self.view_nb.select()) == 1
        except Exception:
            detail_active = False
        state = "normal" if detail_active else "disabled"
        self.filter_entry.configure(state=state)
        self.filter_label.configure(foreground="" if detail_active else "#999")

    def _on_result(self, res, ctrl, seq):
        if ctrl != self.app.current_ctrl or seq != self._load_seq:
            return
        if not res.get("ok"):
            self.raw_text = f"[错误] {res.get('error', '')}"
            self.show_text(self.raw_text)
            self.view_nb.select(self.raw_page)
            self.info.config(text="读取失败")
            return
        self.raw_text = res.get("stdout", "") or ""
        if (res.get("stderr") or "").strip():
            self.raw_text += "\n--- stderr ---\n" + res["stderr"]
        payload = None
        status_text = ""
        rd = {}
        try:
            payload = parse_json_output(res["stdout"])
            status_text, _desc = command_status(payload)
            rd = payload["Controllers"][0].get("Response Data", {}) or {}
        except Exception:
            pass
        if not isinstance(rd, dict) or not rd:
            self.show_text(self.raw_text or "(无输出)")
            self.view_nb.select(self.raw_page)
            self.info.config(text=f"{tr_status(status_text) or '解析失败'} · {res['elapsed']:.1f}s")
            return
        self.records = self.collect_records(rd)
        self.update_summary(rd)
        self.update_overview(rd)
        self.render_details()
        if self.view_nb.index(self.view_nb.select()) == 2:
            self.show_text(self.raw_text)
        self.info.config(
            text=f"{tr_status(status_text) or '成功'} · {res['elapsed']:.1f}s · "
                 f"{len(self.records)} 项 · {time.strftime('%H:%M:%S')}")

    @staticmethod
    def find_first(node, names):
        wanted = {str(name).lower() for name in names}
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).strip().lower() in wanted and not isinstance(value, (dict, list)):
                    return value
            for value in node.values():
                found = ControllerTab.find_first(value, names)
                if found not in (None, ""):
                    return found
        elif isinstance(node, list):
            for value in node:
                found = ControllerTab.find_first(value, names)
                if found not in (None, ""):
                    return found
        return None

    def collect_records(self, rd):
        records = []

        def walk(node, path):
            if not isinstance(node, dict):
                return
            for key, value in node.items():
                key_text = str(key)
                next_path = path + (self.section_label(key_text),)
                if isinstance(value, dict):
                    if value:
                        walk(value, next_path)
                    else:
                        records.append((next_path, "(空)", ""))
                elif isinstance(value, list):
                    if value and all(not isinstance(item, (dict, list)) for item in value):
                        shown = ", ".join(fmt_cell(item) for item in value)
                    else:
                        shown = f"共 {len(value)} 项"
                    records.append((path, key_text, shown))
                else:
                    records.append((path, key_text, fmt_cell(value)))

        walk(rd, ())
        return records

    @staticmethod
    def section_label(key):
        cleaned = clean_section_name(key)
        return CONTROLLER_SECTION_CN.get(
            cleaned, SECTION_CN.get(cleaned, TITLE_CN.get(cleaned, tr_controller_prop(cleaned))))

    def update_summary(self, rd):
        basics = rd.get("Basics")
        basics = basics if isinstance(basics, dict) else {}
        status = rd.get("Status")
        status = status if isinstance(status, dict) else {}
        version = rd.get("Version")
        version = version if isinstance(version, dict) else rd
        values = {
            "model": basics.get("Model") or rd.get("Product Name"),
            "status": status.get("Controller Status"),
            "serial": basics.get("Serial Number"),
            "firmware": self.find_first(version, (
                "Firmware Package Build", "Firmware Version", "Firmware Revision")),
            "driver": self.find_first(version, ("Driver Version",)),
        }
        counts = self.resource_counts(rd)
        values["resources"] = " · ".join(f"{short} {count}" for short, count in counts) if counts else "-"
        for key, value in values.items():
            shown = tr_state(fmt_cell(value)) if value not in (None, "") else "-"
            label = self.summary_values[key]
            label.config(text=shown)
            if key == "status":
                label.config(foreground={
                    "green": "#0a7d32", "red": "#c62828", "orange": "#b26a00",
                }.get(tag_for_state(str(value)), ""))

    @staticmethod
    def resource_counts(rd):
        specs = (
            ("PD", "PD LIST", "Physical Drives"),
            ("VD", "VD LIST", "Virtual Drives"),
            ("DG", "DG LIST", "Drive Groups"),
            ("背板", "Enclosure LIST", "Enclosures"),
            ("JBOD", "JBOD LIST", "JBOD Drives"),
        )
        counts = []
        for short, list_key, count_key in specs:
            value = rd.get(list_key)
            if isinstance(value, list):
                counts.append((short, len(value)))
                continue
            value = rd.get(count_key)
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                counts.append((short, int(value)))
        return counts

    def update_overview(self, rd):
        basics = rd.get("Basics")
        basics = basics if isinstance(basics, dict) else {}
        version = rd.get("Version")
        version = version if isinstance(version, dict) else {}
        status = rd.get("Status")
        status = status if isinstance(status, dict) else {}
        hwcfg = rd.get("HwCfg")
        hwcfg = hwcfg if isinstance(hwcfg, dict) else {}
        cachevault = rd.get("Cachevault_Info")
        if isinstance(cachevault, list) and cachevault and isinstance(cachevault[0], dict):
            cachevault = cachevault[0]
        cachevault = cachevault if isinstance(cachevault, dict) else {}
        counts = self.resource_counts(rd)
        values = {
            "controller_no": basics.get("Controller"),
            "overview_model": basics.get("Model") or rd.get("Product Name"),
            "overview_serial": basics.get("Serial Number"),
            "personality": status.get("Current Personality"),
            "controller_time": basics.get("Current Controller Date/Time"),
            "fw_package": version.get("Firmware Package Build") or version.get("FW Package Build"),
            "fw_version": version.get("Firmware Version") or version.get("FW Version"),
            "bios_version": version.get("Bios Version") or version.get("BIOS Version"),
            "driver_name": version.get("Driver Name"),
            "driver_version": version.get("Driver Version"),
            "chip_revision": hwcfg.get("ChipRevision"),
            "onboard_memory": hwcfg.get("On Board Memory Size"),
            "flash_size": hwcfg.get("Flash Size"),
            "nvram_size": hwcfg.get("NVRAM Size"),
            "roc_temp": hwcfg.get("ROC temperature(Degree Celsius)"),
            "controller_temp": hwcfg.get("Ctrl temperature(Degree Celsius)"),
            "overview_status": status.get("Controller Status"),
            "overview_resources": " · ".join(f"{short} {count}" for short, count in counts),
            "memory_correctable": status.get("Memory Correctable Errors"),
            "memory_uncorrectable": status.get("Memory Uncorrectable Errors"),
            "bbu_status": status.get("BBU Status") or hwcfg.get("BBU"),
            "cachevault_state": cachevault.get("State"),
        }
        colors = {"green": "#0a7d32", "red": "#c62828", "orange": "#b26a00"}
        for key, value in values.items():
            shown = tr_state(fmt_cell(value)) if value not in (None, "") else "-"
            label = self.overview_values[key]
            label.config(text=shown, foreground="")
            if key in ("overview_status", "bbu_status", "cachevault_state"):
                label.config(foreground=colors.get(tag_for_state(str(value)), ""))
            elif key.startswith("memory_"):
                try:
                    if int(value) > 0:
                        label.config(foreground=colors["red"])
                except (TypeError, ValueError):
                    pass

    def render_details(self):
        self.tree.delete(*self.tree.get_children())
        query = self.filter_var.get().strip().lower()
        displayed = 0
        section_nodes = {}
        for path, key, value in self.records:
            path_text = " > ".join(path)
            value_text = tr_state(fmt_cell(value))
            key_text = tr_controller_prop(str(key))
            if query and query not in " ".join(
                    (path_text, key_text, value_text)).lower():
                continue
            display_path = path or ("控制器属性",)
            parent = ""
            for depth in range(len(display_path)):
                partial = display_path[:depth + 1]
                node_id = section_nodes.get(partial)
                if node_id is None:
                    parent_path = partial[:-1]
                    parent = section_nodes.get(parent_path, "")
                    node_id = self.tree.insert(
                        parent, "end", text=partial[-1], values=("",),
                        tags=("section",), open=True)
                    section_nodes[partial] = node_id
                parent = node_id
            tag = tag_for_state(str(value))
            self.tree.insert(parent, "end", text=key_text, values=(value_text,),
                             tags=(tag,) if tag else ())
            displayed += 1
        if not displayed:
            self.tree.insert("", "end", text="(没有匹配的详细信息)" if query
                             else "(尚未获取详细信息)", values=("",))

    def copy_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        values = self.tree.item(selection[0], "values")
        self.frame.clipboard_clear()
        self.frame.clipboard_append(str(values[0]) if values else "")

    def copy_selected_pair(self):
        selection = self.tree.selection()
        if not selection:
            return
        item = self.tree.item(selection[0])
        values = item.get("values", ())
        text = f"{item.get('text', '')}: {values[0] if values else ''}"
        self.frame.clipboard_clear()
        self.frame.clipboard_append(text)

    def set_all_open(self, opened):
        for item in self.tree.get_children():
            self.tree.item(item, open=opened)
            for child in self.tree.get_children(item):
                self.tree.item(child, open=opened)
                for grandchild in self.tree.get_children(child):
                    self.tree.item(grandchild, open=opened)

    def show_text(self, content):
        self.text.delete("1.0", "end")
        self.text.insert("end", content)

    def save_raw(self):
        if not self.raw_text:
            messagebox.showinfo(APP_TITLE, "当前没有可保存的原始输出。", parent=self.frame)
            return
        path = filedialog.asksaveasfilename(
            parent=self.frame, title="保存控制器原始输出", defaultextension=".json",
            filetypes=[("JSON 文件", "*.json"), ("文本文件", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.raw_text)
            self.info.config(text=f"已保存: {os.path.basename(path)}")
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"保存失败: {exc}", parent=self.frame)

    def show_mode(self, tree):
        self.tree_mode = tree
        self.view_nb.select(self.detail_page if tree else self.raw_page)

    def toggle_mode(self):
        if self.tree_mode:
            self.show_text(self.raw_text or "(尚未获取原始输出)")
            self.show_mode(False)
        else:
            self.render_details()
            self.show_mode(True)


# ---------------------------------------------------------------- 固件更新

class CtrlFwDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.ctrl = app.current_ctrl
        self.title(f"控制器固件更新 - 控制器 {self.ctrl}")
        self.geometry("640x340")
        self.transient(app.root)
        model = ""
        for cid, m in app.controllers:
            if cid == self.ctrl:
                model = m
        ttk.Label(self, text=f"目标控制器: 控制器 {self.ctrl}    {model}\n"
                             "请务必确认固件文件与该型号匹配, 刷错固件可能变砖!",
                  foreground="#c62828", font=UI_FONT, justify="left").pack(fill="x", padx=10, pady=(10, 4))
        row1 = ttk.Frame(self)
        row1.pack(fill="x", padx=10, pady=4)
        ttk.Label(row1, text="固件文件:").pack(side="left")
        self.file_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.file_var, font=MONO_FONT).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row1, text="浏览...", command=self.browse).pack(side="left")
        opts = ttk.Frame(self)
        opts.pack(fill="x", padx=10, pady=4)
        self.nosig_var = tk.BooleanVar(value=False)
        self.reset_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="跳过签名校验 (nosigchk)", variable=self.nosig_var).pack(anchor="w")
        ttk.Checkbutton(opts, text="刷完立即重启控制器 (ResetNow)", variable=self.reset_var).pack(anchor="w")
        self.preview_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.preview_var, font=MONO_FONT, foreground="#1565c0",
                  wraplength=600, justify="left").pack(fill="x", padx=10, pady=6)
        for var in (self.file_var, self.nosig_var, self.reset_var):
            var.trace_add("write", lambda *_: self.update_preview())
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="开始更新", command=self.submit).pack(side="right")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=8)

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择控制器固件文件",
            filetypes=[("固件文件", "*.rom *.bin *.zip *.fw *.img"), ("所有文件", "*.*")])
        if path:
            self.file_var.set(path)

    def build_args(self):
        path = self.file_var.get().strip()
        if not path or not os.path.isfile(path):
            return None, "请先选择有效的固件文件。"
        args = [f"/c{self.ctrl}", "download", f"file={path}"]
        if self.nosig_var.get():
            args.append("nosigchk")
        if self.reset_var.get():
            args.append("ResetNow")
        return args, None

    def update_preview(self):
        args, _err = self.build_args()
        self.preview_var.set(("storcli64 " + " ".join(args)) if args else "")

    def submit(self):
        args, err = self.build_args()
        if err:
            messagebox.showinfo("控制器固件更新", err, parent=self)
            return
        if not messagebox.askyesno(
                "控制器固件更新",
                "警告: 刷固件是高风险操作, 刷写过程中断电或使用错误固件可能使卡变砖!\n\n"
                f"将执行:\nstorcli64 {' '.join(args)}\n\n确认继续?",
                icon="warning", parent=self):
            return
        if not messagebox.askyesno("控制器固件更新", "最后确认: 开始刷写控制器固件?",
                                   icon="warning", parent=self):
            return
        reset_now = self.reset_var.get()
        self.app.run_exclusive_cmd(
            args, lambda res: self.on_done(res, reset_now), "控制器固件更新",
            timeout=900, ctrl=self.ctrl)

    def on_done(self, res, reset_now):
        ok = self.app.report_action("控制器固件更新", res)
        if ok and not reset_now:
            messagebox.showinfo("控制器固件更新",
                                "固件刷写成功。新固件将在控制器重启后生效(重启主机即可)。",
                                parent=self)
        if ok:
            self.app.reload_tabs()
            self.destroy()


class PdFwDialog(tk.Toplevel):
    MODES = ["", "5", "7"]

    def __init__(self, app, drives, ctrl):
        super().__init__(app.root)
        self.app = app
        self.drives = drives
        self.ctrl = ctrl
        self.title(f"物理盘固件更新 - 控制器 {ctrl}")
        self.geometry("660x560")
        self.transient(app.root)
        ttk.Label(self, text="请确认固件文件与目标盘型号匹配; 更新期间不要断电或拔盘, 多块盘将逐块顺序更新。",
                  foreground="#c62828", font=UI_FONT, justify="left",
                  wraplength=620).pack(fill="x", padx=10, pady=(10, 4))
        row1 = ttk.Frame(self)
        row1.pack(fill="x", padx=10, pady=4)
        ttk.Label(row1, text="固件文件:").pack(side="left")
        self.file_var = tk.StringVar()
        ttk.Entry(row1, textvariable=self.file_var, font=MONO_FONT).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row1, text="浏览...", command=self.browse).pack(side="left")
        row2 = ttk.Frame(self)
        row2.pack(fill="x", padx=10, pady=2)
        ttk.Label(row2, text="模式:").pack(side="left")
        self.mode_var = tk.StringVar(value="")
        ttk.Combobox(row2, textvariable=self.mode_var, values=self.MODES, width=6).pack(side="left", padx=4)
        ttk.Label(row2, text="留空为默认, 5/7 为指定下载模式", font=UI_FONT).pack(side="left")
        sel_hdr = ttk.Frame(self)
        sel_hdr.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(sel_hdr, text="目标物理盘, 勾选要更新的盘:").pack(side="left")
        ttk.Button(sel_hdr, text="全选", command=self.select_all, width=6).pack(side="left", padx=(8, 2))
        ttk.Button(sel_hdr, text="清空", command=self.select_none, width=6).pack(side="left")
        box_frame = ttk.Frame(self)
        box_frame.pack(fill="both", expand=True, padx=10)
        self.canvas = tk.Canvas(
            box_frame, highlightthickness=0, background=CONTENT_BG)
        vsb = ttk.Scrollbar(box_frame, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._win_id, width=e.width))
        self.canvas.configure(yscrollcommand=vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.vars = []
        if drives:
            for eid, slt, size, model, state in drives:
                var = tk.BooleanVar(value=False)
                self.vars.append(var)
                cb = tk.Checkbutton(self.inner,
                                    text=f"{eid}:{slt}    {size}    {tr_state(state)}    {model}",
                                    variable=var, command=self.update_preview, font=MONO_FONT,
                                    anchor="w")
                cb.pack(anchor="w", padx=4, pady=1)
                cb.bind("<MouseWheel>", self._on_wheel)
        else:
            ttk.Label(self.inner, text="(没有物理盘)").pack(anchor="w", padx=4)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.inner.bind("<MouseWheel>", self._on_wheel)
        self.preview_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.preview_var, font=MONO_FONT, foreground="#1565c0",
                  wraplength=620, justify="left").pack(fill="x", padx=10, pady=6)
        self.file_var.trace_add("write", lambda *_: self.update_preview())
        self.mode_var.trace_add("write", lambda *_: self.update_preview())
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=8)
        ttk.Button(bar, text="开始更新", command=self.submit).pack(side="right")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=8)
        self.update_preview()

    def browse(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择物理盘固件文件",
            filetypes=[("固件文件", "*.bin *.rom *.fw *.img *.zip"), ("所有文件", "*.*")])
        if path:
            self.file_var.set(path)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def select_all(self):
        for var in self.vars:
            var.set(True)
        self.update_preview()

    def select_none(self):
        for var in self.vars:
            var.set(False)
        self.update_preview()

    def selected_drives(self):
        return [d for d, var in zip(self.drives, self.vars) if var.get()]

    def update_preview(self):
        path = self.file_var.get().strip()
        sel = self.selected_drives()
        if not path or not sel:
            self.preview_var.set("")
            return
        mode = f" mode={self.mode_var.get()}" if self.mode_var.get() else ""
        first = f"/c{self.ctrl}/e{sel[0][0]}/s{sel[0][1]} download src={path}{mode}"
        self.preview_var.set(f"storcli64 {first}" + (f"   …共 {len(sel)} 块盘, 顺序执行" if len(sel) > 1 else ""))

    def submit(self):
        path = self.file_var.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showinfo("物理盘固件更新", "请先选择有效的固件文件。", parent=self)
            return
        sel = self.selected_drives()
        if not sel:
            messagebox.showinfo("物理盘固件更新", "请至少选择一块物理盘。", parent=self)
            return
        if not messagebox.askyesno(
                "物理盘固件更新",
                "警告: 更新盘固件期间不要断电或拔盘!\n\n"
                f"目标盘: {', '.join(f'{e}:{s}' for e, s, _z, _m, _st in sel)}\n"
                f"固件文件: {path}\n\n确认开始?",
                icon="warning", parent=self):
            return
        if self.app.run_pd_fw(sel, path, self.mode_var.get().strip(), self.ctrl):
            self.destroy()


class StructuredWindow(tk.Toplevel):
    """结构化详情窗口: 关键信息表 + 明细表格, 可切换原始输出; 无结构化数据时回退纯文本."""

    def __init__(self, app, title, res, command=""):
        super().__init__(app.root)
        self.app = app
        self.title(f"{title} - {APP_TITLE}")
        self.geometry("980x680")
        self.tree_mode = True
        self.raw_text = res.get("stdout", "") or ""
        if (res.get("stderr") or "").strip():
            self.raw_text += "\n--- stderr ---\n" + res["stderr"]
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(top, text=f"storcli64 {command}", font=MONO_FONT).pack(anchor="w")
        self.mode_btn = ttk.Button(top, text="原始输出", command=self.toggle_mode, width=10)
        self.mode_btn.pack(side="right")
        rd = {}
        status_text = ""
        try:
            payload = parse_json_output(res.get("stdout", ""))
            status_text, _d = command_status(payload)
            rd = payload["Controllers"][0].get("Response Data", {}) or {}
        except Exception:
            rd = {}
        if not isinstance(rd, dict) or not rd:
            line = f"状态: {tr_status(status_text) or ('成功' if res.get('code') == 0 else '失败')}"
            ttk.Label(self, text=line, font=UI_FONT).pack(anchor="w", padx=10)
            self.text_frame, self.text = build_text(self)
            self.text.insert("end", self.raw_text or "(无输出)")
            return
        line = f"状态: {tr_status(status_text) or '成功'}"
        ttk.Label(self, text=line, font=UI_FONT).pack(anchor="w", padx=10, pady=(0, 2))
        self.trees_frame = ttk.Frame(self)
        kv_wrap = ttk.LabelFrame(self.trees_frame, text="关键信息")
        kv_wrap.pack(fill="both", expand=True, pady=(0, 4))
        self.kv_tree = ttk.Treeview(kv_wrap, show="headings", columns=("item", "value"), height=14)
        kv_vsb = ttk.Scrollbar(kv_wrap, orient="vertical", command=self.kv_tree.yview)
        self.kv_tree.configure(yscrollcommand=kv_vsb.set)
        self.kv_tree.pack(side="left", fill="both", expand=True)
        kv_vsb.pack(side="right", fill="y")
        self.kv_tree.heading("item", text="项目")
        self.kv_tree.heading("value", text="值")
        self.kv_tree.column("item", width=260, anchor="w", stretch=False)
        self.kv_tree.column("value", width=640, anchor="w")
        tbl_wrap = ttk.LabelFrame(self.trees_frame, text="明细表格")
        tbl_wrap.pack(fill="both", expand=True)
        self.tbl_tree = ttk.Treeview(tbl_wrap, show="headings")
        tbl_vsb = ttk.Scrollbar(tbl_wrap, orient="vertical", command=self.tbl_tree.yview)
        self.tbl_tree.configure(yscrollcommand=tbl_vsb.set)
        self.tbl_tree.pack(side="left", fill="both", expand=True)
        tbl_vsb.pack(side="right", fill="y")
        self.trees_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.text_frame, self.text = build_text(self)
        self.text_frame.pack_forget()
        self.kv_tree.delete(*self.kv_tree.get_children())

        def add_scalar(k, v):
            if isinstance(v, (list, dict)):
                return
            if isinstance(v, str) and len(v) > 120:
                return
            self.kv_tree.insert("", "end", values=(tr_prop(k), tr_state(fmt_cell(v))))

        def add_section(name):
            pretty = clean_section_name(name)
            self.kv_tree.insert("", "end",
                                values=(f"— {SECTION_CN.get(pretty, pretty)} —", ""),
                                tags=("section",))

        for key, value in rd.items():
            if isinstance(value, dict):
                add_section(key)
                for k2, v2 in value.items():
                    if isinstance(v2, dict):
                        add_section(k2)
                        for k3, v3 in v2.items():
                            add_scalar(k3, v3)
                    else:
                        add_scalar(k2, v2)
            elif isinstance(value, list):
                continue
            else:
                add_scalar(key, value)
        self.kv_tree.tag_configure("section", font=(UI_FONT[0], UI_FONT[1], "bold"),
                                   foreground="#1565c0")
        render_tables(self.tbl_tree, list(iter_tables(rd)))
        bind_context_menu(self.kv_tree, lambda: [
            ("复制值", self._copy_kv),
            ("复制行", lambda: self._copy_row(self.kv_tree))])
        bind_context_menu(self.tbl_tree, lambda: [("复制行", lambda: self._copy_row(self.tbl_tree))])

    def _copy_kv(self):
        sel = self.kv_tree.selection()
        if sel:
            self.clipboard_clear()
            self.clipboard_append(str(self.kv_tree.item(sel[0], "values")[1]))

    def _copy_row(self, tree):
        sel = tree.selection()
        if sel:
            self.clipboard_clear()
            self.clipboard_append("\t".join(str(v) for v in tree.item(sel[0], "values")))

    def show_mode(self, tree):
        self.tree_mode = tree
        if tree:
            self.text_frame.pack_forget()
            self.trees_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self.mode_btn.config(text="原始输出")
        else:
            self.trees_frame.pack_forget()
            self.text_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            self.mode_btn.config(text="表格视图")

    def toggle_mode(self):
        if self.tree_mode:
            self.text.delete("1.0", "end")
            self.text.insert("end", self.raw_text)
            self.show_mode(False)
        else:
            self.show_mode(True)


def show_structured(app, title, res, command=""):
    StructuredWindow(app, title, res, command)


class TaskProgressDialog(tk.Toplevel):
    """长时间后台任务进度与逐项结果."""

    def __init__(self, app, title, total):
        super().__init__(app.root)
        self.app = app
        self.title(f"{title} - {APP_TITLE}")
        self.geometry("820x520")
        self.minsize(680, 420)
        self.transient(app.root)
        self.total = max(1, int(total))
        self.completed = 0
        self.running = True
        self.results = []
        self.command_title = title
        self.protocol("WM_DELETE_WINDOW", self.close)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(10, 4))
        self.title_var = tk.StringVar(value=title)
        self.title_lbl = ttk.Label(
            top, textvariable=self.title_var,
            font=(UI_FONT[0], UI_FONT[1] + 2, "bold"))
        self.title_lbl.pack(anchor="w")
        self.step_var = tk.StringVar(value="准备执行...")
        ttk.Label(top, textvariable=self.step_var, font=UI_FONT).pack(
            anchor="w", pady=(4, 0))
        self.progress = ttk.Progressbar(
            self, mode="determinate", maximum=self.total, value=0)
        self.progress.pack(fill="x", padx=10, pady=(4, 8))

        wrap = ttk.LabelFrame(self, text="任务明细")
        wrap.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.tree = ttk.Treeview(
            wrap, show="headings",
            columns=("step", "target", "result", "elapsed", "description"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        for key, label, width in (
                ("step", "步骤", 60), ("target", "目标", 120),
                ("result", "结果", 80), ("elapsed", "耗时", 80),
                ("description", "说明", 420)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w",
                             stretch=(key == "description"))
        self.tree.tag_configure("success", foreground="#0a7d32")
        self.tree.tag_configure("failure", foreground="#c62828")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 10))
        self.output_btn = ttk.Button(
            bar, text="查看完整输出", command=self.show_output, state="disabled")
        self.output_btn.pack(side="left")
        self.close_btn = ttk.Button(
            bar, text="关闭", command=self.close, state="disabled")
        self.close_btn.pack(side="right")

    def update_step(self, index, label):
        self.step_var.set(f"正在处理 {index}/{self.total}: {label}")
        self.progress.configure(value=max(0, index - 1))

    def add_result(self, label, ok, desc, elapsed, res):
        self.completed += 1
        self.results.append((label, ok, desc, res))
        self.tree.insert(
            "", "end",
            values=(self.completed, label, "成功" if ok else "失败",
                    f"{elapsed:.1f}s", desc or "-"),
            tags=("success" if ok else "failure",))
        self.progress.configure(value=self.completed)

    def finish(self, all_ok):
        self.running = False
        self.progress.configure(value=self.total)
        self.step_var.set("任务完成" if all_ok else "任务完成，但存在失败项")
        self.title_var.set(
            self.command_title + (" - 成功" if all_ok else " - 有失败项"))
        self.title_lbl.config(
            foreground="#0a7d32" if all_ok else DANGER_COLOR)
        self.output_btn.config(state="normal")
        self.close_btn.config(state="normal")

    def close(self):
        if self.running:
            messagebox.showwarning(
                APP_TITLE, "任务仍在执行，请等待完成后再关闭进度窗口。", parent=self)
            return
        self.destroy()

    def show_output(self):
        if not self.results:
            return
        combined = "\n\n".join(
            (res.get("stdout", "") or "") for _label, _ok, _desc, res in self.results)
        all_ok = all(ok for _label, ok, _desc, _res in self.results)
        show_result_window(
            self.app, self.command_title,
            {"ok": all_ok, "stdout": combined, "stderr": "",
             "code": 0 if all_ok else 1, "elapsed": 0.0},
            "批量操作完整输出")


# ---------------------------------------------------------------- 主程序

class App:
    def __init__(self, root):
        self.root = root
        self.cmd_q = queue.Queue()
        self.result_q = queue.Queue()
        self.pending = 0
        self.request_seq = 0
        self.controller_refresh_seq = 0
        self.operation_active = False
        self.operation_title = ""
        self.auto_refresh_var = tk.BooleanVar(value=False)
        self.auto_refresh_seconds = tk.StringVar(value="30")
        self._auto_refresh_job = None
        self._window_was_minimized = False
        self._restore_redraw_job = None
        self.current_ctrl = None
        self.controllers = []
        self.last_path = None
        self.worker = Worker(self)
        self.worker.start()
        root.title(f"{APP_TITLE} v{APP_VERSION}")
        root.geometry("1320x840")
        root.minsize(1024, 640)
        root.configure(background=WINDOW_BG)
        root.option_add("*Background", WINDOW_BG)
        root.option_add("*Foreground", TEXT_FG)
        root.option_add("*selectBackground", SELECT_BG)
        root.option_add("*selectForeground", SELECT_FG)
        root.option_add("*Menu.background", CONTENT_BG)
        root.option_add("*Menu.foreground", TEXT_FG)
        root.option_add("*Menu.activeBackground", HOVER_BG)
        root.option_add("*Menu.activeForeground", TEXT_FG)
        root.option_add("*Listbox.selectBackground", HOVER_BG)
        root.option_add("*Listbox.selectForeground", TEXT_FG)
        root.option_add("*TCombobox*Listbox.background", CONTENT_BG)
        root.option_add("*TCombobox*Listbox.foreground", TEXT_FG)
        root.option_add("*TCombobox*Listbox.selectBackground", HOVER_BG)
        root.option_add("*TCombobox*Listbox.selectForeground", TEXT_FG)
        style = ttk.Style(root)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure(".", background=WINDOW_BG, foreground=TEXT_FG)
        style.configure("TFrame", background=WINDOW_BG)
        style.configure("TLabelframe", background=WINDOW_BG)
        style.configure("TLabelframe.Label", background=WINDOW_BG, foreground=TEXT_FG)
        style.configure("TLabel", font=UI_FONT, background=WINDOW_BG, foreground=TEXT_FG)
        style.configure("TButton", font=UI_FONT)
        style.configure("TEntry", fieldbackground=CONTENT_BG, foreground=TEXT_FG)
        style.configure("TCombobox", fieldbackground=CONTENT_BG,
                        background=CONTENT_BG, foreground=TEXT_FG)
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", CONTENT_BG)],
            foreground=[("readonly", TEXT_FG)])
        style.configure("TSpinbox", fieldbackground=CONTENT_BG, foreground=TEXT_FG)
        style.configure("Treeview", font=UI_FONT, rowheight=24,
                        background=CONTENT_BG, fieldbackground=CONTENT_BG,
                        foreground=TEXT_FG)
        style.map(
            "Treeview",
            background=[("selected", SELECT_BG)],
            foreground=[("selected", SELECT_FG)])
        style.configure("TNotebook", background=WINDOW_BG)
        style.configure("TNotebook.Tab", foreground=TEXT_FG)
        self.build_ui()
        self.install_window_paint_guard()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.bind("<F5>", self.on_f5)
        root.bind("<F1>", self.show_help)
        root.after(120, self.poll_results)
        self.refresh_controllers()
        self.schedule_auto_refresh()

    def install_window_paint_guard(self):
        self.root.update_idletasks()
        try:
            disabled = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                self.root.winfo_id(), 3, ctypes.byref(disabled), ctypes.sizeof(disabled))
        except Exception:
            pass
        self.root.bind("<Unmap>", self.on_root_unmap, add="+")
        self.root.bind("<Map>", self.on_root_map, add="+")
        self.root.bind("<Visibility>", self.on_root_visibility, add="+")

    def on_root_unmap(self, event):
        if event.widget is self.root:
            self.root.after_idle(self.mark_window_minimized)

    def mark_window_minimized(self):
        if self.root.state() == "iconic":
            self._window_was_minimized = True

    def on_root_map(self, event):
        if event.widget is not self.root or not self._window_was_minimized:
            return
        self._window_was_minimized = False
        if self._restore_redraw_job is not None:
            return
        self._restore_redraw_job = self.root.after_idle(self.redraw_after_restore)

    def on_root_visibility(self, event):
        if event.widget is self.root and self._window_was_minimized:
            self.on_root_map(event)

    def redraw_after_restore(self):
        self._restore_redraw_job = None
        if self.root.state() != "normal":
            return
        try:
            self.root.update_idletasks()
            flags = 0x0001 | 0x0004 | 0x0080 | 0x0100
            ctypes.windll.user32.RedrawWindow(
                self.root.winfo_id(), None, None, flags)
        except Exception:
            pass

    def build_ui(self):
        root = self.root
        self.status_var = tk.StringVar(value="就绪")
        statusbar = ttk.Frame(root)
        statusbar.pack(side="bottom", fill="x")
        ttk.Label(statusbar, textvariable=self.status_var, font=UI_FONT,
                  anchor="w").pack(side="left", padx=8, pady=3)
        ttk.Label(statusbar, text="F5 刷新当前页", font=UI_FONT,
                  foreground="#666").pack(side="right", padx=8)
        ttk.Spinbox(
            statusbar, from_=10, to=3600, width=6,
            textvariable=self.auto_refresh_seconds).pack(side="right", padx=(2, 0))
        ttk.Label(statusbar, text="秒", font=UI_FONT).pack(side="right")
        ttk.Checkbutton(
            statusbar, text="自动刷新", variable=self.auto_refresh_var,
            command=self.schedule_auto_refresh).pack(side="right", padx=(12, 2))
        topbar = ttk.Frame(root)
        topbar.pack(side="top", fill="x", padx=8, pady=(8, 2))
        ttk.Label(topbar, text="StorCLI:").pack(side="left")
        self.path_var = tk.StringVar(value=find_storcli())
        initial_path = self.path_var.get().strip()
        self.path_short_var = tk.StringVar(
            value=os.path.basename(initial_path) if initial_path else "未找到")
        ttk.Label(topbar, textvariable=self.path_short_var, font=MONO_FONT,
                  foreground="#555").pack(side="left", padx=(6, 8))
        ttk.Button(topbar, text="设置...", command=self.edit_storcli_path).pack(side="left")
        ttk.Button(topbar, text="打开目录", command=self.open_folder).pack(side="left", padx=(6, 0))
        ttk.Button(topbar, text="刷新控制器", command=self.refresh_controllers).pack(side="left", padx=(8, 0))
        ttk.Button(topbar, text="刷新全部", command=self.reload_tabs).pack(
            side="left", padx=(6, 0))
        if is_admin():
            ttk.Label(topbar, text="● 管理员", foreground="#0a7d32", font=UI_FONT).pack(side="left", padx=10)
        else:
            ttk.Label(topbar, text="● 非管理员, 多数操作将失败", foreground="#c62828",
                      font=UI_FONT).pack(side="left", padx=10)
            ttk.Button(topbar, text="以管理员身份重启", command=self.restart_elevated).pack(side="left")
        self.banner_raw = ""
        self.banner_frame = tk.Frame(root, background="#fff7e0")
        self.banner_lbl = tk.Label(
            self.banner_frame, text="", font=UI_FONT, foreground="#7a4b00",
            background="#fff7e0", wraplength=1080, justify="left",
            anchor="w", padx=8, pady=5)
        self.banner_detail_btn = tk.Button(
            self.banner_frame, text="查看详情", command=self.show_banner_detail,
            bg="#fff7e0", fg="#1565c0", relief="flat", font=UI_FONT)
        self.body = ttk.Frame(root)
        self.body.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.Frame(self.body, width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        ttk.Label(left, text="控制器列表", font=(UI_FONT[0], UI_FONT[1], "bold")).pack(anchor="w", pady=(2, 4))
        self.sidebar = ttk.Treeview(left, show="tree", selectmode="browse", height=14)
        self.sidebar.pack(fill="both", expand=True)
        self.sidebar.bind("<<TreeviewSelect>>", self.on_ctrl_select)
        self.ctrl_info_var = tk.StringVar(value="")
        ttk.Label(left, textvariable=self.ctrl_info_var, font=UI_FONT, wraplength=260,
                  justify="left").pack(anchor="w", pady=(6, 0))
        right = ttk.Frame(self.body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)
        self.tab_overview = OverviewTab(self.nb, self)
        self.tab_ctrl = ControllerTab(self.nb, self)
        self.tab_vd = DataTab(self.nb, self, lambda n: [f"/c{n}/vall", "show"], buttons=(
            ("详情", self.vd_details),
            ("初始化(快)", lambda: self.vd_init("fast"), "danger"),
            ("初始化(全)", lambda: self.vd_init("full"), "danger"),
            ("删除", self.vd_delete, "danger"),
            ("新建...", self.create_vd),
        ))
        self.tab_pd = DataTab(self.nb, self, lambda n: [f"/c{n}/eall/sall", "show"], buttons=(
            ("详情", self.pd_details),
            ("定位灯 开", self.pd_locate_on),
            ("定位灯 关", self.pd_locate_off),
            ("开始重建", self.pd_rebuild_start),
            ("停止重建", self.pd_rebuild_stop),
            ("置为正常 (Good)", self.pd_set_good, "danger"),
        ))
        self.tab_encl = DataTab(self.nb, self, lambda n: [f"/c{n}/eall", "show"], buttons=(
            ("详情", self.encl_details),
        ))
        self.tab_events = EventsTab(self.nb, self)
        self.tab_console = ConsoleTab(self.nb, self)
        self.tabs = [self.tab_overview, self.tab_ctrl, self.tab_vd,
                     self.tab_pd, self.tab_encl, self.tab_events, self.tab_console]
        self.nb.add(self.tab_overview.frame, text="  概览  ")
        self.nb.add(self.tab_ctrl.frame, text="  控制器  ")
        self.nb.add(self.tab_vd.frame, text="  虚拟盘  ")
        self.nb.add(self.tab_pd.frame, text="  物理盘  ")
        self.nb.add(self.tab_encl.frame, text="  背板  ")
        self.nb.add(self.tab_events.frame, text="  事件日志  ")
        self.nb.add(self.tab_console.frame, text="  命令控制台  ")
        bind_context_menu(self.sidebar, lambda: [
            ("刷新控制器", self.refresh_controllers),
            ("重新扫描", self.op_rescan),
            "-",
            ("开始巡检", self.op_patrol_start),
            ("停止巡检", self.op_patrol_stop),
            ("巡检状态", self.op_patrol_show),
            "-",
            ("查看外来配置", self.op_foreign_show),
            ("导入外来配置", self.op_foreign_import),
            ("删除外来配置", self.op_foreign_del),
            "-",
            ("BBU / CacheVault 信息", self.op_bbu),
            ("控制器固件更新...", self.ctrl_fw),
            ("报警状态", self.op_alarm_show),
            ("开启报警", self.op_alarm_on),
            ("关闭报警", self.op_alarm_off),
            "-",
            ("清除控制器全部配置 (危险!)", self.op_clear_config)])
        bind_context_menu(self.tab_overview.kv_tree, lambda: [
            ("复制值", self._copy_kv_value),
            ("复制行", lambda: self._copy_tree_row(self.tab_overview.kv_tree))])
        bind_context_menu(self.tab_overview.tbl_tree, lambda: [
            ("复制行", lambda: self._copy_tree_row(self.tab_overview.tbl_tree))])
        bind_context_menu(self.tab_vd.tree, lambda: [
            ("详情", self.vd_details),
            ("初始化(快)", lambda: self.vd_init("fast"), "danger"),
            ("初始化(全)", lambda: self.vd_init("full"), "danger"),
            ("删除...", self.vd_delete, "danger"),
            ("新建...", self.create_vd),
            "-",
            ("复制行", lambda: self._copy_tree_row(self.tab_vd.tree))])
        bind_context_menu(self.tab_pd.tree, lambda: [
            ("详情", self.pd_details),
            ("定位灯 开", self.pd_locate_on),
            ("定位灯 关", self.pd_locate_off),
            ("开始重建", self.pd_rebuild_start),
            ("停止重建", self.pd_rebuild_stop),
            ("置为在线 (Online)", self.pd_set_online),
            ("置为离线 (Offline)", self.pd_set_offline, "danger"),
            ("置为 Missing", self.pd_set_missing, "danger"),
            ("转为 JBOD", self.pd_set_jbod, "danger"),
            ("置为正常 (Good)", self.pd_set_good, "danger"),
            "-",
            ("添加热备盘", self.pd_add_hs),
            ("删除热备盘", self.pd_del_hs),
            "-",
            ("SMART 信息", self.pd_smart),
            ("错误计数", self.pd_errcnt),
            ("固件更新进度", self.pd_fw_status),
            ("固件更新...", self.pd_fw),
            "-",
            ("复制行", lambda: self._copy_tree_row(self.tab_pd.tree))])
        bind_context_menu(self.tab_encl.tree, lambda: [
            ("详情", self.encl_details),
            ("复制行", lambda: self._copy_tree_row(self.tab_encl.tree))])
        self.build_menu()

    def build_menu(self):
        menubar = tk.Menu(self.root)
        ops = tk.Menu(menubar, tearoff=0)
        ops.add_command(label="重新扫描", command=self.op_rescan)
        ops.add_separator()
        ops.add_command(label="开始巡检", command=self.op_patrol_start)
        ops.add_command(label="停止巡检", command=self.op_patrol_stop)
        ops.add_command(label="巡检状态", command=self.op_patrol_show)
        ops.add_separator()
        ops.add_command(label="查看外来配置", command=self.op_foreign_show)
        ops.add_command(label="导入外来配置", command=self.op_foreign_import, foreground=DANGER_COLOR)
        ops.add_command(label="删除外来配置", command=self.op_foreign_del, foreground=DANGER_COLOR)
        ops.add_separator()
        ops.add_command(label="BBU / CacheVault 信息", command=self.op_bbu)
        ops.add_command(label="控制器固件更新...", command=self.ctrl_fw)
        ops.add_command(label="报警状态", command=self.op_alarm_show)
        ops.add_command(label="开启报警", command=self.op_alarm_on)
        ops.add_command(label="关闭报警", command=self.op_alarm_off)
        ops.add_separator()
        ops.add_command(label="清除控制器全部配置 (危险!)", command=self.op_clear_config, foreground=DANGER_COLOR)
        menubar.add_cascade(label="控制器操作", menu=ops)
        pdm = tk.Menu(menubar, tearoff=0)
        pdm.add_command(label="详情", command=self.pd_details)
        pdm.add_command(label="定位灯 开", command=self.pd_locate_on)
        pdm.add_command(label="定位灯 关", command=self.pd_locate_off)
        pdm.add_command(label="开始重建", command=self.pd_rebuild_start)
        pdm.add_command(label="停止重建", command=self.pd_rebuild_stop)
        pdstate = tk.Menu(pdm, tearoff=0)
        pdstate.add_command(label="置为在线 (Online)", command=self.pd_set_online)
        pdstate.add_command(label="置为离线 (Offline)", command=self.pd_set_offline, foreground=DANGER_COLOR)
        pdstate.add_command(label="置为 Missing", command=self.pd_set_missing, foreground=DANGER_COLOR)
        pdstate.add_separator()
        pdstate.add_command(label="转为 JBOD", command=self.pd_set_jbod, foreground=DANGER_COLOR)
        pdstate.add_command(label="置为正常 (Good)", command=self.pd_set_good, foreground=DANGER_COLOR)
        pdm.add_cascade(label="状态设置", menu=pdstate)
        pdm.add_separator()
        pdm.add_command(label="添加热备盘", command=self.pd_add_hs)
        pdm.add_command(label="删除热备盘", command=self.pd_del_hs)
        pdm.add_separator()
        pdm.add_command(label="SMART 信息", command=self.pd_smart)
        pdm.add_command(label="错误计数", command=self.pd_errcnt)
        pdm.add_separator()
        pdm.add_command(label="固件更新...", command=self.pd_fw)
        pdm.add_command(label="固件更新进度", command=self.pd_fw_status)
        menubar.add_cascade(label="物理盘", menu=pdm)
        vdm = tk.Menu(menubar, tearoff=0)
        vdm.add_command(label="创建虚拟驱动器...", command=self.create_vd)
        vdm.add_command(label="虚拟驱动器详情", command=self.vd_details)
        vdm.add_command(label="删除虚拟驱动器...", command=self.vd_delete, foreground=DANGER_COLOR)
        menubar.add_cascade(label="虚拟驱动器", menu=vdm)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="使用帮助", command=self.show_help, accelerator="F1")
        helpm.add_command(label="打开 StorCLI 所在目录", command=self.open_folder)
        helpm.add_command(label="关于", command=self.about)
        menubar.add_cascade(label="帮助", menu=helpm)
        apply_danger_menu_colors(menubar)
        self.root.config(menu=menubar)

    # -- 命令执行

    @staticmethod
    def controller_from_args(args):
        for arg in list(args)[:2]:
            match = re.match(r"^/c(\d+)(?:/|$)", str(arg))
            if match:
                return int(match.group(1))
        return None

    def run_cmd(self, args, on_done, timeout=DEFAULT_TIMEOUT, ctrl=None):
        self.pending += 1
        self.request_seq += 1
        if ctrl is None:
            ctrl = self.controller_from_args(args)
        self.status_var.set(f"执行中: storcli64 {' '.join(args)}")
        self.root.config(cursor="watch")
        self.cmd_q.put((self.path_var.get().strip(), list(args), timeout, on_done,
                        ctrl, self.request_seq))

    def require_operation_idle(self):
        if not self.operation_active:
            return True
        messagebox.showwarning(
            APP_TITLE,
            f"操作正在进行: {self.operation_title}\n\n"
            "请等待当前操作结束，再执行新的阵列配置或固件操作。",
            parent=self.root)
        return False

    def begin_operation(self, title):
        if not self.require_operation_idle():
            return False
        self.operation_active = True
        self.operation_title = title
        self.status_var.set(f"操作进行中: {title}")
        return True

    def end_operation(self):
        self.operation_active = False
        self.operation_title = ""
        if self.pending == 0:
            self.status_var.set("就绪")

    def run_exclusive_cmd(self, args, on_done, title, timeout=DEFAULT_TIMEOUT, ctrl=None):
        if not self.begin_operation(title):
            return False

        def done(res):
            try:
                on_done(res)
            finally:
                self.end_operation()

        try:
            self.run_cmd(args, done, timeout=timeout, ctrl=ctrl)
        except Exception:
            self.end_operation()
            raise
        return True

    def poll_results(self):
        try:
            while True:
                res = self.result_q.get_nowait()
                self.pending = max(0, self.pending - 1)
                callback = res.pop("callback", None)
                try:
                    if callback:
                        callback(res)
                except Exception as exc:
                    messagebox.showerror(APP_TITLE, f"界面处理出错: {exc}", parent=self.root)
                if self.pending == 0:
                    self.status_var.set("就绪")
                    self.root.config(cursor="")
        except queue.Empty:
            pass
        self.root.after(120, self.poll_results)

    # -- 控制器发现

    def refresh_controllers(self):
        self.controller_refresh_seq += 1
        seq = self.controller_refresh_seq
        self.controllers = []
        self.current_ctrl = None
        self.sidebar.delete(*self.sidebar.get_children())
        self.ctrl_info_var.set("正在检测控制器...")
        self.banner(None)
        self.run_cmd(["show", "ctrlcount", "J"],
                     lambda res: self.on_ctrl_count(res, seq))

    def on_ctrl_count(self, res, seq):
        if seq != self.controller_refresh_seq:
            return
        count = None
        if res.get("ok"):
            try:
                payload = parse_json_output(res["stdout"])
                count = int(payload["Controllers"][0]["Response Data"]["Controller Count"])
            except Exception:
                m = re.search(r"Controller Count\s*=\s*(\d+)", res.get("stdout", ""))
                count = int(m.group(1)) if m else None
        self.ctrl_count = count or 0
        if count is None or count == 0:
            if not is_admin():
                msg = ("未检测到控制器。StorCLI 需要管理员权限，"
                       "请点击右上角「以管理员身份重启」。")
            elif res.get("ok"):
                msg = "未检测到 Broadcom / LSI 控制器。可展开详情查看 StorCLI 原始反馈。"
            else:
                msg = f"控制器检测失败: {res.get('error', '')}"
            detail = res.get("stdout", "") if res.get("ok") else res.get("error", "")
            self.banner(msg, detail)
            self.ctrl_info_var.set("未发现控制器")
            return
        self.run_cmd(["/call", "show", "J"],
                     lambda result: self.on_call_show(result, seq))

    def on_call_show(self, res, seq):
        if seq != self.controller_refresh_seq:
            return
        found = []
        if res.get("ok"):
            try:
                payload = parse_json_output(res["stdout"])
                for idx, entry in enumerate(payload.get("Controllers", [])):
                    if not isinstance(entry, dict):
                        continue
                    try:
                        cid = int(entry["Command Status"]["Controller"])
                    except Exception:
                        cid = idx
                    rd = entry.get("Response Data", {})
                    model = str(rd.get("Product Name", "")) if isinstance(rd, dict) else ""
                    found.append((cid, model))
            except Exception:
                pass
            if not found:
                try:
                    payload = parse_json_output(res["stdout"])
                    for _title, headers, rows in iter_tables(payload["Controllers"][0].get("Response Data", {})):
                        upper = [str(h).strip().upper() for h in headers]
                        if "CTL" in upper and "MODEL" in upper:
                            for row in rows:
                                cid = None
                                model = ""
                                for key, value in row.items():
                                    if str(key).strip().upper() == "CTL":
                                        m = re.search(r"\d+", str(value))
                                        cid = int(m.group(0)) if m else None
                                    if str(key).strip().upper() == "MODEL":
                                        model = str(value)
                                if cid is not None:
                                    found.append((cid, model))
                            break
                except Exception:
                    pass
        if not found:
            m = re.findall(r"Controller\s*=\s*(\d+)", res.get("stdout", "") or "")
            found = [(int(x), "") for x in dict.fromkeys(m)]
        if not found and getattr(self, "ctrl_count", 0):
            found = [(i, "") for i in range(self.ctrl_count)]
        if not found:
            self.banner("检测到控制器数量大于 0, 但无法解析列表。可在「命令控制台」执行 /call show 查看原始输出。")
            self.ctrl_info_var.set("")
            return
        self.controllers = found
        for cid, model in found:
            self.sidebar.insert("", "end", iid=f"c{cid}",
                                text=f"控制器 {cid}    {model}".strip())
        first = found[0][0]
        self.sidebar.selection_set(f"c{first}")
        self.sidebar.focus(f"c{first}")
        self.current_ctrl = first
        self.ctrl_info_var.set(f"共发现 {len(found)} 个控制器")
        self.reload_tabs()

    def on_ctrl_select(self, _event=None):
        sel = self.sidebar.selection()
        if not sel:
            return
        try:
            cid = int(sel[0][1:])
        except ValueError:
            return
        if cid == self.current_ctrl:
            return
        self.current_ctrl = cid
        self.reload_tabs()

    def reload_tabs(self):
        self.tab_events.prepare_controller(self.current_ctrl)
        for tab in (self.tab_overview, self.tab_ctrl, self.tab_vd,
                    self.tab_pd, self.tab_encl):
            tab.load()

    def schedule_auto_refresh(self):
        if self._auto_refresh_job is not None:
            try:
                self.root.after_cancel(self._auto_refresh_job)
            except Exception:
                pass
            self._auto_refresh_job = None
        if not self.auto_refresh_var.get():
            return
        try:
            seconds = max(10, int(self.auto_refresh_seconds.get()))
        except ValueError:
            seconds = 30
            self.auto_refresh_seconds.set("30")
        self._auto_refresh_job = self.root.after(seconds * 1000, self.run_auto_refresh)

    def run_auto_refresh(self):
        self._auto_refresh_job = None
        if not self.auto_refresh_var.get():
            return
        if (not self.operation_active and self.pending == 0
                and self.current_ctrl is not None):
            try:
                tab = self.tabs[self.nb.index(self.nb.select())]
                if hasattr(tab, "load"):
                    tab.load()
            except Exception:
                pass
        self.schedule_auto_refresh()

    def update_data_action_state(self, tab):
        selection = tab.tree.selection()
        row = tab.row_data.get(selection[0]) if selection else None
        state = str(tab.row_state(row)).lower() if row else ""
        enabled = {}
        if tab is self.tab_pd:
            enabled = {
                "详情": bool(row),
                "定位灯 开": bool(row),
                "定位灯 关": bool(row),
                "开始重建": bool(row) and not any(
                    word in state for word in ("rbld", "rebuild", "init")),
                "停止重建": bool(row) and (
                    "rbld" in state or "rebuild" in state
                    or tag_for_state(state) == "orange"),
                "置为正常 (Good)": bool(row) and any(
                    word in state for word in ("ubad", "jbod")),
            }
        elif tab is self.tab_vd:
            enabled = {
                "详情": bool(row),
                "初始化(快)": bool(row) and not any(
                    word in state for word in ("init", "rbld", "rebuild")),
                "初始化(全)": bool(row) and not any(
                    word in state for word in ("init", "rbld", "rebuild")),
                "删除": bool(row),
                "新建...": True,
            }
        elif tab is self.tab_encl:
            enabled = {"详情": bool(row)}
        for label, widget in tab.button_widgets.items():
            widget.configure(state="normal" if enabled.get(label, False) else "disabled")

    def tab_double_click(self, tab):
        if tab is self.tab_pd:
            self.pd_details()
        elif tab is self.tab_vd:
            self.vd_details()
        elif tab is self.tab_encl:
            self.encl_details()

    # -- 物理盘操作

    def pd_address(self):
        ctrl = self.tab_pd.loaded_ctrl
        if ctrl is None or ctrl != self.current_ctrl:
            messagebox.showerror(APP_TITLE, "当前物理盘表格不属于已选择的控制器，请刷新后重试。",
                                 parent=self.root)
            return None
        row = self.tab_pd.selected_dict()
        if row is None:
            return None
        eid = slt = None
        for key, value in row.items():
            k = str(key).strip().upper()
            if k in ("EID:SLT", "EID:SLOT"):
                m = re.match(r"\s*(\d+):(\d+)", str(value))
                if m:
                    return ctrl, m.group(1), m.group(2)
            if k == "EID":
                eid = str(value).strip()
            if k in ("SLT", "SLOT"):
                slt = str(value).strip()
        if eid and slt and eid.isdigit() and slt.isdigit():
            return ctrl, eid, slt
        messagebox.showerror(APP_TITLE, "无法从所选行解析出 Enclosure:Slot 信息。", parent=self.root)
        return None

    def pd_current_state(self):
        row = self.tab_pd.selected_dict()
        if not row:
            return None
        for key, value in row.items():
            if str(key).strip().lower() == "state":
                return str(value).strip()
        return None

    PD_STATE_REQUIRE = {
        "good": (["ubad", "jbod"], "未配置(坏) UBad / 直通 JBOD"),
        "jbod": (["ugood"], "未配置(好) UGood"),
        "online": (["offln"], "离线 Offln"),
        "offline": (["onln"], "在线 Onln"),
        "missing": (["onln", "offln"], "在线 Onln / 离线 Offln"),
    }

    def pd_check_state(self, op_key):
        need, label = self.PD_STATE_REQUIRE[op_key]
        state = self.pd_current_state()
        if not state:
            return True
        low = state.lower()
        if any(w in low for w in need):
            return True
        messagebox.showwarning(
            APP_TITLE,
            f"当前物理盘状态: {tr_state(state)}\n\n"
            f"此操作仅适用于状态为 {label} 的物理盘,\n"
            "storcli 会拒绝执行, 已阻止本次操作。",
            parent=self.root)
        return False

    def pd_details(self):
        addr = self.pd_address()
        if not addr:
            return
        ctrl, eid, slt = addr
        args = [f"/c{ctrl}/e{eid}/s{slt}", "show", "all", "J"]
        self.run_cmd(args, lambda res: show_structured(self, f"物理盘 {eid}:{slt} 详情", res, " ".join(args)),
                     ctrl=ctrl)

    def pd_locate_on(self):
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["start", "locate"], "点亮定位灯")

    def pd_locate_off(self):
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["stop", "locate"], "关闭定位灯")

    def pd_rebuild_start(self):
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["start", "rebuild"], "开始重建", confirm=True)

    def pd_rebuild_stop(self):
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["stop", "rebuild"], "停止重建", confirm=True)

    def pd_set_good(self):
        if not self.pd_check_state("good"):
            return
        addr = self.pd_address()
        if addr:
            state = (self.pd_current_state() or "").lower()
            force = "jbod" in state
            tail = ["set", "good"] + (["force"] if force else [])
            if force:
                note = "将物理盘标记为 Unconfigured(Good)。\n当前为 JBOD 状态, 需要 force 参数, 该盘数据将被永久删除!"
            else:
                note = "将物理盘标记为 Unconfigured(Good)。\n适用于未配置(坏) UBad 状态的盘。"
            self.pd_action(addr, tail, "置为未配置(好)", confirm=True, danger=True, note=note)

    def pd_set_online(self):
        if not self.pd_check_state("online"):
            return
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["set", "online"], "置为在线", confirm=True,
                           note="将物理盘置为在线 (Online)。\n仅适用于离线 Offln 状态的盘, 用于恢复被手动下线的磁盘。")

    def pd_set_offline(self):
        if not self.pd_check_state("offline"):
            return
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["set", "offline"], "置为离线", confirm=True, danger=True,
                           note="将物理盘置为离线 (Offline)。\n仅适用于在线 Onln 状态的盘; 若该盘是 RAID 成员, 对应虚拟盘将降级甚至失败!")

    def pd_set_missing(self):
        if not self.pd_check_state("missing"):
            return
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["set", "missing"], "置为 Missing", confirm=True, danger=True,
                           note="将物理盘标记为 Missing (视为已拔出)。\n关联的 RAID 可能因此降级!")

    def pd_set_jbod(self):
        if not self.pd_check_state("jbod"):
            return
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["set", "jbod"], "转为 JBOD", confirm=True, danger=True,
                           note="将物理盘转为 JBOD 直通模式。\n仅适用于未配置(好) UGood 状态的盘, 转换后由系统直接访问。")

    def pd_smart(self):
        addr = self.pd_address()
        if not addr:
            return
        ctrl, eid, slt = addr
        args = [f"/c{ctrl}/e{eid}/s{slt}", "show", "smart"]
        self.run_cmd(args, lambda res: show_result_window(self, f"物理盘 {eid}:{slt} SMART", res, " ".join(args)),
                     ctrl=ctrl)

    def pd_errcnt(self):
        addr = self.pd_address()
        if not addr:
            return
        ctrl, eid, slt = addr
        args = [f"/c{ctrl}/e{eid}/s{slt}", "show", "errorcounters"]
        self.run_cmd(args, lambda res: show_result_window(self, f"物理盘 {eid}:{slt} 错误计数", res, " ".join(args)),
                     ctrl=ctrl)

    def pd_add_hs(self):
        addr = self.pd_address()
        if not addr:
            return
        choice = messagebox.askyesnocancel(
            "添加热备盘",
            "是否将该盘添加为全局热备？\n\n"
            "「是」= 全局热备\n"
            "「否」= 指定磁盘组热备\n"
            "「取消」= 放弃操作",
            parent=self.root)
        if choice is None:
            return
        tail = ["add", "hotsparedrive"]
        note = "添加为全局热备，可供所有磁盘组使用。"
        if not choice:
            row = self.tab_pd.selected_dict()
            current_dg = str(row.get("DG", "")).strip() if row else ""
            if current_dg in ("-", "255"):
                current_dg = ""
            dgs = simpledialog.askstring(
                "指定磁盘组热备", "请输入目标磁盘组编号，多个编号用逗号分隔:",
                initialvalue=current_dg, parent=self.root)
            if dgs is None:
                return
            dgs = re.sub(r"\s+", "", dgs)
            if not dgs or not re.fullmatch(r"\d+(,\d+)*", dgs):
                messagebox.showerror(
                    APP_TITLE, "磁盘组编号格式无效，应类似 0 或 0,1。", parent=self.root)
                return
            tail.append(f"dgs={dgs}")
            note = f"添加为磁盘组 {dgs} 的专用热备。"
        self.pd_action(addr, tail, "添加热备盘", confirm=True, note=note)

    def pd_del_hs(self):
        addr = self.pd_address()
        if addr:
            self.pd_action(addr, ["delete", "hotsparedrive"], "删除热备盘", confirm=True)

    def pd_action(self, addr, tail, title, confirm=False, danger=False, note=""):
        ctrl, eid, slt = addr
        args = [f"/c{ctrl}/e{eid}/s{slt}"] + tail
        if confirm:
            prompt = f"将执行:\n\nstorcli64 {' '.join(args)}\n\n"
            if danger:
                head = f"警告 - 危险操作: {title}\n"
                head += (note if note else "可能影响现有配置或数据。") + "\n\n"
                prompt = head + prompt + "确认继续?"
            else:
                if note:
                    prompt = note + "\n\n" + prompt
                prompt += "确认继续?"
            if not messagebox.askyesno(APP_TITLE, prompt,
                                       icon="warning" if danger else "question",
                                       parent=self.root):
                return
        self.run_exclusive_cmd(args, lambda res: self.after_pd_action(res, title), title,
                               ctrl=ctrl)

    def after_pd_action(self, res, title):
        self.report_action(title, res)
        self.tab_pd.load()

    # -- 虚拟盘操作

    def vd_index(self):
        ctrl = self.tab_vd.loaded_ctrl
        if ctrl is None or ctrl != self.current_ctrl:
            messagebox.showerror(APP_TITLE, "当前虚拟盘表格不属于已选择的控制器，请刷新后重试。",
                                 parent=self.root)
            return None
        row = self.tab_vd.selected_dict()
        if row is None:
            return None
        for key, value in row.items():
            k = str(key).strip().upper()
            if k in ("VC", "VD"):
                m = re.search(r"\d+", str(value))
                if m:
                    return ctrl, int(m.group(0))
            if k in ("DG/VD", "DG/VDID"):
                m = re.search(r"\d+\s*/\s*(\d+)", str(value))
                if m:
                    return ctrl, int(m.group(1))
        messagebox.showerror(APP_TITLE, "无法从所选行解析出 VD 索引。", parent=self.root)
        return None

    def vd_details(self):
        target = self.vd_index()
        if target is None:
            return
        ctrl, idx = target
        args = [f"/c{ctrl}/v{idx}", "show", "all", "J"]
        self.run_cmd(args, lambda res: show_structured(self, f"虚拟盘 {idx} 详情", res, " ".join(args)),
                     ctrl=ctrl)

    def vd_init(self, mode):
        target = self.vd_index()
        if target is None:
            return
        ctrl, idx = target
        args = [f"/c{ctrl}/v{idx}", "start", "init"]
        if mode == "full":
            args.append("full")
        label = "快速初始化" if mode == "fast" else "完全初始化"
        danger = True
        prompt = f"将执行:\n\nstorcli64 {' '.join(args)}\n\n"
        if mode == "full":
            prompt = f"警告: 完全初始化会擦除该虚拟盘上的所有数据!\n\n{prompt}确认继续?"
        else:
            prompt = (f"警告: 快速初始化同样会破坏该虚拟盘上的现有数据!\n\n"
                      f"{prompt}确认继续?")
        if not messagebox.askyesno(APP_TITLE, prompt,
                                   icon="warning" if danger else "question", parent=self.root):
            return
        self.run_exclusive_cmd(args, lambda res: self.after_vd_action(res, label), label,
                               ctrl=ctrl)

    def vd_delete(self):
        target = self.vd_index()
        if target is None:
            return
        ctrl, idx = target
        choice = messagebox.askyesnocancel(
            APP_TITLE,
            f"警告: 删除虚拟盘 {idx} 将导致其上数据不可访问!\n\n"
            "是否在遇到主机 IO 挂起等情况时使用 force 强制删除?\n\n"
            "「是」= 带 force 删除   「否」= 普通删除   「取消」= 放弃操作",
            icon="warning", parent=self.root)
        if choice is None:
            return
        args = [f"/c{ctrl}/v{idx}", "del"]
        if choice:
            args.append("force")
        if not messagebox.askyesno(APP_TITLE,
                                   f"最后确认, 将执行:\n\nstorcli64 {' '.join(args)}\n\n确定删除虚拟盘 {idx}?",
                                   icon="warning", parent=self.root):
            return
        self.run_exclusive_cmd(args, lambda res: self.after_vd_action(res, f"删除虚拟盘 {idx}"),
                               f"删除虚拟盘 {idx}", ctrl=ctrl)

    def after_vd_action(self, res, title):
        self.report_action(title, res)
        self.tab_vd.load()

    def create_vd(self):
        if self.current_ctrl is None:
            messagebox.showinfo(APP_TITLE, "未选择控制器。", parent=self.root)
            return
        if not self.require_operation_idle():
            return
        ctrl = self.current_ctrl
        self.status_var.set("查询可用物理盘...")
        self.run_cmd(
            [f"/c{ctrl}/eall/sall", "show", "J"],
            lambda res: self.on_pd_list_for_vd(res, ctrl), ctrl=ctrl)

    def on_pd_list_for_vd(self, res, ctrl):
        if ctrl != self.current_ctrl:
            return
        drives = []
        if res.get("ok"):
            try:
                payload = parse_json_output(res["stdout"])
                drives = [d for d in parse_pd_rows(payload) if is_ugood(d[4])]
            except Exception:
                pass
        CreateVdDialog(self, drives, ctrl)

    # -- 固件更新

    def ctrl_fw(self):
        if self.current_ctrl is None:
            messagebox.showinfo(APP_TITLE, "未选择控制器。", parent=self.root)
            return
        if not self.require_operation_idle():
            return
        CtrlFwDialog(self)

    def pd_fw(self):
        if self.current_ctrl is None:
            messagebox.showinfo(APP_TITLE, "未选择控制器。", parent=self.root)
            return
        if not self.require_operation_idle():
            return
        ctrl = self.current_ctrl
        self.status_var.set("查询物理盘列表...")
        self.run_cmd(
            [f"/c{ctrl}/eall/sall", "show", "J"],
            lambda res: self.on_pd_list_for_fw(res, ctrl), ctrl=ctrl)

    def on_pd_list_for_fw(self, res, ctrl):
        if ctrl != self.current_ctrl:
            return
        drives = []
        if res.get("ok"):
            try:
                drives = parse_pd_rows(parse_json_output(res["stdout"]))
            except Exception:
                pass
        PdFwDialog(self, drives, ctrl)

    def run_pd_fw(self, drives, filepath, mode, ctrl):
        if not self.begin_operation("物理盘固件更新"):
            return False
        self._fw_queue = []
        self._fw_ctrl = ctrl
        for eid, slt, _size, _model, _state in drives:
            args = [f"/c{ctrl}/e{eid}/s{slt}", "download", f"src={filepath}"]
            if mode:
                args.append(f"mode={mode}")
            self._fw_queue.append((args, f"{eid}:{slt}"))
        self._fw_results = []
        self.task_dialog = TaskProgressDialog(self, "物理盘固件更新", len(drives))
        self._fw_next()
        return True

    def _fw_next(self):
        if not self._fw_queue:
            self._fw_done()
            return
        args, label = self._fw_queue.pop(0)
        if getattr(self, "task_dialog", None) and self.task_dialog.winfo_exists():
            self.task_dialog.update_step(
                len(self._fw_results) + 1,
                f"物理盘 {label}，共 {len(self._fw_results) + len(self._fw_queue) + 1} 块")
        self.run_cmd(
            args, lambda res, lbl=label: self._fw_step(res, lbl),
            timeout=900, ctrl=getattr(self, "_fw_ctrl", None))

    def _fw_step(self, res, label):
        ok, desc = self.summarize(res)
        self._fw_results.append((label, ok, desc, res))
        if getattr(self, "task_dialog", None) and self.task_dialog.winfo_exists():
            self.task_dialog.add_result(
                label, ok, desc, res.get("elapsed", 0.0), res)
        self._fw_next()

    def _fw_done(self):
        try:
            all_ok = bool(self._fw_results) and all(ok for _l, ok, _d, _r in self._fw_results)
            if getattr(self, "task_dialog", None) and self.task_dialog.winfo_exists():
                self.task_dialog.finish(all_ok)
        finally:
            self.end_operation()
        if self.current_ctrl == getattr(self, "_fw_ctrl", None):
            self.tab_pd.load()

    def pd_fw_status(self):
        addr = self.pd_address()
        if not addr:
            return
        ctrl, eid, slt = addr
        args = [f"/c{ctrl}/e{eid}/s{slt}", "download", "status"]
        self.run_cmd(args, lambda res: show_result_window(self, f"物理盘 {eid}:{slt} 固件更新进度", res, " ".join(args)),
                     ctrl=ctrl)

    # -- 背板操作

    def encl_details(self):
        ctrl = self.tab_encl.loaded_ctrl
        if ctrl is None or ctrl != self.current_ctrl:
            messagebox.showerror(APP_TITLE, "当前背板表格不属于已选择的控制器，请刷新后重试。",
                                 parent=self.root)
            return
        row = self.tab_encl.selected_dict()
        if row is None:
            return
        eid = None
        for key, value in row.items():
            if str(key).strip().upper() == "EID":
                m = re.search(r"\d+", str(value))
                if m:
                    eid = int(m.group(0))
        if eid is None:
            messagebox.showerror(APP_TITLE, "无法从所选行解析出 EID。", parent=self.root)
            return
        args = [f"/c{ctrl}/e{eid}", "show", "all", "J"]
        self.run_cmd(args, lambda res: show_structured(self, f"Enclosure {eid} 详情", res, " ".join(args)),
                     ctrl=ctrl)

    # -- 控制器操作(菜单栏与右键菜单共用)

    def op_rescan(self):
        self.op("重新扫描", lambda _n: ["/call", "rescan"], need_ctrl=False)

    def op_patrol_start(self):
        self.op("开始巡检", lambda n: [f"/c{n}", "start", "patrolread"], confirm=True, refresh=True)

    def op_patrol_stop(self):
        self.op("停止巡检", lambda n: [f"/c{n}", "stop", "patrolread"], confirm=True, refresh=True)

    def op_patrol_show(self):
        self.op("巡检状态", lambda n: [f"/c{n}", "show", "patrolread"])

    def op_foreign_show(self):
        self.op("外来配置", lambda n: [f"/c{n}/fall", "show"])

    def op_foreign_import(self):
        self.op("导入外来配置", lambda n: [f"/c{n}/fall", "import"], confirm=True, danger=True, refresh=True)

    def op_foreign_del(self):
        self.op("删除外来配置", lambda n: [f"/c{n}/fall", "del"], confirm=True, danger=True, refresh=True)

    def op_bbu(self):
        self.op("BBU / CacheVault", lambda n: [f"/c{n}/bbu", "show", "all"])

    def op_alarm_show(self):
        self.op("报警状态", lambda n: [f"/c{n}", "show", "alarm"])

    def op_alarm_on(self):
        self.op("开启报警", lambda n: [f"/c{n}", "set", "alarm=on"], refresh=True)

    def op_alarm_off(self):
        self.op("关闭报警", lambda n: [f"/c{n}", "set", "alarm=off"], refresh=True)

    def op_clear_config(self):
        self.op("清除控制器配置", lambda n: [f"/c{n}", "delete", "config"],
                confirm=True, danger=True, double_confirm=True, refresh=True)

    # -- 操作结果弹窗

    def summarize(self, res):
        if not res.get("ok"):
            return False, tr_desc(res.get("error", ""))
        status, desc = "", ""
        try:
            status, desc = command_status(parse_json_output(res["stdout"]))
        except Exception:
            status = extract_text_status(res.get("stdout", ""))
            m = re.search(r"^\s*Description\s*=\s*(.+)$", res.get("stdout", "") or "", re.M)
            desc = m.group(1).strip() if m else ""
        if not status:
            status = "Success" if res.get("code") == 0 else "Failure"
        return status == "Success", tr_desc(desc or "")

    def report_action(self, title, res):
        ok, desc = self.summarize(res)
        msg = f"{title}\n\n结果: {'成功' if ok else '失败'}"
        if desc and desc != "None":
            msg += f"\n说明: {desc}"
        if ok:
            messagebox.showinfo(APP_TITLE, msg, parent=self.root)
        else:
            messagebox.showerror(APP_TITLE, msg, parent=self.root)
        if messagebox.askyesno(APP_TITLE, "是否查看 storcli 完整输出?", parent=self.root):
            show_result_window(self, title, res, " ".join(res.get("args", [])))
        return ok

    # -- 菜单操作

    def op(self, title, build, confirm=False, danger=False, double_confirm=False, need_ctrl=True,
             refresh=False):
        if need_ctrl and self.current_ctrl is None:
            messagebox.showinfo(APP_TITLE, "未选择控制器。", parent=self.root)
            return
        args = build(self.current_ctrl if need_ctrl else 0)
        if confirm:
            prompt = f"将执行:\n\nstorcli64 {' '.join(args)}\n\n"
            if danger:
                prompt = f"警告 - 危险操作: {title}\n可能影响现有配置或数据。\n\n{prompt}确认继续?"
            else:
                prompt += "确认继续?"
            if not messagebox.askyesno(APP_TITLE, prompt,
                                       icon="warning" if danger else "question", parent=self.root):
                return
            if double_confirm and not messagebox.askyesno(
                    APP_TITLE, "再次确认: 此操作不可撤销。仍要继续?", icon="warning", parent=self.root):
                return
        def _done(res):
            self.report_action(title, res)
            if refresh:
                self.reload_tabs()

        if confirm or refresh:
            self.run_exclusive_cmd(args, _done, title,
                                   ctrl=self.controller_from_args(args))
        else:
            self.run_cmd(args, _done)

    # -- 杂项

    def banner(self, text, detail=""):
        self.banner_raw = detail or ""
        if text:
            self.banner_lbl.config(text=text)
            self.banner_lbl.pack(side="left", fill="x", expand=True)
            if self.banner_raw:
                self.banner_detail_btn.pack(side="right", padx=(4, 8), pady=4)
            else:
                self.banner_detail_btn.pack_forget()
            self.banner_frame.pack(side="top", fill="x", padx=8, pady=(2, 0),
                                   before=self.body)
        else:
            self.banner_frame.pack_forget()

    def show_banner_detail(self):
        if not self.banner_raw:
            return
        show_result_window(
            self, "控制器检测详情",
            {"ok": True, "stdout": self.banner_raw, "stderr": "",
             "code": 0, "elapsed": 0.0},
            "show ctrlcount J")

    def edit_storcli_path(self):
        win = tk.Toplevel(self.root)
        win.title("StorCLI 设置")
        win.geometry("720x170")
        win.transient(self.root)
        win.resizable(False, False)
        path_var = tk.StringVar(value=self.path_var.get())
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(body, text="StorCLI 可执行文件:").pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(4, 10))
        entry = ttk.Entry(row, textvariable=path_var, font=MONO_FONT)
        entry.pack(side="left", fill="x", expand=True)

        def choose():
            selected = filedialog.askopenfilename(
                parent=win, title="选择 StorCLI 可执行文件",
                initialdir=os.path.dirname(path_var.get()) if path_var.get() else base_dir(),
                filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
            if selected:
                path_var.set(selected)

        def apply():
            path = path_var.get().strip()
            if not path or not os.path.isfile(path):
                messagebox.showerror(APP_TITLE, "请选择有效的 StorCLI 可执行文件。", parent=win)
                return
            self.path_var.set(path)
            self.last_path = path
            self.path_short_var.set(os.path.basename(path))
            win.destroy()
            self.refresh_controllers()

        ttk.Button(row, text="浏览...", command=choose).pack(side="left", padx=(6, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="保存并刷新", command=apply).pack(side="right")
        ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right", padx=8)
        win.bind("<Return>", lambda _e: apply())
        win.bind("<Escape>", lambda _e: win.destroy())

    def browse_exe(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="选择 StorCLI 可执行文件",
            initialdir=(os.path.dirname(self.path_var.get()) if self.path_var.get().strip() else base_dir()),
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")])
        if path:
            self.path_var.set(path)
            self.path_short_var.set(os.path.basename(path))
            self.refresh_controllers()

    def on_path_change(self, _event=None):
        path = self.path_var.get().strip()
        if path and os.path.isfile(path) and path != self.last_path:
            self.last_path = path
            self.path_short_var.set(os.path.basename(path))
            self.refresh_controllers()

    def restart_elevated(self):
        if not self.require_operation_idle():
            return
        try:
            if getattr(sys, "frozen", False):
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, None, os.path.dirname(sys.executable), 1)
            else:
                script = os.path.abspath(__file__)
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", sys.executable, f'"{script}"', None, 1)
            if int(ret) > 32:
                self.root.destroy()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"提权重启失败: {exc}", parent=self.root)

    def open_folder(self):
        path = self.path_var.get().strip() or find_storcli()
        folder = os.path.dirname(path) if path else base_dir()
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def show_help(self, _event=None):
        top = tk.Toplevel(self.root)
        top.title("使用帮助")
        top.geometry("800x640")
        top.transient(self.root)
        apply_app_icon(top)
        bar = ttk.Frame(top)
        bar.pack(fill=tk.X, padx=10, pady=(10, 0))
        ttk.Label(bar, text=f"{APP_TITLE} v{APP_VERSION} 使用帮助",
                  font=(UI_FONT[0], UI_FONT[1] + 2, "bold"),
                  foreground="#1565c0").pack(side="left")
        body = ttk.Frame(top)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        scroll = ttk.Scrollbar(body)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        txt = tk.Text(
            body, wrap="word", font=(UI_FONT[0], UI_FONT[1] + 1),
            yscrollcommand=scroll.set, borderwidth=1, relief="solid",
            highlightthickness=0, padx=12, pady=10,
            background=CONTENT_BG, foreground=TEXT_FG,
            selectbackground=SELECT_BG, selectforeground=SELECT_FG)
        txt.pack(fill=tk.BOTH, expand=True)
        scroll.config(command=txt.yview)
        txt.tag_configure("h2", font=(UI_FONT[0], UI_FONT[1] + 1, "bold"),
                          foreground="#1565c0", spacing1=10, spacing3=3)
        txt.tag_configure("li", lmargin1=18, lmargin2=18, spacing1=1)
        txt.tag_configure("note", lmargin1=18, lmargin2=18, foreground="#c62828")
        content = [
            ("h2", "一、概述"),
            ("li", "· 本工具是 Broadcom MegaRAID StorCLI (storcli64.exe) 的图形化前端, 所有操作最终转换为 storcli 命令执行。"),
            ("li", "· 需以管理员权限运行 (exe 已内置 UAC 提权清单)。"),
            ("li", "· 顶部「设置...」可指定 storcli64.exe 位置；右下角可启用自动刷新并设置间隔。"),
            ("li", "· F1 打开本帮助, F5 刷新当前页面; 表格支持搜索、状态筛选、排序、导出和右键菜单。"),
            ("h2", "二、页面说明"),
            ("li", "· 概览: 仪表盘式展示控制器属性、容量使用、后台操作、高级软件选项、固件版本与构建时间、物理盘列表。"),
            ("li", "· 控制器: 包含「概览 / 详细属性 / 原始 JSON」子页；概览显示健康、固件、硬件和资源摘要，详细属性支持筛选。"),
            ("li", "· 虚拟盘: VD 列表; 支持搜索、状态筛选和 CSV 导出; 选中后可编辑/删除/查看详情。"),
            ("li", "· 物理盘: PD 列表; 右键可详情、定位灯、重建、状态设置、热备、SMART、错误计数、固件更新等。"),
            ("li", "· 背板: 背板 (Enclosure) 与槽位信息。"),
            ("li", "· 事件日志: 自动解析为时间、级别、对象和描述表格，支持严重/警告筛选、搜索、导出及原始日志切换。"),
            ("li", "· 命令控制台: 手动输入并执行任意 storcli 参数, 适合高级用户。"),
            ("h2", "三、常用操作"),
            ("li", "· 创建虚拟驱动器: 选择磁盘和 RAID 后会实时检查最低磁盘数、容量和请求大小，并显示预计可用容量。"),
            ("li", "· 删除虚拟驱动器: 选中 VD 后操作, 需二次确认, 数据不可恢复!"),
            ("li", "· PD 状态设置: 右键物理盘 → 状态设置, 支持 Online / Offline / Missing / JBOD / Good; 涉及数据丢失的操作会给出红色警告。"),
            ("li", "· 热备盘: 右键物理盘 → 添加热备盘 / 删除热备盘；支持全局热备和指定磁盘组热备。"),
            ("li", "· 定位灯: 右键物理盘 → 定位灯 开 / 关, 用于在机箱中识别硬盘位置。"),
            ("li", "· 固件更新: 物理盘批量固件更新会显示逐盘进度、当前目标、耗时和成功/失败结果。"),
            ("li", "· 外来配置: 控制器操作 → 查看 / 导入 / 删除外来配置, 用于迁移带旧 RAID 配置的磁盘。"),
            ("li", "· 巡检 (Patrol Read): 控制器操作 → 开始 / 停止巡检、巡检状态。"),
            ("li", "· BBU / CacheVault: 控制器操作 → BBU / CacheVault 信息, 查看电池/电容备份状态。"),
            ("li", "· 报警: 控制器操作 → 报警状态 / 开启报警 / 关闭报警。"),
            ("h2", "四、状态颜色"),
            ("li", "· 在线 (Onln) 显示为绿色; 故障 (Fault / Failed) 为红色; 重建 (Rebuild) 为橙色; 其余状态各有标识色。"),
            ("h2", "五、注意事项"),
            ("note", "· 标注 (危险!) 的操作会清除配置或销毁数据, 执行前请务必核对目标对象!"),
            ("li", "· 每个操作的完整 storcli 命令与原始输出都会显示在结果窗口, 便于排错。"),
            ("li", "· 若识别不到控制器: 确认以管理员运行、驱动已安装; 可经 帮助 → 打开 StorCLI 所在目录 检查程序是否存在。"),
            ("h2", "六、关于"),
            ("li", f"· {APP_TITLE} v{APP_VERSION}, Made By Windy He。"),
        ]
        for tag, line in content:
            txt.insert(tk.END, line + "\n", tag)
        txt.config(state="disabled")
        ttk.Button(top, text="关闭", command=top.destroy).pack(pady=(0, 10))
        top.bind("<Escape>", lambda _e: top.destroy())

    def about(self):
        exe = self.path_var.get().strip() or "(未找到)"
        messagebox.showinfo(
            "关于", f"{APP_TITLE} v{APP_VERSION}\n\nBroadcom MegaRAID StorCLI 的图形化前端。\n"
                    f"StorCLI: {exe}\nPython: {sys.version.split()[0]}\n\n"
                    "所有操作最终转换为 storcli 命令执行, 可在结果窗口中查看完整命令。\n"
                    "Made By Windy He",
            parent=self.root)

    def _copy_tree_row(self, tree):
        sel = tree.selection()
        if not sel:
            return
        vals = [str(v) for v in tree.item(sel[0], "values")]
        self.root.clipboard_clear()
        self.root.clipboard_append("\t".join(vals))

    def _copy_kv_value(self):
        sel = self.tab_overview.kv_tree.selection()
        if not sel:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(str(self.tab_overview.kv_tree.item(sel[0], "values")[1]))

    def on_f5(self, _event=None):
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            return
        tab = self.tabs[idx]
        if hasattr(tab, "load"):
            tab.load()

    def on_close(self):
        if self.operation_active:
            messagebox.showwarning(
                APP_TITLE,
                f"操作仍在进行: {self.operation_title}\n\n"
                "此时关闭界面不会安全地停止底层 storcli 子进程。\n"
                "请等待操作完成后再关闭。",
                parent=self.root)
            return
        self.cmd_q.put(None)
        self.root.destroy()


APP_ICON_B64 = "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"


def apply_app_icon(root):
    """为标题栏设置应用图标 (替换 Tk 默认羽毛图标)."""
    try:
        import base64
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "storcli_gui_app.ico")
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(APP_ICON_B64))
        root.iconbitmap(default=path)
    except Exception:
        pass


def main():
    if sys.platform != "win32":
        print("本 GUI 针对 Windows 版 StorCLI。")
        return
    root = tk.Tk()
    apply_app_icon(root)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
