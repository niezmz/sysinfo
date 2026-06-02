"""跨平台系统信息采集。

在 Windows / Linux / macOS 上统一获取 CPU、内存、GPU、磁盘、网络等信息。
"""

import platform
import os
import subprocess
import re
import datetime
from typing import Optional
from pathlib import Path

# ── Windows 平台检测 ──────────────────────────
_WINDOWS = platform.system() == "Windows"

if _WINDOWS:
    import ctypes
    from ctypes import wintypes

    # ── 常见的 ctypes 错误码 & 常量 ─────────

    kernel32 = ctypes.windll.kernel32
    iphlpapi = ctypes.windll.iphlpapi
    advapi32 = ctypes.windll.advapi32

    # ── CPU ──

    class SYSTEM_INFO(ctypes.Structure):
        _fields_ = [
            ("wProcessorArchitecture", wintypes.WORD),
            ("wReserved", wintypes.WORD),
            ("dwPageSize", wintypes.DWORD),
            ("lpMinimumApplicationAddress", ctypes.c_void_p),
            ("lpMaximumApplicationAddress", ctypes.c_void_p),
            ("dwActiveProcessorMask", ctypes.c_size_t),
            ("dwNumberOfProcessors", wintypes.DWORD),
            ("dwProcessorType", wintypes.DWORD),
            ("dwAllocationGranularity", wintypes.DWORD),
            ("wProcessorLevel", wintypes.WORD),
            ("wProcessorRevision", wintypes.WORD),
        ]

    RelationProcessorCore = 0
    RelationNumaNode = 1
    RelationCache = 2

    class CACHE_DESCRIPTOR(ctypes.Structure):
        _fields_ = [
            ("Level", ctypes.c_ubyte),
            ("Associativity", ctypes.c_ubyte),
            ("LineSize", wintypes.WORD),
            ("Size", wintypes.DWORD),
            ("Type", wintypes.DWORD),
        ]

    class SYSTEM_LOGICAL_PROCESSOR_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("ProcessorMask", ctypes.c_size_t),
            ("Relationship", wintypes.DWORD),
            ("_u", ctypes.c_byte * max(ctypes.sizeof(CACHE_DESCRIPTOR), ctypes.sizeof(ctypes.c_ulonglong))),
        ]

    # ── 内存 ──

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    # ── 磁盘 ──

    DRIVE_FIXED = 3
    DRIVE_REMOVABLE = 2
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400

    class STORAGE_PROPERTY_QUERY(ctypes.Structure):
        _fields_ = [
            ("PropertyId", wintypes.DWORD),
            ("QueryType", wintypes.DWORD),
            ("AdditionalParameters", ctypes.c_ubyte * 4),
        ]

    class STORAGE_DESCRIPTOR_HEADER(ctypes.Structure):
        _fields_ = [
            ("Version", wintypes.DWORD),
            ("Size", wintypes.DWORD),
        ]

    # ── 网络 ──

    MAX_ADAPTER_NAME_LENGTH = 256
    MAX_ADAPTER_ADDRESS_LENGTH = 8
    AF_UNSPEC = 0
    GAA_FLAG_INCLUDE_PREFIX = 0x0010
    _WIN32_WINNT_VISTA = 0x0600

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [
            ("lpSockaddr", ctypes.c_void_p),
            ("iSockaddrLength", ctypes.c_int),
        ]

    class IP_ADAPTER_UNICAST_ADDRESS_LH(ctypes.Structure):
        pass

    IP_ADAPTER_UNICAST_ADDRESS_LH._fields_ = [
        ("Length", wintypes.DWORD),
        ("Flags", wintypes.DWORD),
        ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS_LH)),
        ("Address", SOCKET_ADDRESS),
        ("PrefixOrigin", wintypes.DWORD),
        ("SuffixOrigin", wintypes.DWORD),
        ("DadState", wintypes.DWORD),
        ("ValidLifetime", wintypes.DWORD),
        ("PreferredLifetime", wintypes.DWORD),
        ("LeaseLifetime", wintypes.DWORD),
        ("OnLinkPrefixLength", ctypes.c_ubyte),
    ]

    class IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
        pass

    IP_ADAPTER_DNS_SERVER_ADDRESS._fields_ = [
        ("Length", wintypes.DWORD),
        ("Flags", wintypes.DWORD),
        ("Next", ctypes.c_void_p),
        ("Address", SOCKET_ADDRESS),
    ]

    class IP_ADAPTER_ADDRESSES_LH(ctypes.Structure):
        pass

    IP_ADAPTER_ADDRESSES_LH._fields_ = [
        ("Length", wintypes.DWORD),
        ("IfIndex", wintypes.DWORD),
        ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES_LH)),
        ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS_LH)),
        ("FirstAnycastAddress", ctypes.c_void_p),
        ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p),
        ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p),
        ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * MAX_ADAPTER_ADDRESS_LENGTH),
        ("PhysicalAddressLength", wintypes.DWORD),
        ("Flags", wintypes.DWORD),
        ("Mtu", wintypes.DWORD),
        ("IfType", wintypes.DWORD),
        ("OperStatus", wintypes.DWORD),
        ("Ipv6IfIndex", wintypes.DWORD),
        ("ZoneIndices", wintypes.DWORD * 16),
        ("FirstPrefix", ctypes.c_void_p),
        ("TransmitLinkSpeed", ctypes.c_ulonglong),
        ("ReceiveLinkSpeed", ctypes.c_ulonglong),
        ("FirstWinsServerAddress", ctypes.c_void_p),
        ("FirstGatewayAddress", ctypes.c_void_p),
        ("Ipv4Metric", wintypes.DWORD),
        ("Ipv6Metric", wintypes.DWORD),
    ]

    # ── 时区 / 语言 ──

    class SYSTEMTIME(ctypes.Structure):
        _fields_ = [
            ("wYear", wintypes.WORD),
            ("wMonth", wintypes.WORD),
            ("wDayOfWeek", wintypes.WORD),
            ("wDay", wintypes.WORD),
            ("wHour", wintypes.WORD),
            ("wMinute", wintypes.WORD),
            ("wSecond", wintypes.WORD),
            ("wMilliseconds", wintypes.WORD),
        ]

    class DYNAMIC_TIME_ZONE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Bias", wintypes.LONG),
            ("StandardName", wintypes.WCHAR * 32),
            ("StandardDate", SYSTEMTIME),
            ("StandardBias", wintypes.LONG),
            ("DaylightName", wintypes.WCHAR * 32),
            ("DaylightDate", SYSTEMTIME),
            ("DaylightBias", wintypes.LONG),
            ("TimeZoneKeyName", wintypes.WCHAR * 128),
            ("DynamicDaylightTimeDisabled", wintypes.BOOL),
        ]

    # ── 工具函数 ──

    def _ct_fail_ok(cond, msg=""):
        """忽略 ctypes 错误，总是返回 True（类似断言，仅标记意图）。"""
        return True


