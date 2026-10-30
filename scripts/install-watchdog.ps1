param([ValidateSet('Interactive', 'S4U')][string]$LogonType = 'Interactive')
$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python.exe).Source
$pythonWindowless = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (!(Test-Path -LiteralPath $pythonWindowless)) { throw 'pythonw.exe is required for hidden scheduled tasks.' }
$user = "$env:USERDOMAIN\$env:USERNAME"
$backupDir = Join-Path $env:LOCALAPPDATA ('orb-bot-task-backups\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -WakeToRun -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 8) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType $LogonType
$weekdays = @('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday')
$tasks = @(
    @{ Name='ORB watchdog morning'; Mode='morning'; At='08:45'; Interval=5; Duration=190 },
    @{ Name='ORB watchdog close'; Mode='close'; At='13:00'; Interval=15; Duration=165 },
    @{ Name='ORB watchdog eod'; Mode='eod'; At='17:30'; Interval=30; Duration=360 },
    @{ Name='ORB check ready'; Mode='check-ready'; At='09:20'; Interval=0; Duration=0 },
    @{ Name='ORB check morning'; Mode='check-morning'; At='12:25'; Interval=0; Duration=0 },
    @{ Name='ORB check close'; Mode='check-close'; At='16:25'; Interval=0; Duration=0 }
)
foreach ($item in $tasks) {
    $existing = Get-ScheduledTask -TaskName $item.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Export-ScheduledTask -TaskName $item.Name | Set-Content -LiteralPath (Join-Path $backupDir ($item.Name + '.xml')) -Encoding UTF8
    }
    $trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $weekdays -At $item.At
    if ($item.Interval -gt 0) {
        $repeat = New-ScheduledTaskTrigger -Once -At $item.At `
            -RepetitionInterval (New-TimeSpan -Minutes $item.Interval) `
            -RepetitionDuration (New-TimeSpan -Minutes $item.Duration)
        $trigger.Repetition = $repeat.Repetition
    }
    $action = New-ScheduledTaskAction -Execute $pythonWindowless `
        -Argument ('"' + (Join-Path $projectDir 'watchdog.py') + '" ' + $item.Mode) -WorkingDirectory $projectDir
    Register-ScheduledTask -TaskName $item.Name -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Write-Output ($item.Name + ': installed (' + $LogonType + ')')
}
Write-Output ('Previous task definitions: ' + $backupDir)

# Independent login helper remains useful when Windows refuses scheduled starts.
$startupPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'ORB watchdog.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($startupPath)
$shortcut.TargetPath = $pythonWindowless
$shortcut.Arguments = '"' + (Join-Path $projectDir 'watchdog.py') + '" daemon'
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = 'Independent ORB paper-trading workflow watchdog'
$shortcut.Save()
Start-Process -FilePath $pythonWindowless -ArgumentList ('"' + (Join-Path $projectDir 'watchdog.py') + '"'), 'daemon' -WorkingDirectory $projectDir -WindowStyle Hidden
Write-Output ('Independent login helper: ' + $startupPath)
