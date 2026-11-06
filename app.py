"""
SteelSeries Arctis Nova / GameDAC OLED Hardware Monitor
Displays CPU, GPU temps, and RAM usage on the controller OLED screen.
Includes OLED burn-in protection (pixel shifting, line alternation, and idle sleep).
Uses SteelSeries GameSense SDK local REST API.
"""

import sys
import os
import json
import time
import signal
import socket
import ctypes
import traceback
import urllib.request
import urllib.error

# Ensure pythonw.exe doesn't crash on stdout/stderr calls
class NullWriter:
    def write(self, s):
        pass
    def flush(self):
        pass

if sys.stdout is None:
    sys.stdout = NullWriter()
if sys.stderr is None:
    sys.stderr = NullWriter()

instance_lock_socket = None

def acquire_instance_lock():
    global instance_lock_socket
    instance_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        instance_lock_socket.bind(("127.0.0.1", 47823))
        return True
    except socket.error:
        return False

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.log")

def safe_print(msg, end="\n", flush=False):
    try:
        sys.stdout.write(msg + end)
        if flush:
            sys.stdout.flush()
    except Exception:
        pass
def log(msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    safe_print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Windows Native Hardware & Idle Monitoring (ctypes - Zero External Dependencies)
# ---------------------------------------------------------------------------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)
    ]

class FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_uint32), ('dwHighDateTime', ctypes.c_uint32)]

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]

def filetime_to_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime

def get_idle_seconds():
    """Returns number of seconds since last user keyboard/mouse input."""
    try:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            if lii.dwTime == 0:
                return 0.0
            curr_tick = ctypes.windll.kernel32.GetTickCount()
            millis = (curr_tick - lii.dwTime) & 0xFFFFFFFF
            return millis / 1000.0
    except Exception:
        pass
    return 0.0

class HardwareMonitor:
    def __init__(self, lhm_url="http://localhost:8085/data.json"):
        self.lhm_url = lhm_url
        self.last_idle = 0
        self.last_kernel = 0
        self.last_user = 0
        self._init_cpu_times()
        self.cached_cpu_temp = None
        self.cached_gpu_temp = None
        self.last_temp_time = 0

    def _init_cpu_times(self):
        try:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            self.last_idle = filetime_to_int(idle)
            self.last_kernel = filetime_to_int(kernel)
            self.last_user = filetime_to_int(user)
        except Exception:
            pass

    def get_ram_info(self):
        """Returns (used_gb, total_gb, percent_used)"""
        try:
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            total_gb = mem.ullTotalPhys / (1024 ** 3)
            used_gb = (mem.ullTotalPhys - mem.ullAvailPhys) / (1024 ** 3)
            return used_gb, total_gb, int(mem.dwMemoryLoad)
        except Exception:
            return 0.0, 0.0, 0

    def get_cpu_load(self):
        """Calculates CPU utilization % since last call."""
        try:
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
            )
            curr_idle = filetime_to_int(idle)
            curr_kernel = filetime_to_int(kernel)
            curr_user = filetime_to_int(user)

            idle_diff = curr_idle - self.last_idle
            kernel_diff = curr_kernel - self.last_kernel
            user_diff = curr_user - self.last_user

            self.last_idle = curr_idle
            self.last_kernel = curr_kernel
            self.last_user = curr_user

            total = kernel_diff + user_diff
            if total > 0:
                cpu_pct = 100.0 * (total - idle_diff) / total
                return max(0, min(100, int(round(cpu_pct))))
            return 0
        except Exception:
            return 0

    def get_temperatures_from_lhm(self):
        """
        Queries LibreHardwareMonitor web server.
        Returns (cpu_temp_c, gpu_temp_c) or cached/fallback values.
        """
        data = None
        try:
            req = urllib.request.Request(self.lhm_url, headers={'User-Agent': 'SteelSeriesMonitor/1.0'})
            with urllib.request.urlopen(req, timeout=1.0) as response:
                data = json.loads(response.read().decode('utf-8'))
        except Exception:
            data = None

        cpu_temp = None
        gpu_temp = None

        if data:
            def crawl(node, hw_type=None):
                nonlocal cpu_temp, gpu_temp
                text = node.get("Text", "")
                hid = node.get("HardwareId", "").lower()
                t_lower = text.lower()

                # Detect hardware category
                if "/gpu" in hid or any(k in t_lower for k in ["radeon", "geforce", "nvidia", "intel arc"]) or (t_lower.startswith("gpu") and not hw_type):
                    hw_type = "gpu"
                elif "/cpu" in hid or any(k in t_lower for k in ["intel core", "amd ryzen", "intel pentium", "intel celeron"]) or (t_lower.startswith("cpu") and not hw_type):
                    hw_type = "cpu"

                val_str = node.get("Value", "")
                stype = node.get("Type", "")

                if ("°C" in val_str or stype == "Temperature") and val_str:
                    try:
                        val = float(val_str.split()[0].replace(',', '.'))
                        if hw_type == "gpu":
                            if "core" in t_lower or "edge" in t_lower or "gpu" in t_lower:
                                gpu_temp = int(round(val))
                            elif gpu_temp is None:
                                gpu_temp = int(round(val))
                        elif hw_type == "cpu":
                            if any(k in t_lower for k in ["package", "average", "core max", "tctl"]):
                                if cpu_temp is None or "package" in t_lower or "average" in t_lower:
                                    cpu_temp = int(round(val))
                            elif cpu_temp is None:
                                cpu_temp = int(round(val))
                    except (ValueError, IndexError):
                        pass

                for child in node.get("Children", []):
                    crawl(child, hw_type)

            crawl(data)

        # Update cache if valid values received
        now = time.time()
        if cpu_temp is not None:
            self.cached_cpu_temp = cpu_temp
        if gpu_temp is not None:
            self.cached_gpu_temp = gpu_temp
        if cpu_temp is not None or gpu_temp is not None:
            self.last_temp_time = now

        # Use cached values during boot/slow poll if last update was within 15 seconds
        if (now - self.last_temp_time) < 15.0:
            if cpu_temp is None:
                cpu_temp = self.cached_cpu_temp
            if gpu_temp is None:
                gpu_temp = self.cached_gpu_temp

        return cpu_temp, gpu_temp

