"""实时性能监控 — CPU / GPU / 内存 / 网络 采样。

维护采样间状态，计算 delta 值（CPU 使用率、网络速率等）。
"""

import time
import os
import re
import platform
from pathlib import Path

# ── Windows 平台检测 ──────────────────────────
_WINDOWS = platform.system() == "Windows"

if _WINDOWS:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    iphlpapi = ctypes.windll.iphlpapi

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

    # ── CPU ──

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    def _filetime_to_uint64(ft: 'FILETIME') -> int:
        return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

    class PROCESSOR_POWER_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("Number", wintypes.DWORD),
            ("MaxMhz", wintypes.DWORD),
            ("CurrentMhz", wintypes.DWORD),
            ("MhzLimit", wintypes.DWORD),
            ("MaxIdleState", wintypes.DWORD),
            ("CurrentIdleState", wintypes.DWORD),
        ]

    # ── 网络 ──

    MAX_INTERFACE_NAME_LEN = 256
    MAXLEN_PHYSADDR = 8
    MAXLEN_IFDESCR = 256

    class MIB_IFROW(ctypes.Structure):
        _fields_ = [
            ("wszName", wintypes.WCHAR * MAX_INTERFACE_NAME_LEN),
            ("dwIndex", wintypes.DWORD),
            ("dwType", wintypes.DWORD),
            ("dwMtu", wintypes.DWORD),
            ("dwSpeed", wintypes.DWORD),
            ("dwPhysAddrLen", wintypes.DWORD),
            ("bPhysAddr", ctypes.c_ubyte * MAXLEN_PHYSADDR),
            ("dwAdminStatus", wintypes.DWORD),
            ("dwOperStatus", wintypes.DWORD),
            ("dwLastChange", wintypes.DWORD),
            ("dwInOctets", wintypes.DWORD),
            ("dwInUcastPkts", wintypes.DWORD),
            ("dwInNUcastPkts", wintypes.DWORD),
            ("dwInDiscards", wintypes.DWORD),
            ("dwInErrors", wintypes.DWORD),
            ("dwInUnknownProtos", wintypes.DWORD),
            ("dwOutOctets", wintypes.DWORD),
            ("dwOutUcastPkts", wintypes.DWORD),
            ("dwOutNUcastPkts", wintypes.DWORD),
            ("dwOutDiscards", wintypes.DWORD),
            ("dwOutErrors", wintypes.DWORD),
            ("dwOutQLen", wintypes.DWORD),
            ("dwDescrLen", wintypes.DWORD),
            ("bDescr", ctypes.c_ubyte * MAXLEN_IFDESCR),
        ]

    class MIB_IFTABLE(ctypes.Structure):
        _fields_ = [
            ("dwNumEntries", wintypes.DWORD),
            ("table", MIB_IFROW * 1),  # 变长数组，最低 1 个元素
        ]

    # ── 磁盘 I/O ──

    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 1
    FILE_SHARE_WRITE = 2
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    IOCTL_DISK_PERFORMANCE = 0x00070020

    class DISK_PERFORMANCE(ctypes.Structure):
        _fields_ = [
            ("BytesRead", ctypes.c_int64),
            ("BytesWritten", ctypes.c_int64),
            ("ReadTime", ctypes.c_int64),
            ("WriteTime", ctypes.c_int64),
            ("IdleTime", ctypes.c_int64),
            ("ReadCount", wintypes.DWORD),
            ("WriteCount", wintypes.DWORD),
            ("_pad0", wintypes.DWORD),  # QueueDepth alignment — skip
            ("SplitCount", wintypes.DWORD),
            ("QueryTime", ctypes.c_int64),
            ("StorageDeviceNumber", wintypes.DWORD),
            ("StorageManagerName", wintypes.WCHAR * 8),
        ]


