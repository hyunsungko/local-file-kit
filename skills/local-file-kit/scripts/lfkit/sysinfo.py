"""This computer's OS, CPU, memory, graphics cards and disks (standard library only)."""
import os
import platform
import re
import shutil
import sys

from .util import IS_MAC, IS_WIN, LfkError, run

GB = 1024 ** 3


def _gb(n):
    return round(n / GB, 1) if n is not None else None


def os_info():
    info = {"system": platform.system(), "release": platform.release(), "version": platform.version(),
            "machine": platform.machine(), "python": platform.python_version(),
            "python_bits": 64 if sys.maxsize > 2 ** 32 else 32}
    if IS_WIN:
        try:
            build = int(platform.version().split(".")[2])
            info["release"] = "11" if build >= 22000 else info["release"]
            info["build"] = build
        except (IndexError, ValueError):
            pass
        info["edition"] = _win_reg(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "EditionID")
    return info


def _win_reg(sub, value, root=None):
    import winreg
    try:
        with winreg.OpenKey(root or winreg.HKEY_LOCAL_MACHINE, sub) as k:
            return winreg.QueryValueEx(k, value)[0]
    except OSError:
        return None


def cpu_info():
    name = None
    if IS_WIN:
        name = _win_reg(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    elif IS_MAC:
        try:
            name = run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=5)[1].strip()
        except LfkError:
            pass
    else:
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
                m = re.search(r"^model name\s*:\s*(.+)$", f.read(), re.M)
                name = m.group(1) if m else None
        except OSError:
            pass
    return {"name": (name or platform.processor() or "").strip() or None, "logical_cores": os.cpu_count()}


def memory_info():
    if IS_WIN:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = MEMORYSTATUSEX()
        st.dwLength = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return {"total_gb": _gb(st.ullTotalPhys), "free_gb": _gb(st.ullAvailPhys)}
        return {}
    if IS_MAC:
        try:
            total = int(run(["sysctl", "-n", "hw.memsize"], timeout=5)[1].strip())
            return {"total_gb": _gb(total), "free_gb": None}
        except (LfkError, ValueError):
            return {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            text = f.read()
        total = int(re.search(r"MemTotal:\s+(\d+)", text).group(1)) * 1024
        avail = int(re.search(r"MemAvailable:\s+(\d+)", text).group(1)) * 1024
        return {"total_gb": _gb(total), "free_gb": _gb(avail)}
    except (OSError, AttributeError):
        return {}


def gpu_info():
    """Graphics cards with dedicated memory. On Apple Silicon the GPU shares system memory."""
    gpus = []
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            rc, out, _ = run([smi, "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits"], timeout=15)
            if rc == 0:
                for line in out.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 3:
                        gpus.append({"name": parts[0], "vram_gb": round(int(parts[1]) / 1024, 1),
                                     "vram_used_gb": round(int(parts[2]) / 1024, 1), "source": "nvidia-smi"})
        except (LfkError, ValueError):
            pass
    if IS_WIN:
        import winreg
        cls = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, cls) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                    except OSError:
                        break
                    i += 1
                    if not sub.isdigit():
                        continue
                    name = _win_reg(cls + "\\" + sub, "DriverDesc")
                    mem = _win_reg(cls + "\\" + sub, "HardwareInformation.qwMemorySize")
                    if mem is None:
                        raw = _win_reg(cls + "\\" + sub, "HardwareInformation.MemorySize")
                        mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else raw
                    if not name or any(g["name"] == name for g in gpus):
                        continue
                    if any(w in name for w in ("Basic Display", "Remote", "Virtual", "Hyper-V")):
                        continue
                    gpus.append({"name": name, "vram_gb": _gb(int(mem)) if mem else None, "source": "registry"})
        except OSError:
            pass
    elif IS_MAC and platform.machine() == "arm64":
        gpus.append({"name": "Apple Silicon GPU", "vram_gb": None, "shared_memory": True, "source": "platform"})
    return gpus


def disk_info():
    disks = []
    if IS_WIN:
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        kinds = {2: "removable", 3: "fixed", 4: "network", 5: "cdrom", 6: "ramdisk"}
        for i in range(26):
            if not mask & (1 << i):
                continue
            root = chr(65 + i) + ":\\"
            dtype = kinds.get(k32.GetDriveTypeW(root), "unknown")
            entry = {"root": root, "type": dtype}
            if dtype in ("fixed", "removable", "network", "ramdisk"):
                fs = ctypes.create_unicode_buffer(64)
                if k32.GetVolumeInformationW(root, None, 0, None, None, None, fs, 64):
                    entry["filesystem"] = fs.value
                try:
                    u = shutil.disk_usage(root)
                    entry.update(total_gb=_gb(u.total), free_gb=_gb(u.free))
                except OSError:
                    pass
            disks.append(entry)
    else:
        for root in ("/", os.path.expanduser("~")):
            try:
                u = shutil.disk_usage(root)
                disks.append({"root": root, "total_gb": _gb(u.total), "free_gb": _gb(u.free)})
            except OSError:
                pass
    return disks


def all_info():
    return {"os": os_info(), "cpu": cpu_info(), "memory": memory_info(), "gpus": gpu_info(), "disks": disk_info()}
