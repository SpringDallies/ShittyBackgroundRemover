# ShittyBackgroundRemover

The ultimate tool that removes shitty backgrounds once and for all.

A small offline desktop app (Flask + ONNX Runtime, shown in a native window) that removes image backgrounds on your CPU. No account, no cloud upload: your images stay on your PC.

## Features

- Import with a button, or **drag and drop** an image onto the window
- 10 models, from a fast general one to hair/fur and anime specialists
- Sliders for feather, threshold, contrast and shift, re-applied instantly without re-running the model
- Before/after compare slider, zoom and pan, and 4 preview backgrounds
- Export as PNG or WebP straight to your `Downloads` folder
- PNG, JPEG and WebP input, up to 25 MB

## Download (no Python needed)

Go to the [Releases](../../releases) page, download `BackgroundRemover-windows.zip`, extract it and run `BackgroundRemover.exe`.

If there is no release yet, use "Run from source" or "Build the .exe yourself" below.

## Run from source (Windows, PowerShell)

Needs Python 3.10 or newer.

```powershell
git clone https://github.com/SpringDallies/ShittyBackgroundRemover.git
cd ShittyBackgroundRemover
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

If PowerShell blocks the activate script, run `Set-ExecutionPolicy -Scope Process Bypass` once and try again.

## Build the .exe yourself

```powershell
pip install -r requirements-build.txt
.\build.ps1
```

The result is `dist\BackgroundRemover\BackgroundRemover.exe`. Zip the whole `dist\BackgroundRemover` folder to share it, because the `.exe` needs the files next to it.

## First run

Models are not bundled. Each one is downloaded the first time you pick it and cached in `%USERPROFILE%\.cache\fast_rmbg`, so the first conversion with a model needs internet and takes longer. The small `u2netp` model is a good one to start with. After that, models you've already used work offline.

## Notes

- Built and tested on Windows. The app window uses the Microsoft Edge WebView2 runtime, which is already on current Windows 10/11. If it's missing, the app falls back to opening in your default browser.
- Exports are saved to `%USERPROFILE%\Downloads`.
- The heavy models (BiRefNet, RMBG) use a lot of RAM and are slow on CPU.

## Project layout

```
app.py              backend and model handling
templates/index.html
static/             style.css, script.js, JetBrainsMono.woff2
requirements.txt    runtime dependencies
build.ps1           clean PyInstaller build
```
