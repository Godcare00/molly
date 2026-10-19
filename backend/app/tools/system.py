import platform
import psutil
import subprocess
import shutil
from typing import Optional
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry


class GetSystemInfoTool(BaseTool):
    name = "get_system_info"
    description = "Get compact system information: OS, kernel, architecture, hostname, uptime, CPU, Python version, current user."
    risk_level = RiskLevel.READ
    timeout_seconds = 10
    output_limit_chars = 2000

    async def execute(self) -> ToolResult:
        try:
            import getpass

            uname = platform.uname()
            boot_time = psutil.boot_time()
            uptime_seconds = int(psutil.time.time() - boot_time)
            uptime_str = self._format_uptime(uptime_seconds)

            cpu_count = psutil.cpu_count(logical=True)
            cpu_freq = psutil.cpu_freq()

            info = {
                "os": uname.system,
                "os_release": uname.release,
                "os_version": uname.version,
                "architecture": uname.machine,
                "hostname": uname.node,
                "uptime": uptime_str,
                "cpu_cores": cpu_count,
                "cpu_freq_mhz": round(cpu_freq.current) if cpu_freq else None,
                "python_version": platform.python_version(),
                "current_user": getpass.getuser(),
            }

            return ToolResult(success=True, output=info)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _format_uptime(self, seconds: int) -> str:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        return " ".join(parts) if parts else "< 1m"


class GetDiskUsageTool(BaseTool):
    name = "get_disk_usage"
    description = "Get compact filesystem usage: total, used, available, percentage for relevant mounted filesystems."
    risk_level = RiskLevel.READ
    timeout_seconds = 10
    output_limit_chars = 3000

    async def execute(self) -> ToolResult:
        try:
            partitions = psutil.disk_partitions(all=False)
            filesystems = []

            for part in partitions:
                try:
                    usage = shutil.disk_usage(part.mountpoint)
                    filesystems.append(
                        {
                            "device": part.device,
                            "mountpoint": part.mountpoint,
                            "fstype": part.fstype,
                            "total_bytes": usage.total,
                            "used_bytes": usage.used,
                            "free_bytes": usage.free,
                            "percent_used": round((usage.used / usage.total) * 100, 1),
                        }
                    )
                except (PermissionError, OSError):
                    continue

            return ToolResult(success=True, output={"filesystems": filesystems})
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetMemoryUsageTool(BaseTool):
    name = "get_memory_usage"
    description = "Get memory usage: RAM total, used, available, percentage, swap usage."
    risk_level = RiskLevel.READ
    timeout_seconds = 5
    output_limit_chars = 1500

    async def execute(self) -> ToolResult:
        try:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()

            output = {
                "ram": {
                    "total_bytes": mem.total,
                    "used_bytes": mem.used,
                    "available_bytes": mem.available,
                    "percent_used": mem.percent,
                },
                "swap": {
                    "total_bytes": swap.total,
                    "used_bytes": swap.used,
                    "free_bytes": swap.free,
                    "percent_used": swap.percent,
                },
            }

            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetProcessesTool(BaseTool):
    name = "get_processes"
    description = "Get a compact process overview. Supports filtering by name, user, or CPU/memory thresholds."
    risk_level = RiskLevel.READ
    timeout_seconds = 10
    output_limit_chars = 8000

    async def execute(
        self,
        filter_name: Optional[str] = None,
        filter_user: Optional[str] = None,
        min_cpu_percent: float = 0.0,
        min_memory_percent: float = 0.0,
        limit: int = 50,
        sort_by: str = "cpu",
    ) -> ToolResult:
        try:
            processes = []

            for proc in psutil.process_iter(
                ["pid", "name", "username", "cpu_percent", "memory_percent", "cmdline", "status"]
            ):
                try:
                    info = proc.info

                    if filter_name and filter_name.lower() not in (info["name"] or "").lower():
                        continue
                    if filter_user and info["username"] != filter_user:
                        continue
                    if info["cpu_percent"] is not None and info["cpu_percent"] < min_cpu_percent:
                        continue
                    if info["memory_percent"] is not None and info["memory_percent"] < min_memory_percent:
                        continue

                    cmdline = info["cmdline"]
                    if cmdline:
                        cmdline = " ".join(cmdline[:5])  # Truncate long command lines

                    processes.append(
                        {
                            "pid": info["pid"],
                            "name": info["name"],
                            "user": info["username"],
                            "cpu_percent": round(info["cpu_percent"] or 0, 1),
                            "memory_percent": round(info["memory_percent"] or 0, 1),
                            "status": info["status"],
                            "cmdline": cmdline,
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            # Sort
            reverse = True
            if sort_by == "cpu":
                processes.sort(key=lambda p: p["cpu_percent"], reverse=reverse)
            elif sort_by == "memory":
                processes.sort(key=lambda p: p["memory_percent"], reverse=reverse)
            elif sort_by == "pid":
                processes.sort(key=lambda p: p["pid"])

            # Limit
            truncated = len(processes) > limit
            processes = processes[:limit]

            return ToolResult(
                success=True,
                output={"processes": processes, "total_count": len(processes) + (len(processes) - limit if truncated else 0)},
                truncated=truncated,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GetServiceStatusTool(BaseTool):
    name = "get_service_status"
    description = "Inspect a system service status. Returns compact status information."
    risk_level = RiskLevel.READ
    timeout_seconds = 10
    output_limit_chars = 2000

    async def execute(self, service: str) -> ToolResult:
        try:
            # Use systemctl for systemd services
            result = subprocess.run(
                ["systemctl", "status", service, "--no-pager", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            output_lines = result.stdout.strip().split("\n")
            active = "inactive"
            sub_state = "dead"
            main_pid = None

            for line in output_lines:
                line = line.strip()
                if line.startswith("Active:"):
                    # Active: active (running) since ...
                    parts = line.split()
                    if len(parts) >= 2:
                        active = parts[1].strip("()")
                        if len(parts) >= 3 and parts[2] == "(":
                            sub_state = parts[3].strip(")")
                elif line.startswith("Main PID:"):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            main_pid = int(parts[2])
                        except ValueError:
                            pass

            return ToolResult(
                success=True,
                output={
                    "service": service,
                    "active": active,
                    "sub_state": sub_state,
                    "main_pid": main_pid,
                    "exit_code": result.returncode,
                    "raw_output": result.stdout[-2000:] if result.stdout else "",
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Command timed out")
        except FileNotFoundError:
            return ToolResult(success=False, error="systemctl not found")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# Register all system tools
def register_system_tools():
    registry.register(GetSystemInfoTool())
    registry.register(GetDiskUsageTool())
    registry.register(GetMemoryUsageTool())
    registry.register(GetProcessesTool())
    registry.register(GetServiceStatusTool())