class PerfMonitor:
    """性能采样器。

    调用 snapshot() 获取当前快照。内部维护上一次采样的原始数据，
    用两次采样的差值计算瞬时速率。
    """

    def __init__(self):
        self._system = platform.system()
        # Linux: (idle_ticks, total_ticks); Windows: (idle, kernel, user) uint64
        self._prev_cpu: tuple | None = None
        self._prev_net: dict[str, tuple[int, int]] | None = None
        self._prev_disk: dict[str, tuple[int, int]] | None = None
        self._prev_time: float | None = None

        # Windows 专用
        self._nvml = None          # NVML CDLL handle
        self._disk_handles = []    # 物理磁盘句柄缓存
        if self._system == "Windows":
            self._init_nvml()

    def _init_nvml(self):
        """尝试加载 NVML，初始化 NVIDIA GPU 监控。"""
        try:
            self._nvml = ctypes.CDLL("nvml.dll")
            if self._nvml.nvmlInit_v2() != 0:
                self._nvml = None
        except Exception:
            pass

    # ═══════════════════════════════════════════
    #  公开接口
    # ═══════════════════════════════════════════

    def snapshot(self) -> dict:
        """获取当前性能快照。

        Returns:
            dict with keys: cpu_percent, cpu_freq_mhz, memory_percent,
                            gpu_percent, gpu_temp_c, gpu_power_w,
                            gpu_freq_mhz, gpu_vram_percent,
                            network_rx_kbps, network_tx_kbps
        """
        now = time.time()
        snap: dict = {}

        # CPU
        snap["cpu_percent"] = self._cpu_usage(now)
        snap["cpu_freq_mhz"] = self._cpu_freq()
        snap["cpu_temp_c"] = self._cpu_temp()

        # 内存
        snap["memory_percent"] = self._memory_usage()

        # GPU (AMD)
        snap.update(self._gpu_stats())

        # 网络速率
        net = self._network_throughput(now)
        snap["network_rx_kbps"] = net["rx_kbps"]
        snap["network_tx_kbps"] = net["tx_kbps"]

        # 磁盘 I/O
        disk = self._disk_io(now)
        snap["disk_read_kbps"] = disk["read_kbps"]
        snap["disk_write_kbps"] = disk["write_kbps"]

        self._prev_time = now
        return snap

    # ═══════════════════════════════════════════
    #  CPU
    # ═══════════════════════════════════════════

    def _cpu_usage(self, now: float) -> float:
        if self._system == "Linux":
            return self._cpu_usage_linux(now)
        elif self._system == "Windows":
            return self._cpu_usage_windows(now)
        return 0.0

    def _cpu_usage_linux(self, now: float) -> float:
        """从 /proc/stat 计算 CPU 使用率（百分比）。"""
        try:
            with open("/proc/stat", "r") as f:
                for line in f:
                    if line.startswith("cpu "):
                        parts = line.split()
                        vals = [int(x) for x in parts[1:8]]
                        idle = vals[3] + vals[4]  # idle + iowait
                        total = sum(vals)
                        break
                else:
                    return 0.0

            if self._prev_cpu is not None and self._prev_time is not None:
                prev_idle, prev_total = self._prev_cpu
                delta_idle = idle - prev_idle
                delta_total = total - prev_total
                if delta_total > 0:
                    usage = (1 - delta_idle / delta_total) * 100
                else:
                    usage = 0.0
            else:
                usage = 0.0

            self._prev_cpu = (idle, total)
            return round(usage, 1)
        except Exception:
            return 0.0

    def _cpu_usage_windows(self, now: float) -> float:
        """GetSystemTimes → 所有核心合计的 CPU 使用率。"""
        try:
            idle_ft = FILETIME()
            kernel_ft = FILETIME()
            user_ft = FILETIME()
            kernel32.GetSystemTimes(
                ctypes.byref(idle_ft), ctypes.byref(kernel_ft),
                ctypes.byref(user_ft))

            idle = _filetime_to_uint64(idle_ft)
            kernel = _filetime_to_uint64(kernel_ft)
            user = _filetime_to_uint64(user_ft)
            total = kernel + user

            if self._prev_cpu is not None and self._prev_time is not None:
                prev_idle, prev_kernel, prev_user = self._prev_cpu
                prev_total = prev_kernel + prev_user
                delta_idle = idle - prev_idle
                delta_total = total - prev_total
                if delta_total > 0:
                    usage = (1 - delta_idle / delta_total) * 100
                else:
                    usage = 0.0
            else:
                usage = 0.0

            self._prev_cpu = (idle, kernel, user)
            return round(usage, 1)
        except Exception:
            return 0.0

    def _cpu_freq(self) -> float:
        if self._system == "Linux":
            return self._cpu_freq_linux()
        elif self._system == "Windows":
            return self._cpu_freq_windows()
        return 0.0

    def _cpu_freq_linux(self) -> float:
        """获取所有核心 cpufreq 平均值 (MHz)。"""
        freqs = []
        try:
            for entry in os.listdir("/sys/devices/system/cpu/"):
                if entry.startswith("cpu") and entry[3:].isdigit():
                    fpath = Path(f"/sys/devices/system/cpu/{entry}/cpufreq/scaling_cur_freq")
                    if fpath.exists():
                        khz = int(fpath.read_text().strip())
                        freqs.append(khz / 1000)
        except Exception:
            pass
        if freqs:
            return round(sum(freqs) / len(freqs), 0)
        return 0.0

    def _cpu_freq_windows(self) -> float:
        """CallNtPowerInformation(ProcessorInformation) → 所有核心平均 MHz。"""
        try:
            # Try powrprof first (real-time frequency)
            import ctypes as _ct
            powrprof = _ct.windll.powrprof
            cpu_count = os.cpu_count() or 1
            infos = (PROCESSOR_POWER_INFORMATION * cpu_count)()
            ret = powrprof.CallNtPowerInformation(
                11, None, 0, _ct.byref(infos),
                _ct.sizeof(PROCESSOR_POWER_INFORMATION) * cpu_count)
            if ret == 0:
                total = sum(info.CurrentMhz for info in infos)
                if total > 0:
                    return round(total / cpu_count, 0)
        except Exception:
            pass
        return 0.0

    def _cpu_temp(self) -> int:
        if self._system == "Linux":
            return self._cpu_temp_linux()
        return 0  # Windows: 无标准 API

    def _cpu_temp_linux(self) -> int:
        """获取 CPU 封装温度 (°C)。支持 AMD k10temp 和 Intel coretemp。"""
        try:
            for hwmon in Path("/sys/class/hwmon/").iterdir():
                name_file = hwmon / "name"
                if not name_file.exists():
                    continue
                driver = name_file.read_text().strip()
                if driver in ("k10temp", "coretemp"):
                    temp_file = hwmon / "temp1_input"
                    if temp_file.exists():
                        return int(temp_file.read_text().strip()) // 1000
        except Exception:
            pass
        return 0

    # ═══════════════════════════════════════════
    #  内存
    # ═══════════════════════════════════════════

    def _memory_usage(self) -> float:
        if self._system == "Linux":
            return self._memory_usage_linux()
        elif self._system == "Windows":
            return self._memory_usage_windows()
        return 0.0

    def _memory_usage_linux(self) -> float:
        """从 /proc/meminfo 计算内存使用率。"""
        try:
            with open("/proc/meminfo", "r") as f:
                content = f.read()
            total = _extract_kb(content, "MemTotal")
            available = _extract_kb(content, "MemAvailable")
            if total > 0:
                return round((1 - available / total) * 100, 1)
        except Exception:
            pass
        return 0.0

    def _memory_usage_windows(self) -> float:
        """GlobalMemoryStatusEx.dwMemoryLoad (0-100)。"""
        try:
            ms = MEMORYSTATUSEX()
            ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
            return round(float(ms.dwMemoryLoad), 1)
        except Exception:
            return 0.0

    # ═══════════════════════════════════════════
    #  GPU (AMD)
    # ═══════════════════════════════════════════

    def _gpu_stats(self) -> dict:
        if self._system == "Linux":
            return self._gpu_stats_linux()
        elif self._system == "Windows":
            return self._gpu_stats_windows()
        return {"gpu_percent": 0.0, "gpu_temp_c": 0, "gpu_power_w": 0.0,
                "gpu_freq_mhz": 0, "gpu_vram_percent": 0.0}

    def _gpu_stats_linux(self) -> dict:
        """读取 AMD GPU 传感器（/sys/class/drm）。"""
        stats: dict = {
            "gpu_percent": 0.0, "gpu_temp_c": 0, "gpu_power_w": 0.0,
            "gpu_freq_mhz": 0, "gpu_vram_percent": 0.0,
        }
        try:
            for entry in os.listdir("/sys/class/drm/"):
                if not entry.startswith("card") or "-" in entry:
                    continue
                dev = Path(f"/sys/class/drm/{entry}/device")

                usage_f = dev / "gpu_busy_percent"
                if usage_f.exists():
                    stats["gpu_percent"] = float(usage_f.read_text().strip())

                vram_used = dev / "mem_info_vram_used"
                vram_total = dev / "mem_info_vram_total"
                if vram_used.exists() and vram_total.exists():
                    used = int(vram_used.read_text().strip())
                    total = int(vram_total.read_text().strip())
                    if total > 0:
                        stats["gpu_vram_percent"] = round(used / total * 100, 1)

                hwmon_dir = dev / "hwmon"
                if hwmon_dir.exists():
                    for hw in hwmon_dir.iterdir():
                        temp_f = hw / "temp1_input"
                        if temp_f.exists() and stats["gpu_temp_c"] == 0:
                            stats["gpu_temp_c"] = int(temp_f.read_text().strip()) // 1000

                        power_f = hw / "power1_average"
                        if power_f.exists():
                            stats["gpu_power_w"] = round(
                                int(power_f.read_text().strip()) / 1_000_000, 1)

                        for freq_f in ("freq1_input", "freq2_input"):
                            fp = hw / freq_f
                            if fp.exists():
                                mhz = int(fp.read_text().strip()) // 1_000_000
                                stats["gpu_freq_mhz"] = max(stats["gpu_freq_mhz"], mhz)
                break
        except Exception:
            pass
        return stats

    def _gpu_stats_windows(self) -> dict:
        """NVML (NVIDIA) GPU 传感器。非 NVIDIA 返回全 0。"""
        stats = {"gpu_percent": 0.0, "gpu_temp_c": 0, "gpu_power_w": 0.0,
                 "gpu_freq_mhz": 0, "gpu_vram_percent": 0.0}
        if self._nvml is None:
            return stats

        try:
            count = ctypes.c_uint(0)
            if self._nvml.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
                return stats
            if count.value == 0:
                return stats

            dev = ctypes.c_void_p()
            if self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev)) != 0:
                return stats

            # 使用率
            util = ctypes.c_uint(0), ctypes.c_uint(0)
            class NvmlUtil(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]
            nu = NvmlUtil()
            if self._nvml.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(nu)) == 0:
                stats["gpu_percent"] = float(nu.gpu)
                stats["gpu_vram_percent"] = float(nu.memory)

            # 温度
            temp = ctypes.c_uint(0)
            if self._nvml.nvmlDeviceGetTemperature(dev, 0, ctypes.byref(temp)) == 0:
                stats["gpu_temp_c"] = temp.value

            # 功耗 (mW → W)
            power = ctypes.c_uint(0)
            if self._nvml.nvmlDeviceGetPowerUsage(dev, ctypes.byref(power)) == 0:
                stats["gpu_power_w"] = round(power.value / 1000.0, 1)

            # 频率
            clock = ctypes.c_uint(0)
            if self._nvml.nvmlDeviceGetClockInfo(dev, 0, ctypes.byref(clock)) == 0:
                stats["gpu_freq_mhz"] = clock.value
        except Exception:
            pass
        return stats

    # ═══════════════════════════════════════════
    #  网络速率
    # ═══════════════════════════════════════════

    def _network_throughput(self, now: float) -> dict:
        if self._system == "Linux":
            return self._network_linux(now)
        elif self._system == "Windows":
            return self._network_windows(now)
        return {"rx_kbps": 0.0, "tx_kbps": 0.0}

    def _network_linux(self, now: float) -> dict:
        """从 /proc/net/dev 计算网络瞬时速率 (KB/s)。"""
        result = {"rx_kbps": 0.0, "tx_kbps": 0.0}
        try:
            current: dict[str, tuple[int, int]] = {}
            with open("/proc/net/dev", "r") as f:
                for line in f:
                    if ":" not in line:
                        continue
                    iface, rest = line.split(":", 1)
                    iface = iface.strip()
                    if iface == "lo":
                        continue
                    parts = rest.split()
                    rx = int(parts[0])
                    tx = int(parts[8])
                    current[iface] = (rx, tx)

            if self._prev_net is not None and self._prev_time is not None:
                delta_t = now - self._prev_time
                if delta_t > 0:
                    total_rx = total_tx = 0
                    for iface, (rx, tx) in current.items():
                        if iface in self._prev_net:
                            prev_rx, prev_tx = self._prev_net[iface]
                            drx = rx - prev_rx if rx >= prev_rx else rx
                            dtx = tx - prev_tx if tx >= prev_tx else tx
                            total_rx += drx
                            total_tx += dtx
                    result["rx_kbps"] = round(total_rx / 1024 / delta_t, 1)
                    result["tx_kbps"] = round(total_tx / 1024 / delta_t, 1)

            self._prev_net = current
        except Exception:
            pass
        return result

    def _network_windows(self, now: float) -> dict:
        """GetIfTable → 所有操作接口的 InOctets/OutOctets delta。"""
        result = {"rx_kbps": 0.0, "tx_kbps": 0.0}
        try:
            # 计算所需缓冲区大小
            row_size = ctypes.sizeof(MIB_IFROW)
            buf_size = wintypes.DWORD(0)
            iphlpapi.GetIfTable(None, ctypes.byref(buf_size), 1)

            raw = (ctypes.c_ubyte * buf_size.value)()
            if iphlpapi.GetIfTable(ctypes.cast(raw, ctypes.c_void_p),
                                   ctypes.byref(buf_size), 1) != 0:
                return result

            num_entries = ctypes.cast(raw, ctypes.POINTER(wintypes.DWORD)).contents.value
            current: dict[str, tuple[int, int]] = {}

            for i in range(num_entries):
                offset = 4 + i * row_size  # 跳过 dwNumEntries
                row = MIB_IFROW.from_buffer(raw, offset)
                # IF_TYPE_ETHERNET_CSMACD=6, IF_TYPE_IEEE80211=71
                if row.dwType not in (6, 71):
                    continue
                if row.dwOperStatus != 1:  # IF_OPER_STATUS_UP
                    continue
                name = row.wszName  # WCHAR array → Python string
                if isinstance(name, ctypes.Array):
                    name = name.value
                name = str(name).rstrip("\x00") if name else f"if_{i}"
                current[name] = (row.dwInOctets, row.dwOutOctets)

            if self._prev_net is not None and self._prev_time is not None:
                delta_t = now - self._prev_time
                if delta_t > 0:
                    total_rx = total_tx = 0
                    for iface, (rx, tx) in current.items():
                        if iface in self._prev_net:
                            prev_rx, prev_tx = self._prev_net[iface]
                            drx = rx - prev_rx if rx >= prev_rx else rx
                            dtx = tx - prev_tx if tx >= prev_tx else tx
                            total_rx += drx
                            total_tx += dtx
                    result["rx_kbps"] = round(total_rx / 1024 / delta_t, 1)
                    result["tx_kbps"] = round(total_tx / 1024 / delta_t, 1)

            self._prev_net = current
        except Exception:
            pass
        return result

    # ═══════════════════════════════════════════
    #  磁盘 I/O 速率
    # ═══════════════════════════════════════════

    def _disk_io(self, now: float) -> dict:
        if self._system == "Linux":
            return self._disk_io_linux(now)
        elif self._system == "Windows":
            return self._disk_io_windows(now)
        return {"read_kbps": 0.0, "write_kbps": 0.0}

    def _disk_io_linux(self, now: float) -> dict:
        """从 /proc/diskstats 计算磁盘读写速率 (KB/s)。"""
        result = {"read_kbps": 0.0, "write_kbps": 0.0}
        try:
            current: dict[str, tuple[int, int]] = {}
            with open("/proc/diskstats", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 14:
                        continue
                    dev = parts[2]
                    if not _is_physical_disk(dev):
                        continue
                    rd_sect = int(parts[5])
                    wr_sect = int(parts[9])
                    current[dev] = (rd_sect, wr_sect)

            if self._prev_disk is not None and self._prev_time is not None:
                delta_t = now - self._prev_time
                if delta_t > 0:
                    total_rd = total_wr = 0
                    for dev, (rd, wr) in current.items():
                        if dev in self._prev_disk:
                            prev_rd, prev_wr = self._prev_disk[dev]
                            drd = rd - prev_rd if rd >= prev_rd else rd
                            dwr = wr - prev_wr if wr >= prev_wr else wr
                            total_rd += drd
                            total_wr += dwr
                    result["read_kbps"] = round(total_rd * 0.5 / delta_t, 1)
                    result["write_kbps"] = round(total_wr * 0.5 / delta_t, 1)

            self._prev_disk = current
        except Exception:
            pass
        return result

    def _disk_io_windows(self, now: float) -> dict:
        """DeviceIoControl(IOCTL_DISK_PERFORMANCE) → 累计 BytesRead/Write delta。

        注意：需要管理员权限才能打开 \\\\.\\PhysicalDriveN。无权限时返回 0。
        """
        result = {"read_kbps": 0.0, "write_kbps": 0.0}
        try:
            # 惰性打开物理磁盘句柄
            if not self._disk_handles:
                for i in range(8):
                    path = f"\\\\.\\PhysicalDrive{i}"
                    h = kernel32.CreateFileW(
                        path, GENERIC_READ,
                        FILE_SHARE_READ | FILE_SHARE_WRITE,
                        None, OPEN_EXISTING, 0, None)
                    if h != INVALID_HANDLE_VALUE:
                        self._disk_handles.append(h)

            if not self._disk_handles:
                return result

            dp = DISK_PERFORMANCE()
            total_rd = 0
            total_wr = 0
            disk_ok = False

            for h in self._disk_handles:
                ret_bytes = wintypes.DWORD(0)
                if kernel32.DeviceIoControl(
                    h, IOCTL_DISK_PERFORMANCE,
                    None, 0,
                    ctypes.byref(dp), ctypes.sizeof(DISK_PERFORMANCE),
                    ctypes.byref(ret_bytes), None
                ):
                    disk_ok = True
                    total_rd += dp.BytesRead
                    total_wr += dp.BytesWritten

            if not disk_ok:
                return result

            current = (total_rd, total_wr)

            if self._prev_disk is not None and self._prev_time is not None:
                delta_t = now - self._prev_time
                if delta_t > 0:
                    prev_rd, prev_wr = self._prev_disk.get("__total__", (0, 0))
                    drd = total_rd - prev_rd if total_rd >= prev_rd else total_rd
                    dwr = total_wr - prev_wr if total_wr >= prev_wr else total_wr
                    result["read_kbps"] = round(drd / 1024 / delta_t, 1)
                    result["write_kbps"] = round(dwr / 1024 / delta_t, 1)

            self._prev_disk = {"__total__": current}
        except Exception:
            pass
        return result


def _is_physical_disk(name: str) -> bool:
    """判断块设备名是否代表物理磁盘（排除分区、loop、ramdisk 等）。"""
    import re as _re
    # nvme0n1 ✓  |  nvme0n1p1 ✗
    # sda ✓      |  sda1 ✗
    # vda ✓      |  vda1 ✗
    # loop0 ✗    |  ram0 ✗  |  zram0 ✗
    if name.startswith(("loop", "ram", "zram", "dm-")):
        return False
    # NVMe 分区: nvmeXnYpZ
    if "p" in name and _re.search(r'nvme\d+n\d+p', name):
        return False
    # SCSI/SATA 分区: sdX + 数字
    if _re.search(r'^sd[a-z]+\d+$', name):
        return False
    # virtio 分区: vdX + 数字
    if _re.search(r'^vd[a-z]+\d+$', name):
        return False
    return True


# ═══════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════

def _extract_kb(content: str, key: str) -> int:
    """从 /proc/meminfo 内容中提取某个键的 KB 值。"""
    m = re.search(rf"^{key}:\s+(\d+)", content, re.MULTILINE)
    return int(m.group(1)) if m else 0
