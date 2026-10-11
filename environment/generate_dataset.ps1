param(
    [int]$Count = 10000,
    [int]$Start = 0,
    [string]$Output = '',
    [int]$GroupSize = 50
)
$workspaceRoot = Split-Path $PSScriptRoot -Parent
$engine = Join-Path $workspaceRoot 'tools/godot/Godot_v4.7.2-stable_win64_console.exe'
if (!$Output) { $Output = Join-Path $workspaceRoot 'datasets/valorant_synthetic_10k' }
$Output = [System.IO.Path]::GetFullPath($Output)
$arguments = @('--path', ('"' + $PSScriptRoot + '"'), 'res://dataset.tscn', '--', "--count=$Count", "--start=$Start", "--group-size=$GroupSize", ('"--output=' + $Output + '"'))
$process = Start-Process -FilePath $engine -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot "generation_${Start}_stdout.log") -RedirectStandardError (Join-Path $PSScriptRoot "generation_${Start}_stderr.log")
Write-Output "Renderer PID: $($process.Id)"
Write-Output "Dataset: $Output"
Write-Output "Progress: $PSScriptRoot/generation_${Start}_stdout.log"
