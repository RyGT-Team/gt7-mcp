# gt7-direct.ps1 - starts GT7.exe in the shared GT Sport/GT7 folder (no nsys) with the environment
# the RyGT launcher gives it (loader/Gt7Pages.cs StartGameGt7, settings from user\custom_configs\CUSA24769.json:
# PS4 Pro mode on a 1080p TV, 60 fps race lock, 100 GB driver cache). The launcher itself can't run under nsys
$root = $env:GT7_ROOT  # set by server.py: GT7_ROOT, or the GTSport-Ryty-shadGT folder next to this repo
Get-ChildItem env: | Where-Object { $_.Name -match '^(SHADGT_|SHARED_|RYGT_|RYTY_)' } |
    ForEach-Object { Remove-Item "env:$($_.Name)" }
Remove-Item env:VK_LOADER_LAYERS_DISABLE -ErrorAction SilentlyContinue
$env:RYGT_LOG_DIRECTORY = Join-Path $root 'logs\CUSA24769'
$env:SHADGT_GAME = 'gt7'
$env:SHADGT_SCRIPTS = '0'
$env:RYTY_INTEROP_BASE = '8000000000'
$env:RYGT_NATIVE_INPLACE_RANGES = '1020000000+412000,200000000+8000000'
$env:RYGT_NATIVE_INPLACE_FROM = 'e000000000'
$env:SHADGT_FPS_LOCK = '60'
$env:RYGT_DRIVER_CACHE_MAX_MB = '102400'
$env:RYGT_AMD_SINGLE_SAMPLE_BARYCENTRIC = '0'
$env:RYGT_DLSSG_FRAMES = '1'
$env:RYGT_UPSCALE_QUALITY = 'auto'
$env:RYGT_TEXTURE_LOD_BIAS = '0'
$env:RYGT_NEO = '1'
$env:RYGT_NEO_TV = '1080'

Set-Location $root
Start-Process -FilePath (Join-Path $root "GT7.exe") -WorkingDirectory $root