# ---------------------------------------------------------------------------
# SteelSeries GameSense Client
# ---------------------------------------------------------------------------

class GameSenseClient:
    GAME_NAME = "PC_SYS_MONITOR"
    GAME_DISPLAY_NAME = "PC Hardware Monitor"
    EVENT_NAME = "STATS"

    def __init__(self):
        self.base_url = None
        self.last_heartbeat = 0

    def discover_address(self):
        """Reads coreProps.json to find the local SteelSeries GG server port."""
        program_data = os.getenv("PROGRAMDATA", "C:\\ProgramData")
        core_props_path = os.path.join(
            program_data, "SteelSeries", "SteelSeries Engine 3", "coreProps.json"
        )

        if not os.path.exists(core_props_path):
            return None

        try:
            with open(core_props_path, "r", encoding="utf-8") as f:
                props = json.load(f)
                addr = props.get("address")
                if addr:
                    return f"http://{addr}"
        except Exception:
            return None
        return None

    def post(self, endpoint, payload):
        """Performs a JSON POST request to GameSense server."""
        if not self.base_url:
            return False
        url = f"{self.base_url}/{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def connect_and_register(self):
        """Attempts to register app and screen event with SteelSeries GG."""
        addr = self.discover_address()
        if not addr:
            return False
        self.base_url = addr

        # 1. Register Metadata
        meta_ok = self.post("game_metadata", {
            "game": self.GAME_NAME,
            "game_display_name": self.GAME_DISPLAY_NAME,
            "developer": "Antigravity",
            "deinitialize_timer_length_ms": 60000
        })
        if not meta_ok:
            return False

        # 2. Bind OLED Screen Handler across all supported screened device types
        screen_frame = {
            "length-millis": 3000,
            "lines": [
                {
                    "has-text": True,
                    "context-frame-key": "line1"
                },
                {
                    "has-text": True,
                    "context-frame-key": "line2"
                }
            ]
        }

        handlers = []
        for dev in ["screened", "screened-2-lines", "screened-128x52", "screened-128x48"]:
            handlers.append({
                "device-type": dev,
                "zone": "one",
                "mode": "screen",
                "datas": [screen_frame]
            })

        bind_ok = self.post("bind_game_event", {
            "game": self.GAME_NAME,
            "event": self.EVENT_NAME,
            "handlers": handlers
        })
        return bind_ok

    def send_frame(self, line1, line2):
        """Sends a 2-line frame update to the OLED screen."""
        payload = {
            "game": self.GAME_NAME,
            "event": self.EVENT_NAME,
            "data": {
                "frame": {
                    "line1": line1,
                    "line2": line2
                }
            }
        }
        return self.post("game_event", payload)

    def heartbeat(self):
        now = time.time()
        if now - self.last_heartbeat > 10:
            self.post("game_heartbeat", {"game": self.GAME_NAME})
            self.last_heartbeat = now

    def stop(self):
        """Stops the game session in GameSense so default OLED screen is restored."""
        if self.base_url:
            self.post("stop_game", {"game": self.GAME_NAME})