# ═══════════════════════════════════════════════
#  CPU
# ═══════════════════════════════════════════════

def get_cpu_info() -> dict:
    """获取 CPU 信息。"""
    system = platform.system()
    if system == "Linux":
        return _cpu_linux()
    elif system == "Windows":
        return _cpu_windows()
    elif system == "Darwin":
        return _cpu_macos()
    else:
        return _cpu_fallback()


def _cpu_linux() -> dict:
    name = ""
    cores_physical = 0
    cores_logical = 0
    mhz = ""
    try:
        with open("/proc/cpuinfo", "r") as f:
            content = f.read()
        for line in content.split("\n"):
            if line.startswith("model name") and not name:
                name = line.split(":", 1)[1].strip()
            if line.startswith("cpu MHz") and not mhz:
                mhz = line.split(":", 1)[1].strip()
            if line.startswith("cpu cores") and not cores_physical:
                cores_physical = int(line.split(":", 1)[1].strip())
        cores_logical = content.count("processor\t:")
        if cores_physical == 0:
            phys_ids = set()
            for line in content.split("\n"):
                if line.startswith("physical id"):
                    phys_ids.add(line.split(":", 1)[1].strip())
            cores_physical = len(phys_ids) or (cores_logical or 1)
    except Exception:
        pass

    if not name:
        name = _try_lscpu() or "未知"

    return {
        "name": name,
        "cores_physical": cores_physical,
        "cores_logical": cores_logical,
        "frequency_mhz": mhz,
        "architecture": platform.machine(),
    }


