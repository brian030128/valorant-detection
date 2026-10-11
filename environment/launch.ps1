param([switch]$Verify, [switch]$VerifyAll, [switch]$Capture, [string]$Character = "viper")
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$engine = Get-ChildItem -LiteralPath (Join-Path $workspaceRoot 'tools/godot') -Filter '*win64_console.exe' | Select-Object -First 1
if (-not $engine) { throw 'Portable Godot engine not found in tools/godot.' }
$engineArgs = @('--path', $PSScriptRoot, '--', "--character=$Character")
if ($Verify) { $engineArgs += '--verify' }
if ($VerifyAll) { $engineArgs += '--verify-all' }
if ($Capture) { $engineArgs += '--capture' }
& $engine.FullName @engineArgs