# ---------------------------------------------------------------------------
# Burn-in Protection Controller
# ---------------------------------------------------------------------------

class BurnInProtector:
    def __init__(self, config):
        burn_cfg = config.get("burn_in_protection", {})
        self.enabled = burn_cfg.get("enabled", True)
        self.pixel_shift_enabled = burn_cfg.get("pixel_shift_enabled", True)
        self.pixel_shift_interval = burn_cfg.get("pixel_shift_interval_sec", 60)
        self.swap_lines_enabled = burn_cfg.get("swap_lines_enabled", True)
        self.swap_lines_interval = burn_cfg.get("swap_lines_interval_sec", 180)
        self.idle_sleep_enabled = burn_cfg.get("idle_sleep_enabled", True)
        self.idle_sleep_sec = burn_cfg.get("idle_sleep_minutes", 5) * 60

        self.start_time = time.time()

    def check_idle_sleep(self):
        """Returns True if display should be put to sleep (blanked) due to inactivity."""
        if not self.enabled or not self.idle_sleep_enabled:
            return False
        # Grace period: never sleep in the first 2 minutes after launch/reboot
        if (time.time() - self.start_time) < 120:
            return False
        idle_time = get_idle_seconds()
        return idle_time >= self.idle_sleep_sec

    def apply_protection(self, line1, line2):
        """
        Applies pixel shifting and periodic line swapping to protect OLED phosphor.
        """
        if not self.enabled:
            return line1, line2

        now = time.time()

        # 1. Periodic Line Swapping (swaps line 1 and 2 every N seconds)
        if self.swap_lines_enabled and self.swap_lines_interval > 0:
            swap_cycle = int((now - self.start_time) // self.swap_lines_interval) % 2
            if swap_cycle == 1:
                line1, line2 = line2, line1

        # 2. Pixel Shifting (shifts text horizontally by 0 or 1 space cyclically)
        if self.pixel_shift_enabled and self.pixel_shift_interval > 0:
            shift_step = int((now - self.start_time) // self.pixel_shift_interval) % 2
            prefix = " " if shift_step == 1 else ""
            line1 = f"{prefix}{line1}"
            line2 = f"{prefix}{line2}"

        return line1, line2

# ---------------------------------------------------------------------------
# Main Application Loop
# ---------------------------------------------------------------------------

def load_config():
    default_config = {
        "refresh_interval_sec": 1.5,
        "lhm_url": "http://localhost:8085/data.json",
        "lhm_exe_path": r"C:\Program Files\LibreHardwareMonitor\LibreHardwareMonitor.exe",
        "autostart_lhm": True,
        "ram_show_decimal": True,
        "burn_in_protection": {
            "enabled": True,
            "pixel_shift_enabled": True,
            "pixel_shift_interval_sec": 60,
            "swap_lines_enabled": True,
            "swap_lines_interval_sec": 180,
            "idle_sleep_enabled": True,
            "idle_sleep_minutes": 5
        }
    }
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    if isinstance(v, dict) and k in default_config and isinstance(default_config[k], dict):
                        default_config[k].update(v)
                    else:
                        default_config[k] = v
        except Exception:
            pass
    else:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=4)
        except Exception:
            pass
    return default_config

def ensure_lhm_running(lhm_path, lhm_url="http://localhost:8085/data.json"):
    """Launches LibreHardwareMonitor if its web server is not already answering."""
    if not lhm_path or not os.path.exists(lhm_path):
        return
    try:
        req = urllib.request.Request(lhm_url, headers={'User-Agent': 'SteelSeriesMonitor/1.0'})
        with urllib.request.urlopen(req, timeout=0.3):
            return  # Already answering
    except Exception:
        pass

    try:
        log(f"[Autostart] Launching LibreHardwareMonitor from {lhm_path}...")
        os.startfile(lhm_path)
    except Exception as e:
        log(f"[Warning] Could not autostart LibreHardwareMonitor: {e}")

def main():
    if not acquire_instance_lock():
        # Another instance is already active
        sys.exit(0)

    log("=" * 60)
    log("SteelSeries Arctis Nova / GameDAC OLED Hardware Monitor Started")
    log("=" * 60)

    config = load_config()

    # Autostart LibreHardwareMonitor if enabled
    if config.get("autostart_lhm", True):
        ensure_lhm_running(config.get("lhm_exe_path"), config.get("lhm_url", "http://localhost:8085/data.json"))
    hw = HardwareMonitor(lhm_url=config.get("lhm_url", "http://localhost:8085/data.json"))
    client = GameSenseClient()
    protector = BurnInProtector(config)

    running = True

    def sig_handler(sig, frame):
        nonlocal running
        log("Stopping monitor and releasing OLED display...")
        running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    connected = False
    lhm_warned = False
    was_sleeping = False
    fail_count = 0
    sensors_logged = False

    log("Checking connection to SteelSeries GG (Engine)...")

    try:
        while running:
            if not connected:
                if client.connect_and_register():
                    connected = True
                    log(f"[OK] Connected to SteelSeries GameSense ({client.base_url})")
                    log("[OK] Registered OLED app: 'PC Hardware Monitor'")
                    burn_info = "Enabled (Shift: 60s, Line Swap: 180s, Sleep: 5m)" if protector.enabled else "Disabled"
                    log(f"[OK] OLED Burn-in Protection: {burn_info}")
                    log(f"[OK] Streaming metrics every {config['refresh_interval_sec']}s.\n")
                else:
                    time.sleep(3)
                    continue

            # Keep alive
            client.heartbeat()

            # Check idle sleep for OLED burn-in protection
            is_idle = protector.check_idle_sleep()
            if is_idle:
                if not was_sleeping:
                    # Blank the OLED screen completely (pure black = LEDs off)
                    client.send_frame("", "")
                    log("[OLED Burn-in Protection] Inactivity detected. OLED display sleeping (LEDs OFF)...")
                    was_sleeping = True
                time.sleep(1.0)
                continue
            elif was_sleeping:
                log("[OLED Burn-in Protection] User activity detected! Waking display...")
                was_sleeping = False

            # Gather metrics
            used_ram, total_ram, _ = hw.get_ram_info()
            cpu_load = hw.get_cpu_load()
            cpu_temp, gpu_temp = hw.get_temperatures_from_lhm()

            if not sensors_logged and (cpu_temp is not None and gpu_temp is not None):
                log(f"[OK] Hardware sensors online: CPU Temp={cpu_temp}°C, GPU Temp={gpu_temp}°C")
                sensors_logged = True

            # Format Line 1: CPU & GPU Temps
            if cpu_temp is not None or gpu_temp is not None:
                c_str = f"C:{cpu_temp}°" if cpu_temp is not None else f"C:{cpu_load}%"
                g_str = f"G:{gpu_temp}°" if gpu_temp is not None else "G:--"
                line_temps = f"{c_str}  {g_str}"
            else:
                line_temps = f"CPU:{cpu_load}% GPU:--"
                if not lhm_warned:
                    safe_print("[Info] For live CPU/GPU temps, run LibreHardwareMonitor with 'Remote Web Server' enabled.")
                    lhm_warned = True

            # Format Line 2: RAM usage (clean x/32G without the % per user request)
            if config.get("ram_show_decimal", True):
                line_ram = f"RAM: {used_ram:.1f}/{total_ram:.0f}G"
            else:
                line_ram = f"RAM: {int(round(used_ram))}/{total_ram:.0f}G"

            # Apply burn-in protection (pixel shifting & line alternating)
            final_line1, final_line2 = protector.apply_protection(line_temps, line_ram)

            # Push to OLED
            success = client.send_frame(final_line1, final_line2)
            if not success:
                fail_count += 1
                if fail_count >= 3:
                    log("[Warning] Failed to push frame 3 times in a row. Re-establishing connection...")
                    connected = False
                    fail_count = 0
                    time.sleep(1)
                    continue
            else:
                fail_count = 0

            # Console status line
            safe_print(f"\r[OLED Display] L1: '{final_line1:<14}' | L2: '{final_line2:<14}'", end="", flush=True)

            time.sleep(config.get("refresh_interval_sec", 1.5))

    except Exception as e:
        log(f"[FATAL CRASH] {e}\n{traceback.format_exc()}")
    finally:
        client.stop()
        log("Exited cleanly.")

if __name__ == "__main__":
    main()
