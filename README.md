# shitty background remover (sbr)

A small offline desktop app that rips backgrounds off your images on your cpu, images are stored locally. 

<img width="969" height="626" alt="image" src="https://github.com/user-attachments/assets/8c9a63d1-caac-4fe4-a64d-3d287ba84601" />


## features

- Import with a button, or drag and drop
- Added 10 models currently ranging from general/people to anime/artwork
- Adjustments apply almost instantly
- Export as png or webp (better png icl) straight to your `Downloads` folder, because that's where files go to die (i wont add an option to change export location anytime soon, good luck)

## install

go to the [Releases](../../releases) page, download `BackgroundRemover-windows.zip`, extract it, and run `BackgroundRemover.exe`. 

## run from source (windows powershell)

needs python 3.10 or newer. don't ask why.

```powershell
git clone https://github.com/SpringDallies/ShittyBackgroundRemover.git
cd ShittyBackgroundRemover
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

if powershell blocks the activate script, try `Set-ExecutionPolicy -Scope Process Bypass`

## Build the exe yourself

```powershell
pip install -r requirements-build.txt
.\build.ps1
```

the exe is saved in: `dist\BackgroundRemover\BackgroundRemover.exe`.

## first stage

each one downloads the first time you pick it and gets cached in `%USERPROFILE%\.cache\fast_rmbg`, so the first conversion with a model needs internet and takes longer. The small `u2netp` model is a good one to start with. After that, models you've already used work offline. 

## notes

- Built and tested on Windows. the app window uses the microsoft webview2 runtime, which is already on current Windows 10/11. if it's missing, the app falls back to opening in your default browser.
- Exports are saved to `%USERPROFILE%\Downloads`.
*on my intel-i3* The heavy models (BiRefNet, RMBG) use a lot of RAM and are slow on CPU, I've optmized it as much as i could.
