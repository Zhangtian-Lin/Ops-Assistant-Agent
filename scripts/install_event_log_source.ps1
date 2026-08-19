<#
Registers the source used by core.audit.WindowsEventLogWriter.
Run once in an elevated PowerShell. This changes only the local Event Log
source registration; it does not start the Broker or change its identity.
#>
[CmdletBinding()]
param()

$source = 'OpsAgent Broker'
$logName = 'Application'

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw '请以管理员身份运行 PowerShell，再执行此脚本。'
}

if ([System.Diagnostics.EventLog]::SourceExists($source)) {
    Write-Host "Event Log source already exists: $source"
    exit 0
}

New-EventLog -LogName $logName -Source $source
Write-Host "Registered Event Log source '$source' in '$logName'. Restart the Broker if it is running."
