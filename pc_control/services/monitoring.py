"""
Моніторинг ресурсів ПК на вимогу (запускається з телефона, вимикається — щоб не
жерти ресурси даремно).

Збирає: CPU% (загальне + по ядрах), RAM%, GPU% і GPU-пам'ять (nvidia-smi),
температуру CPU/GPU (LibreHardwareMonitor, якщо доступний), назву активного вікна.
Накопичує avg/min/max для статистики сесії.

API (див. api.server):
  start()  — увімкнути збір (фоновий тік раз на INTERVAL);
  reset()  — обнулити накопичену статистику (рахувати середнє заново);
  stop()   — вимкнути збір, повернути фінальну статистику;
  snapshot() — поточні значення + агреговані (для живого відображення).

LibreHardwareMonitor: опційний. Якщо DLL немає або немає прав — температура
просто відсутня (решта метрик працює). DLL кладеться поруч з .exe:
  LibreHardwareMonitorLib.dll
"""

from __future__ import annotations

import threading
import time

from ..core.logging_setup import get_logger

logger = get_logger("monitoring")

INTERVAL = 1.0  # секунда між тіками (достатньо, майже не навантажує)


def _cpu_name() -> str:
    """Назва процесора з реєстру Windows (без адмін-прав)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        name = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        winreg.CloseKey(k)
        return name.strip()
    except Exception:
        return ""


class _Agg:
    """Накопичувач avg/min/max для однієї метрики."""
    __slots__ = ("sum", "n", "min", "max", "last")

    def __init__(self):
        self.sum = 0.0
        self.n = 0
        self.min = None
        self.max = None
        self.last = None

    def add(self, v):
        if v is None:
            return
        self.last = v
        self.sum += v
        self.n += 1
        self.min = v if self.min is None else min(self.min, v)
        self.max = v if self.max is None else max(self.max, v)

    def as_dict(self):
        avg = round(self.sum / self.n, 1) if self.n else None
        return {"last": self.last, "avg": avg, "min": self.min, "max": self.max}


class _Monitor:
    def __init__(self):
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._lhm = None            # LibreHardwareMonitor computer (лінива ініціалізація)
        self._lhm_tried = False
        self._reset_locked()

    def _reset_locked(self):
        self.metrics = {
            "cpu": _Agg(), "ram": _Agg(),
            "gpu": _Agg(), "gpu_mem": _Agg(),
            "cpu_temp": _Agg(), "gpu_temp": _Agg(),
            "gpu_power": _Agg(), "cpu_power": _Agg(),
            "total_power": _Agg(),   # приблизне сумарне споживання ПК (CPU+GPU)
        }
        self.cores_last = []        # % по ядрах (останній замір)
        self.active_window = ""
        self.started_at = time.time()
        # абсолютні значення (поточні, не агреговані)
        self.ram_used_gb = self.ram_total_gb = None
        self.vram_used_gb = self.vram_total_gb = None
        self.gpu_name = ""
        self.cpu_name = _cpu_name()
        self.disks = []

    # ---------------- метрики ----------------
    def _read_gpu(self):
        """dict з даними GPU через nvidia-smi (util%, mem%, ГБ, temp, вати).
        Порожній dict, якщо недоступно."""
        try:
            import subprocess
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,"
                 "power.draw,name",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=0x08000000).stdout.strip().split("\n")[0]
            parts = [x.strip() for x in out.split(",")]
            util, used, total, temp, power = parts[:5]
            name = parts[5] if len(parts) > 5 else ""
            used_mb, total_mb = float(used), float(total)
            return {
                "util": float(util),
                "mem_pct": round(used_mb / total_mb * 100, 1) if total_mb else None,
                "mem_used_gb": round(used_mb / 1024, 1),
                "mem_total_gb": round(total_mb / 1024, 1),
                "temp": float(temp),
                "power": round(float(power)) if power not in ("", "[N/A]") else None,
                "name": name,
            }
        except Exception:
            return {}

    def _read_temps_lhm(self):
        """CPU/GPU температура через LibreHardwareMonitor (опційно). (cpu_t, gpu_t)."""
        if not self._lhm_tried:
            self._lhm_tried = True
            try:
                import clr  # pythonnet
                import sys
                from pathlib import Path
                from ..core import paths
                # DLL можуть бути: у _MEIPASS (onefile .exe розпаковує datas туди),
                # поруч з .exe (BASE_DIR), або у pc_control/lib (dev-запуск).
                name = "LibreHardwareMonitorLib.dll"
                candidates = []
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass:
                    candidates.append(Path(meipass) / name)
                candidates += [
                    paths.BASE_DIR / name,
                    Path(__file__).resolve().parents[1] / "lib" / name,
                ]
                dll = next((d for d in candidates if d.exists()), None)
                if dll is not None:
                    clr.AddReference(str(dll))
                    from LibreHardwareMonitor.Hardware import Computer
                    c = Computer()
                    c.IsCpuEnabled = True
                    c.IsGpuEnabled = True
                    c.Open()
                    self._lhm = c
                    logger.info("LibreHardwareMonitor підключено (температура доступна).")
                else:
                    logger.info("LibreHardwareMonitorLib.dll не знайдено — темп. CPU без нього.")
            except Exception as e:
                logger.info("LHM недоступний (%s) — температура CPU може бути відсутня.", e)
                self._lhm = None
        if self._lhm is None:
            return {"cpu_t": None, "gpu_t": None, "cpu_power": None, "gpu_power": None}
        try:
            from LibreHardwareMonitor.Hardware import SensorType
            res = {"cpu_t": None, "gpu_t": None, "cpu_power": None, "gpu_power": None}
            for hw in self._lhm.Hardware:
                hw.Update()
                is_cpu = "Cpu" in str(hw.HardwareType)
                is_gpu = "Gpu" in str(hw.HardwareType)
                for s in hw.Sensors:
                    if s.Value is None:
                        continue
                    sn = (s.Name or "")
                    if s.SensorType == SensorType.Temperature:
                        # для CPU беремо "Package"/"Tctl" (загальна), інакше перший
                        if is_cpu and (res["cpu_t"] is None or "Package" in sn or "Tctl" in sn):
                            res["cpu_t"] = round(float(s.Value), 1)
                        elif is_gpu and res["gpu_t"] is None:
                            res["gpu_t"] = round(float(s.Value), 1)
                    elif s.SensorType == SensorType.Power:
                        # CPU Package Power; GPU — беремо загальну плати ("Package"/"Total")
                        if is_cpu and ("Package" in sn or res["cpu_power"] is None):
                            res["cpu_power"] = round(float(s.Value))
                        elif is_gpu and ("Package" in sn or "Total" in sn
                                         or res["gpu_power"] is None):
                            res["gpu_power"] = round(float(s.Value))
            return res
        except Exception:
            return {"cpu_t": None, "gpu_t": None, "cpu_power": None, "gpu_power": None}

    def _active_window_title(self):
        try:
            import win32gui
            return win32gui.GetWindowText(win32gui.GetForegroundWindow())[:80]
        except Exception:
            return ""

    def _tick(self):
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        vm = psutil.virtual_memory()
        ram = vm.percent
        g = self._read_gpu()
        lhm = self._read_temps_lhm()
        cpu_temp = lhm.get("cpu_t")
        cpu_power = lhm.get("cpu_power")
        gpu_temp = lhm.get("gpu_t") if lhm.get("gpu_t") is not None else g.get("temp")
        # GPU-вати: nvidia-smi точніші; якщо нема (не-Nvidia) — беремо з LHM
        gpu_power = g.get("power") if g.get("power") is not None else lhm.get("gpu_power")
        # приблизне сумарне споживання ПК: CPU + GPU (головні споживачі; повне
        # «з розетки» без спец. заліза не виміряти, це оцінка знизу).
        total_power = None
        if cpu_power is not None or gpu_power is not None:
            total_power = round((cpu_power or 0) + (gpu_power or 0))

        with self._lock:
            self.metrics["cpu"].add(cpu)
            self.metrics["ram"].add(ram)
            if g.get("util") is not None:
                self.metrics["gpu"].add(g["util"])
            if g.get("mem_pct") is not None:
                self.metrics["gpu_mem"].add(g["mem_pct"])
            if cpu_temp is not None:
                self.metrics["cpu_temp"].add(cpu_temp)
            if cpu_power is not None:
                self.metrics["cpu_power"].add(cpu_power)
            if gpu_temp is not None:
                self.metrics["gpu_temp"].add(gpu_temp)
            if gpu_power is not None:
                self.metrics["gpu_power"].add(gpu_power)
            if total_power is not None:
                self.metrics["total_power"].add(total_power)
            self.cores_last = [round(c, 1) for c in cores]
            self.active_window = self._active_window_title()
            # абсолютні значення (не агрегуємо — показуємо поточні)
            self.ram_used_gb = round(vm.used / 1024**3, 1)
            self.ram_total_gb = round(vm.total / 1024**3, 1)
            self.vram_used_gb = g.get("mem_used_gb")
            self.vram_total_gb = g.get("mem_total_gb")
            self.gpu_name = g.get("name", "")
            self.disks = self._read_disks()

    def _read_disks(self):
        """Диски: [{letter, used_gb, total_gb, pct}]. Лише фіксовані."""
        import psutil
        out = []
        try:
            for p in psutil.disk_partitions(all=False):
                if "cdrom" in p.opts or not p.fstype:
                    continue
                try:
                    u = psutil.disk_usage(p.mountpoint)
                except Exception:
                    continue
                out.append({
                    "letter": p.device.replace("\\", ""),
                    "used_gb": round(u.used / 1024**3, 1),
                    "total_gb": round(u.total / 1024**3, 1),
                    "pct": round(u.percent, 1),
                })
        except Exception:
            pass
        return out

    def _run(self):
        import psutil
        psutil.cpu_percent(interval=None)  # перший виклик — «розігрів»
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.warning("monitor tick error: %s", e)
            time.sleep(INTERVAL)

    # ---------------- публічний API ----------------
    def start(self):
        with self._lock:
            if self._running:
                return
            self._reset_locked()
            self._running = True
        self._thread = threading.Thread(target=self._run, name="monitoring", daemon=True)
        self._thread.start()
        logger.info("Моніторинг ресурсів УВІМКНЕНО.")

    def reset(self):
        with self._lock:
            self._reset_locked()
        logger.info("Моніторинг: статистику скинуто.")

    def stop(self):
        was = self._running
        self._running = False
        logger.info("Моніторинг ресурсів ВИМКНЕНО.")
        return self.snapshot(final=True) if was else self.snapshot(final=True)

    def snapshot(self, final: bool = False):
        with self._lock:
            data = {k: v.as_dict() for k, v in self.metrics.items()}
            return {
                "running": self._running,
                "final": final,
                "duration_sec": int(time.time() - self.started_at),
                "active_window": self.active_window,
                "cores": self.cores_last,
                "metrics": data,
                "ram_used_gb": self.ram_used_gb,
                "ram_total_gb": self.ram_total_gb,
                "vram_used_gb": self.vram_used_gb,
                "vram_total_gb": self.vram_total_gb,
                "gpu_name": self.gpu_name,
                "cpu_name": self.cpu_name,
                "disks": self.disks,
            }


_monitor = _Monitor()


def start():
    _monitor.start()


def reset():
    _monitor.reset()


def stop():
    return _monitor.stop()


def snapshot():
    return _monitor.snapshot()
