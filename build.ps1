# Clean one-shot build. Run from the project folder with the venv active:
#   .\build.ps1
$ErrorActionPreference = "SilentlyContinue"

# 1. Stop a running copy that could lock files in dist/
Stop-Process -Name "BackgroundRemover" -Force

# 2. Remove partial/corrupted model files from failed downloads
Remove-Item -Path "$env:USERPROFILE\.cache\fast_rmbg\*.part", "$env:USERPROFILE\.cache\fast_rmbg\*_optimized.onnx" -Force

# 3. Remove old spec files and build output
Remove-Item -Path "BackgroundRemover.spec", "app.spec" -Force
Remove-Item -Path "build", "dist" -Recurse -Force

# 4. Fresh PyInstaller build
$ErrorActionPreference = "Continue"
pyinstaller --noconfirm --clean --noconsole --onedir `
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module transformers `
    --exclude-module timm `
    --exclude-module scipy `
    --exclude-module matplotlib `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --name "BackgroundRemover" `
    app.py

if ($LASTEXITCODE -eq 0) { Write-Host "`nDone: dist\BackgroundRemover\BackgroundRemover.exe" }
else { Write-Host "`nBuild failed." }
