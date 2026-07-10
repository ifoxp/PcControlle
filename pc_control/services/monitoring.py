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
        }
        self.cores_last = []        # % по ядрах (останній замір)
        self.active_window = ""
        self.started_at = time.time()

    # ---------------- метрики ----------------
    def _read_gpu(self):
        """(gpu_util%, gpu_mem%, gpu_temp) через nvidia-smi. None якщо недоступно."""
        try:
            import subprocess
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=4,
                creationflags=0x08000000).stdout.strip().split("\n")[0]
            util, used, total, temp = [x.strip() for x in out.split(",")]
            mem_pct = round(float(used) / float(total) * 100, 1) if float(total) else None
            return float(util), mem_pct, float(temp)
        except Exception:
            return None, None, None

    def _read_temps_lhm(self):
        """CPU/GPU температура через LibreHardwareMonitor (опційно). (cpu_t, gpu_t)."""
        if not self._lhm_tried:
            self._lhm_tried = True
            try:
                import clr  # pythonnet
                from ..core import paths
                dll = paths.BASE_DIR / "LibreHardwareMonitorLib.dll"
                if dll.exists():
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
            return None, None
        try:
            from LibreHardwareMonitor.Hardware import HardwareType, SensorType
            cpu_t = gpu_t = None
            for hw in self._lhm.Hardware:
                hw.Update()
                for s in hw.Sensors:
                    if s.SensorType == SensorType.Temperature and s.Value is not None:
                        name = str(hw.HardwareType)
                        if "Cpu" in name and cpu_t is None:
                            cpu_t = round(float(s.Value), 1)
                        elif "Gpu" in name and gpu_t is None:
                            gpu_t = round(float(s.Value), 1)
            return cpu_t, gpu_t
        except Exception:
            return None, None

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
        ram = psutil.virtual_memory().percent
        gpu, gpu_mem, gpu_temp = self._read_gpu()
        cpu_temp, gpu_temp_lhm = self._read_temps_lhm()
        if gpu_temp_lhm is not None:
            gpu_temp = gpu_temp_lhm  # LHM точніший, якщо є

        with self._lock:
            self.metrics["cpu"].add(cpu)
            self.metrics["ram"].add(ram)
            if gpu is not None:
                self.metrics["gpu"].add(gpu)
            if gpu_mem is not None:
                self.metrics["gpu_mem"].add(gpu_mem)
            if cpu_temp is not None:
                self.metrics["cpu_temp"].add(cpu_temp)
            if gpu_temp is not None:
                self.metrics["gpu_temp"].add(gpu_temp)
            self.cores_last = [round(c, 1) for c in cores]
            self.active_window = self._active_window_title()

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