def _try_lscpu() -> str:
    try:
        result = subprocess.run(
            ["lscpu"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if "Model name" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return ""


def _cpu_windows() -> dict:
    """Windows: 通过 GetSystemInfo + GetLogicalProcessorInformation 获取 CPU 信息。"""
    name = os.environ.get("PROCESSOR_IDENTIFIER", "")
    cores_logical = 0
    cores_physical = 0
    mhz = ""

    # —— 逻辑核心数 (GetSystemInfo) ——
    try:
        sysinfo = SYSTEM_INFO()
        kernel32.GetSystemInfo(ctypes.byref(sysinfo))
        cores_logical = sysinfo.dwNumberOfProcessors
    except Exception:
        cores_logical = os.cpu_count() or 0

    # —— 物理核心数 (GetLogicalProcessorInformation) ——
    if cores_logical > 0:
        try:
            buf_size = wintypes.DWORD(0)
            kernel32.GetLogicalProcessorInformation(None, ctypes.byref(buf_size))
            raw = (ctypes.c_ubyte * buf_size.value)()
            if kernel32.GetLogicalProcessorInformation(
                ctypes.cast(raw, ctypes.c_void_p), ctypes.byref(buf_size)
            ):
                info_size = ctypes.sizeof(SYSTEM_LOGICAL_PROCESSOR_INFORMATION)
                offset = 0
                while offset + info_size <= buf_size.value:
                    info = SYSTEM_LOGICAL_PROCESSOR_INFORMATION.from_buffer(
                        raw, offset)
                    if info.Relationship == RelationProcessorCore:
                        cores_physical += 1
                    offset += info_size
        except Exception:
            pass

    if cores_physical == 0:
        cores_physical = cores_logical

    # —— 频率 & 型号（注册表） ——
    try:
        import winreg
        rkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        try:
            mhz_val, _ = winreg.QueryValueEx(rkey, "~MHz")
            mhz = str(mhz_val)
        except Exception:
            pass
        if not name:
            try:
                name, _ = winreg.QueryValueEx(rkey, "ProcessorNameString")
            except Exception:
                pass
        winreg.CloseKey(rkey)
    except Exception:
        pass

    return {
        "name": name or "未知",
        "cores_physical": cores_physical,
        "cores_logical": cores_logical,
        "frequency_mhz": mhz,
        "architecture": platform.machine(),
    }


def _cpu_macos() -> dict:
    name = ""
    cores_physical = os.cpu_count() or 0
    try:
        r = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True, text=True, timeout=5,
        )
        name = r.stdout.strip()
        r = subprocess.run(
            ["sysctl", "-n", "hw.physicalcpu"],
            capture_output=True, text=True, timeout=5,
        )
        cores_physical = int(r.stdout.strip())
    except Exception:
        pass
    return {
        "name": name or "未知",
        "cores_physical": cores_physical,
        "cores_logical": os.cpu_count() or 0,
        "frequency_mhz": "",
        "architecture": platform.machine(),
    }


def _cpu_fallback() -> dict:
    return {
        "name": platform.processor() or "未知",
        "cores_physical": os.cpu_count() or 0,
        "cores_logical": os.cpu_count() or 0,
        "frequency_mhz": "",
        "architecture": platform.machine(),
    }


# ═══════════════════════════════════════════════
#  内存
# ═══════════════════════════════════════════════

def get_memory_info() -> dict:
    system = platform.system()
    if system == "Linux":
        return _memory_linux()
    elif system == "Windows":
        return _memory_windows()
    elif system == "Darwin":
        return _memory_macos()
    else:
        return {"total_gb": 0, "available_gb": 0, "swap_gb": 0}


def _memory_linux() -> dict:
    total_kb = available_kb = swap_total_kb = swap_free_kb = 0
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                digits = int(re.findall(r"\d+", line)[0]) if re.findall(r"\d+", line) else 0
                if line.startswith("MemTotal"):
                    total_kb = digits
                elif line.startswith("MemAvailable"):
                    available_kb = digits
                elif line.startswith("SwapTotal"):
                    swap_total_kb = digits
                elif line.startswith("SwapFree"):
                    swap_free_kb = digits
    except Exception:
        pass
    return {
        "total_gb": round(total_kb / (1024 * 1024), 1),
        "available_gb": round(available_kb / (1024 * 1024), 1),
        "swap_gb": round(swap_total_kb / (1024 * 1024), 1),
        "swap_free_gb": round(swap_free_kb / (1024 * 1024), 1),
    }


def _memory_windows() -> dict:
    """Windows: 通过 GlobalMemoryStatusEx 获取物理内存 & 交换空间。"""
    try:
        ms = MEMORYSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))

        total_gb = round(ms.ullTotalPhys / (1024 ** 3), 1)
        avail_gb = round(ms.ullAvailPhys / (1024 ** 3), 1)

        # 交换空间 = 页面文件总量 - 物理内存总量
        swap_total = ms.ullTotalPageFile - ms.ullTotalPhys
        swap_avail = ms.ullAvailPageFile - ms.ullAvailPhys

        return {
            "total_gb": total_gb,
            "available_gb": avail_gb,
            "swap_gb": round(swap_total / (1024 ** 3), 1),
            "swap_free_gb": round(swap_avail / (1024 ** 3), 1),
        }
    except Exception:
        return {"total_gb": 0, "available_gb": 0, "swap_gb": 0, "swap_free_gb": 0}


