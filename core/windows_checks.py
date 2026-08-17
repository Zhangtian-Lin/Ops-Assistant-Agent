"""Read-only Windows diagnostics used by the local Ops Agent."""

import json
import os
import subprocess
from typing import Any, Dict


class WindowsCheckError(RuntimeError):
    pass


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsCheckError("This diagnostic is available on Windows only")


def _powershell_json(script: str, timeout: int = 15) -> Any:
    _require_windows()
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise WindowsCheckError(completed.stderr.strip() or "Windows diagnostic command failed")
    output = completed.stdout.strip()
    return json.loads(output) if output else []


def _result(category: str, script: str, timeout: int = 15) -> Dict[str, Any]:
    try:
        return {"status": "ok", "category": category, "data": _powershell_json(script, timeout)}
    except (OSError, subprocess.SubprocessError, ValueError, WindowsCheckError) as exc:
        return {"status": "system_error", "category": category, "error": str(exc)}


def check_gpu() -> Dict[str, Any]:
    return _result("gpu", "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,AdapterRAM,VideoProcessor,CurrentHorizontalResolution,CurrentVerticalResolution | ConvertTo-Json -Compress")


def check_disk_health() -> Dict[str, Any]:
    return _result("disk_health", "[pscustomobject]@{physical=(Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,OperationalStatus,Size); volumes=(Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,HealthStatus,OperationalStatus,Size,SizeRemaining)} | ConvertTo-Json -Depth 4 -Compress")


def check_processes() -> Dict[str, Any]:
    return _result("processes", "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 20 ProcessName,Id,CPU,@{Name='MemoryMB';Expression={[math]::Round($_.WorkingSet64/1MB,1)}} | ConvertTo-Json -Compress")


def check_system_inventory() -> Dict[str, Any]:
    return _result("system_inventory", "$os=Get-CimInstance Win32_OperatingSystem; $boot=(bcdedit /enum osloader 2>$null | Select-String 'identifier|description' | ForEach-Object {$_.Line.Trim()}); [pscustomobject]@{caption=$os.Caption;version=$os.Version;build=$os.BuildNumber;last_boot=$os.LastBootUpTime;boot_entries=$boot} | ConvertTo-Json -Depth 3 -Compress")


def check_security_baseline() -> Dict[str, Any]:
    return _result("security_baseline", "$fw=Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction; $defender=if(Get-Command Get-MpComputerStatus -ErrorAction SilentlyContinue){Get-MpComputerStatus | Select-Object AMServiceEnabled,AntivirusEnabled,AntispywareEnabled,RealTimeProtectionEnabled,AntivirusSignatureLastUpdated}else{$null}; $hotfix=Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 10 HotFixID,Description,InstalledOn; [pscustomobject]@{firewall=$fw;defender=$defender;recent_updates=$hotfix} | ConvertTo-Json -Depth 4 -Compress", 25)


def check_event_errors() -> Dict[str, Any]:
    return _result("event_errors", "Get-WinEvent -FilterHashtable @{LogName='System';Level=2;StartTime=(Get-Date).AddDays(-7)} -MaxEvents 20 | Select-Object TimeCreated,ProviderName,Id,LevelDisplayName,Message | ConvertTo-Json -Compress", 25)


def check_driver_issues() -> Dict[str, Any]:
    return _result("driver_issues", "Get-CimInstance Win32_PnPEntity | Where-Object {$_.ConfigManagerErrorCode -ne 0} | Select-Object Name,DeviceID,ConfigManagerErrorCode,Status | ConvertTo-Json -Compress")


def check_scheduled_tasks() -> Dict[str, Any]:
    return _result("scheduled_tasks", "Get-ScheduledTask | Where-Object {$_.State -eq 'Running'} | Select-Object TaskName,TaskPath,State | ConvertTo-Json -Compress")


def check_user_sessions() -> Dict[str, Any]:
    return _result("user_sessions", "$sessions=(query user 2>$null); [pscustomobject]@{sessions=$sessions} | ConvertTo-Json -Compress")


def check_power() -> Dict[str, Any]:
    return _result("power", "$battery=Get-CimInstance Win32_Battery | Select-Object Name,BatteryStatus,EstimatedChargeRemaining,EstimatedRunTime,Status; $plan=(powercfg /getactivescheme 2>$null); [pscustomobject]@{battery=$battery;active_power_plan=$plan} | ConvertTo-Json -Depth 3 -Compress")


CHECKS = {
    "gpu": check_gpu,
    "disk_health": check_disk_health,
    "processes": check_processes,
    "system_inventory": check_system_inventory,
    "security_baseline": check_security_baseline,
    "event_errors": check_event_errors,
    "driver_issues": check_driver_issues,
    "scheduled_tasks": check_scheduled_tasks,
    "user_sessions": check_user_sessions,
    "power": check_power,
}


def run_check(category: str) -> Dict[str, Any]:
    check = CHECKS.get(category)
    if not check:
        return {"status": "invalid_request", "error": "Unknown Windows diagnostic category"}
    return check()