def _memory_macos() -> dict:
    return {"total_gb": 0, "available_gb": 0, "swap_gb": 0, "swap_free_gb": 0}


# ═══════════════════════════════════════════════
#  GPU / 显卡
# ═══════════════════════════════════════════════

def get_gpu_info() -> list[dict]:
    """获取 GPU 列表。"""
    system = platform.system()
    if system == "Linux":
        return _gpu_linux()
    elif system == "Windows":
        return _gpu_windows()
    elif system == "Darwin":
        return _gpu_macos()
    else:
        return []


def _gpu_linux() -> list[dict]:
    gpus = []
    try:
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if re.search(r"VGA compatible|3D controller|Display controller", line, re.IGNORECASE):
                # 格式: "29:00.0 VGA compatible controller: ..."
                parts = line.split(":", 2)
                desc = parts[2].strip() if len(parts) > 2 else line
                gpus.append({"name": desc, "bus": parts[0].strip() if parts else ""})
    except Exception:
        pass
    return gpus


def _gpu_windows() -> list[dict]:
    """Windows: 从注册表读取显示适配器（名称 + 显存），wmic 兜底。"""
    gpus: list[dict] = []
    display_guid = "{4d36e968-e325-11ce-bfc1-08002be10318}"

    # ── 主路径：注册表 ──
    try:
        import winreg
        rkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            f"SYSTEM\\CurrentControlSet\\Control\\Class\\{display_guid}")
        idx = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(rkey, idx)
                idx += 1
                # 只需 "0000", "0001" … 形式
                if not re.match(r"^\d{4}$", subkey_name):
                    continue
                sk = winreg.OpenKey(rkey, subkey_name)
                try:
                    gpu_name, _ = winreg.QueryValueEx(sk, "DriverDesc")
                except Exception:
                    gpu_name = "未知 GPU"

                vram_gb: Optional[float] = None
                try:
                    raw, _ = winreg.QueryValueEx(sk, "HardwareInformation.qwMemorySize")
                    if isinstance(raw, bytes) and len(raw) >= 8:
                        import struct
                        vram_bytes = struct.unpack_from("<Q", raw)[0]
                        if vram_bytes > 0:
                            vram_gb = round(vram_bytes / (1024 ** 3), 1)
                except Exception:
                    pass

                gpu = {"name": gpu_name, "bus": subkey_name}  # type: ignore
                if vram_gb is not None:
                    gpu["vram_gb"] = vram_gb
                gpus.append(gpu)

                winreg.CloseKey(sk)
            except OSError:
                break
        winreg.CloseKey(rkey)
    except Exception:
        pass

    # ── 兜底：wmic ──
    if not gpus:
        try:
            result = subprocess.run(
                ["wmic", "path", "win32_videocontroller", "get", "name"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.strip().split("\n")[1:]:
                name = line.strip()
                if name and name != "Name":
                    gpus.append({"name": name, "bus": ""})
        except Exception:
            pass

    return gpus


def _gpu_macos() -> list[dict]:
    gpus = []
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.split("\n"):
            if "Chipset Model:" in line:
                gpus.append({"name": line.split(":", 1)[1].strip(), "bus": ""})
    except Exception:
        pass
    return gpus


# ═══════════════════════════════════════════════
#  磁盘 / 存储
# ═══════════════════════════════════════════════

def get_disk_info() -> list[dict]:
    """获取磁盘列表。"""
    system = platform.system()
    if system == "Linux":
        return _disk_linux()
    elif system == "Windows":
        return _disk_windows()
    elif system == "Darwin":
        return _disk_macos()
    else:
        return []


def _disk_linux() -> list[dict]:
    disks = []
    try:
        result = subprocess.run(
            ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL", "-d", "-e", "7,11"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            size = parts[1] if len(parts) > 1 else ""
            dtype = parts[2] if len(parts) > 2 else ""
            model = " ".join(parts[4:]) if len(parts) > 4 else ""
            if dtype == "disk":
                disks.append({"name": name, "size": size, "model": model})
    except Exception:
        pass

    # 补充分区挂载信息
    try:
        result = subprocess.run(
            ["df", "-h", "--output=source,size,used,avail,target"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if parts and parts[0].startswith("/dev/"):
                disks.append({
                    "name": parts[0], "size": parts[1],
                    "used": parts[2], "avail": parts[3],
                    "mountpoint": parts[4], "model": "",
                })
    except Exception:
        pass

    return disks


def _disk_windows() -> list[dict]:
    """Windows: GetLogicalDrives + GetDiskFreeSpaceExW + wmic 物理磁盘。"""
    disks: list[dict] = []

    # ── 分区（逻辑驱动器） ──
    try:
        drive_bitmask = kernel32.GetLogicalDrives()
        for i in range(26):
            if drive_bitmask & (1 << i):
                root = f"{chr(ord('A') + i)}:\\"
                dtype = kernel32.GetDriveTypeW(root)
                if dtype == DRIVE_FIXED:
                    free_bytes = ctypes.c_ulonglong(0)
                    total_bytes = ctypes.c_ulonglong(0)
                    total_free = ctypes.c_ulonglong(0)
                    if kernel32.GetDiskFreeSpaceExW(
                        root,
                        ctypes.byref(free_bytes),
                        ctypes.byref(total_bytes),
                        ctypes.byref(total_free),
                    ):
                        disks.append({
                            "name": root.rstrip("\\"),
                            "size": _fmt_bytes(total_bytes.value),
                            "used": _fmt_bytes(total_bytes.value - free_bytes.value),
                            "avail": _fmt_bytes(free_bytes.value),
                            "mountpoint": root,
                            "model": "",
                        })
    except Exception:
        pass

    # ── 物理磁盘（wmic） ──
    try:
        result = subprocess.run(
            ["wmic", "diskdrive", "get", "model,size,name"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.strip().split()
            if not parts:
                continue
            raw_name = parts[0]
            model = " ".join(parts[1:-1]) if len(parts) > 2 else ""
            size_str = parts[-1] if parts else ""
            try:
                size_bytes = int(size_str)
                size = _fmt_bytes(size_bytes)
            except Exception:
                size = ""
            if raw_name and model:
                disks.append({
                    "name": raw_name,
                    "size": size,
                    "used": "",
                    "avail": "",
                    "mountpoint": "",
                    "model": model,
                })
    except Exception:
        pass

    return disks


def _fmt_bytes(b: int) -> str:
    """字节数 → 人类可读字符串。"""
    if b >= 1024 ** 4:
        return f"{b / 1024 ** 4:.1f} TB"
    elif b >= 1024 ** 3:
        return f"{b / 1024 ** 3:.1f} GB"
    elif b >= 1024 ** 2:
        return f"{b / 1024 ** 2:.1f} MB"
    else:
        return f"{b} B"


def _disk_macos() -> list[dict]:
    return []


# ═══════════════════════════════════════════════
#  网络接口
# ═══════════════════════════════════════════════

def get_network_info() -> list[dict]:
    """获取网络接口列表。"""
    system = platform.system()
    if system == "Linux":
        return _network_linux()
    elif system == "Windows":
        return _network_windows()
    elif system == "Darwin":
        return _network_macos()
    else:
        return []


def _network_linux() -> list[dict]:
    interfaces = []
    # 先收集所有 NIC 的型号（从 lspci）
    nic_models = _get_nic_models_linux()

    try:
        result = subprocess.run(
            ["ip", "-br", "addr"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.strip().split("\n"):
            parts = line.split()
            if not parts:
                continue
            name = parts[0]
            state = parts[1] if len(parts) > 1 else ""
            ips = [p for p in parts[2:] if "/" in p]

            # 获取接口速度
            speed = ""
            speed_path = Path(f"/sys/class/net/{name}/speed")
            if speed_path.exists():
                try:
                    raw_speed = speed_path.read_text().strip()
                    if raw_speed and raw_speed != "-1":
                        s = int(raw_speed)
                        if s >= 1000:
                            speed = f"{s // 1000} Gbps"
                        else:
                            speed = f"{s} Mbps"
                except Exception:
                    pass

            # 获取 MAC 地址
            mac = ""
            mac_path = Path(f"/sys/class/net/{name}/address")
            if mac_path.exists():
                try:
                    mac = mac_path.read_text().strip()
                except Exception:
                    pass

            interfaces.append({
                "name": name,
                "state": state,
                "ips": ", ".join(ips) if ips else "无 IP",
                "model": nic_models.get(name, ""),
                "speed": speed,
                "mac": mac,
            })
    except Exception:
        pass
    return interfaces


def _get_nic_models_linux() -> dict[str, str]:
    """通过 lspci 获取网卡型号，返回 {iface_name: model} 映射。"""
    models: dict[str, str] = {}
    try:
        # 建立 PCI 地址 → 接口名的映射
        pci_to_iface: dict[str, str] = {}
        for iface in os.listdir("/sys/class/net/"):
            dev_path = Path(f"/sys/class/net/{iface}/device")
            if dev_path.is_symlink():
                # device 符号链接指向 PCI 地址，如 ../../../0000:22:00.0
                target = os.readlink(str(dev_path))
                pci_addr = os.path.basename(target)
                # 去除 0000: 前缀，与 lspci 输出格式对齐
                if pci_addr.startswith("0000:"):
                    pci_addr = pci_addr[5:]
                pci_to_iface[pci_addr] = iface

        # 从 lspci 获取以太网控制器
        result = subprocess.run(
            ["lspci"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if re.search(r"Ethernet|Network", line, re.IGNORECASE):
                # 格式: "22:00.0 Ethernet controller: Realtek ..."
                pci_match = re.match(r"([0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f])", line)
                if pci_match:
                    pci_addr = pci_match.group(1)
                    # 提取型号（冒号后的部分）
                    desc = line.split(":", 2)[-1].strip() if ":" in line else ""
                    if pci_addr in pci_to_iface:
                        models[pci_to_iface[pci_addr]] = desc
    except Exception:
        pass
    return models


def _network_windows() -> list[dict]:
    """Windows: GetAdaptersAddresses 遍历网络适配器链表。"""
    interfaces: list[dict] = []
    try:
        buf_len = wintypes.ULONG(0)
        ret = iphlpapi.GetAdaptersAddresses(
            AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, None, None,
            ctypes.byref(buf_len))
        if ret not in (0, 122):  # 122 = ERROR_BUFFER_OVERFLOW
            return []

        raw = (ctypes.c_ubyte * buf_len.value)()
        ret = iphlpapi.GetAdaptersAddresses(
            AF_UNSPEC, GAA_FLAG_INCLUDE_PREFIX, None,
            ctypes.cast(raw, ctypes.c_void_p), ctypes.byref(buf_len))
        if ret != 0:
            return []

        adapter = ctypes.cast(raw, ctypes.POINTER(IP_ADAPTER_ADDRESSES_LH))
        while adapter:
            a = adapter.contents

            # 接口名称
            iface_name = (a.AdapterName.decode()
                          if a.AdapterName else f"eth{a.IfIndex}")

            # 型号（Description 在 FriendlyName 为空时兜底）
            desc = a.Description or ""
            if not desc:
                desc = a.FriendlyName or ""

            iface: dict = {
                "name": iface_name,
                "state": "UP" if a.OperStatus == 1 else "DOWN",
                "ips": "",
                "model": desc,
                "speed": "",
                "mac": "",
            }

            # MAC 地址
            if a.PhysicalAddressLength > 0:
                mac_parts = [f"{a.PhysicalAddress[i]:02x}"
                             for i in range(a.PhysicalAddressLength)]
                iface["mac"] = ":".join(mac_parts)

            # 链路速率
            if a.TransmitLinkSpeed > 0:
                speed_mbps = a.TransmitLinkSpeed // 1_000_000
            else:
                speed_mbps = a.ReceiveLinkSpeed // 1_000_000
            if speed_mbps >= 1000:
                iface["speed"] = f"{speed_mbps // 1000} Gbps"
            elif speed_mbps > 0:
                iface["speed"] = f"{speed_mbps} Mbps"

            # IP 地址链表
            ips: list[str] = []
            ua = a.FirstUnicastAddress
            while ua:
                sock = ua.contents.Address
                if sock.lpSockaddr:
                    family = ctypes.cast(sock.lpSockaddr,
                        ctypes.POINTER(wintypes.USHORT)).contents.value
                    if family == 2:   # AF_INET
                        addr = ctypes.string_at(sock.lpSockaddr + 4, 4)
                        ips.append(".".join(str(b) for b in addr))
                    elif family == 23:  # AF_INET6
                        addr = ctypes.string_at(sock.lpSockaddr + 8, 16)
                        groups = [f"{addr[i]:02x}{addr[i+1]:02x}" for i in range(0, 16, 2)]
                        ips.append(":".join(groups))
                ua = ua.contents.Next
            iface["ips"] = ", ".join(ips) if ips else "无 IP"

            interfaces.append(iface)
            adapter = a.Next
    except Exception:
        pass
    return interfaces


def _network_macos() -> list[dict]:
    return []


# ═══════════════════════════════════════════════
#  主板
# ═══════════════════════════════════════════════

def get_motherboard_info() -> dict:
    """获取主板信息。"""
    system = platform.system()
    if system == "Linux":
        return _motherboard_linux()
    elif system == "Windows":
        return _motherboard_windows()
    else:
        return {}


def _motherboard_linux() -> dict:
    info = {}
    dmi_path = Path("/sys/class/dmi/id")
    fields = {
        "board_vendor": "制造商",
        "board_name": "型号",
        "board_version": "版本",
        "bios_vendor": "BIOS 厂商",
        "bios_version": "BIOS 版本",
        "bios_date": "BIOS 日期",
        "product_name": "产品名称",
        "sys_vendor": "系统厂商",
        "chassis_type": "机箱类型",
    }
    for key, label in fields.items():
        fpath = dmi_path / key
        if fpath.exists():
            try:
                info[label] = fpath.read_text().strip()
            except Exception:
                pass
    return info


def _motherboard_windows() -> dict:
    """Windows: 从注册表 BIOS 键读取主板 & 系统厂商信息。"""
    info: dict = {}
    field_map = {
        "BaseBoardManufacturer": "制造商",
        "BaseBoardProduct": "型号",
        "BaseBoardVersion": "版本",
        "BIOSVendor": "BIOS 厂商",
        "BIOSVersion": "BIOS 版本",
        "BIOSReleaseDate": "BIOS 日期",
        "SystemManufacturer": "系统厂商",
        "SystemProductName": "产品名称",
    }
    try:
        import winreg
        rkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\BIOS")
        i = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(rkey, i)
                i += 1
                if name in field_map:
                    info[field_map[name]] = str(value)
            except OSError:
                break
        winreg.CloseKey(rkey)
    except Exception:
        pass
    return info


# ═══════════════════════════════════════════════
#  操作系统
# ═══════════════════════════════════════════════

def get_os_info() -> dict:
    return {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "hostname": platform.node(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "boot_time": _get_boot_time(),
    }


def _get_boot_time() -> str:
    system = platform.system()
    if system == "Linux":
        try:
            output = subprocess.run(
                ["uptime", "-s"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            return output
        except Exception:
            pass
    elif system == "Windows":
        return _get_boot_time_windows()
    return ""


def _get_boot_time_windows() -> str:
    """Windows: GetTickCount64 → 反推系统启动时间。"""
    try:
        tick_ms = kernel32.GetTickCount64()
        boot = datetime.datetime.now() - datetime.timedelta(milliseconds=tick_ms)
        return boot.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


# ═══════════════════════════════════════════════
#  语言 / 时区
# ═══════════════════════════════════════════════

def get_locale_info() -> dict:
    """获取系统语言和时区。"""
    system = platform.system()
    if system == "Linux":
        return _locale_linux()
    elif system == "Windows":
        return _locale_windows()
    elif system == "Darwin":
        return _locale_macos()
    else:
        return {"language": "未知", "timezone": "未知"}


def _locale_linux() -> dict:
    lang = os.environ.get("LANG", "") or os.environ.get("LC_ALL", "")
    tz = ""
    try:
        r = subprocess.run(
            ["timedatectl", "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        tz = r.stdout.strip()
    except Exception:
        pass
    if not tz:
        try:
            tz = Path("/etc/timezone").read_text().strip()
        except Exception:
            pass
    if not tz:
        tz = os.environ.get("TZ", "")
    return {"language": lang or "未知", "timezone": tz or "未知"}


def _locale_windows() -> dict:
    """Windows: GetUserDefaultLocaleName + GetDynamicTimeZoneInformation。"""
    lang = "未知"
    tz = "未知"

    # ── 语言 ──
    try:
        buf = ctypes.create_unicode_buffer(85)  # LOCALE_NAME_MAX_LENGTH
        if kernel32.GetUserDefaultLocaleName(buf, len(buf)):
            raw = buf.value
            locale_map = {
                "zh-CN": "zh_CN.UTF-8", "zh-TW": "zh_TW.UTF-8",
                "en-US": "en_US.UTF-8", "en-GB": "en_GB.UTF-8",
                "ja-JP": "ja_JP.UTF-8", "ko-KR": "ko_KR.UTF-8",
                "de-DE": "de_DE.UTF-8", "fr-FR": "fr_FR.UTF-8",
                "es-ES": "es_ES.UTF-8", "ru-RU": "ru_RU.UTF-8",
            }
            lang = locale_map.get(raw, raw)
    except Exception:
        pass

    # ── 时区 ──
    try:
        tzi = DYNAMIC_TIME_ZONE_INFORMATION()
        kernel32.GetDynamicTimeZoneInformation(ctypes.byref(tzi))
        if tzi.TimeZoneKeyName:
            tz = tzi.TimeZoneKeyName
    except Exception:
        pass

    return {"language": lang, "timezone": tz}


def _locale_macos() -> dict:
    tz = ""
    try:
        tz = subprocess.run(
            ["systemsetup", "-gettimezone"],
            capture_output=True, text=True, timeout=5,
        ).stdout.replace("Time Zone:", "").strip()
    except Exception:
        pass
    return {
        "language": os.environ.get("LANG", "未知"),
        "timezone": tz or "未知",
    }


# ═══════════════════════════════════════════════
#  IP 地址
# ═══════════════════════════════════════════════

def get_primary_ip() -> str:
    """获取当前主 IP 地址。"""
    import socket as _socket
    system = platform.system()
    if system == "Linux":
        return _primary_ip_linux()
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _primary_ip_linux() -> str:
    """Linux: 从默认路由接口获取 IP。"""
    try:
        r = subprocess.run(
            ["ip", "-4", "-br", "addr"], capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "UP" and parts[0] != "lo":
                for p in parts[2:]:
                    if "/" in p:
                        return p.split("/")[0]
    except Exception:
        pass
    return "127.0.0.1"


# ═══════════════════════════════════════════════
#  聚合
# ═══════════════════════════════════════════════

def get_all_hardware() -> dict:
    """获取所有可检测的硬件信息，返回结构化字典。

    Returns:
        {
            "os": dict,
            "cpu": dict,
            "memory": dict,
            "gpu": list[dict],
            "disks": list[dict],
            "network": list[dict],
            "motherboard": dict,
        }
    """
    return {
        "os": get_os_info(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "gpu": get_gpu_info(),
        "disks": get_disk_info(),
        "network": get_network_info(),
        "motherboard": get_motherboard_info(),
    }
