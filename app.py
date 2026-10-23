import ctypes
import gc
import hashlib
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from datetime import datetime
from io import BytesIO
from pathlib import Path

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

import numpy as np
import onnxruntime as ort
from flask import Flask, jsonify, render_template, request, send_file
from huggingface_hub import hf_hub_download
from PIL import Image, ImageFilter, ImageOps

# =====================================================================
# INTERNAL DIAGNOSTIC LOGGER & 64-BIT WINDOWS RAM MONITOR
# =====================================================================
LOG_BUFFER = []
LOG_LOCK = threading.Lock()


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def get_ram_mb() -> float:
    """Accurate 64-bit Windows WorkingSetSize reader."""
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel32.GetCurrentProcess()

        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int

        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        pass
    return -1.0


def log_event(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    ram = get_ram_mb()
    entry = f"[{ts}] [PID:{os.getpid()}] [RAM:{ram:.1f}MB] {msg}"
    with LOG_LOCK:
        LOG_BUFFER.append(entry)
        if len(LOG_BUFFER) > 500:
            LOG_BUFFER.pop(0)
    try:
        print(entry, flush=True)
    except Exception:
        pass


BASE_DIR = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)

CACHE_DIR = Path.home() / ".cache" / "fast_rmbg"
DOWNLOADS_DIR = Path.home() / "Downloads"

# =====================================================================
# MODEL REGISTRY & FIRST-TIME LOADING STATE TRACKER
# =====================================================================
MODELS = {
    "u2netp": {
        "label": "U2Net-P (Fastest, 4MB)",
        "res": (320, 320),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "filename": "u2netp.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
        "min_bytes": 3_000_000,
    },
    "silueta": {
        "label": "Silueta (Portraits, 43MB)",
        "res": (320, 320),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "filename": "silueta.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/silueta.onnx",
        "min_bytes": 40_000_000,
    },
    "u2net": {
        "label": "U2Net General (176MB)",
        "res": (320, 320),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "filename": "u2net.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
        "min_bytes": 160_000_000,
    },
    "u2net_human_seg": {
        "label": "U2Net Human Seg (176MB)",
        "res": (320, 320),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "filename": "u2net_human_seg.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
        "min_bytes": 160_000_000,
    },
    "isnet_general": {
        "label": "ISNet General HD (178MB)",
        "res": (1024, 1024),
        "mean": [0.5, 0.5, 0.5],
        "std": [1.0, 1.0, 1.0],
        "filename": "isnet-general-use.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
        "min_bytes": 160_000_000,
    },
    "isnet_anime": {
        "label": "ISNet Anime HD (176MB)",
        "res": (1024, 1024),
        "mean": [0.5, 0.5, 0.5],
        "std": [1.0, 1.0, 1.0],
        "filename": "isnet-anime.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-anime.onnx",
        "min_bytes": 160_000_000,
    },
    "birefnet_lite": {
        "label": "BiRefNet Lite HD (224MB)",
        "res": (1024, 1024),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "filename": "BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "min_bytes": 200_000_000,
    },
    "rmbg14": {
        "label": "BRIA RMBG-1.4 (176MB)",
        "res": (1024, 1024),
        "mean": [0.5, 0.5, 0.5],
        "std": [1.0, 1.0, 1.0],
        "hf_repo": "briaai/RMBG-1.4",
        "hf_file": "onnx/model.onnx",
        "min_bytes": 160_000_000,
    },
    "rmbg20": {
        "label": "BRIA RMBG-2.0 FP16 (514MB)",
        "res": (1024, 1024),
        "mean": [0.485, 0.456, 0.406],
        "std": [0.229, 0.224, 0.225],
        "hf_repo": "briaai/RMBG-2.0",
        "hf_file": "onnx/model_fp16.onnx",
        "min_bytes": 450_000_000,
    },
    "manga_bw": {
        "label": "Manga B&W Line-Art (Instant)",
        "res": None,
    },
}

current_model_key = None
ort_session = None
session_lock = threading.RLock()

MODEL_STATE_LOCK = threading.Lock()
MODEL_STATE = {
    "state": "idle",  # idle | downloading | initializing | ready | error
    "model_key": None,
    "progress_pct": 0,
    "downloaded_mb": 0.0,
    "total_mb": 0.0,
    "message": "Ready",
}

LAST_CACHE = {
    "file_hash": None,
    "filename": None,
    "model_key": None,
    "rgb_image": None,
    "raw_mask": None,
}


def update_model_state(
    state: str,
    model_key: str = None,
    progress_pct: int = 0,
    downloaded_mb: float = 0.0,
    total_mb: float = 0.0,
    message: str = "",
):
    with MODEL_STATE_LOCK:
        MODEL_STATE["state"] = state
        if model_key is not None:
            MODEL_STATE["model_key"] = model_key
        MODEL_STATE["progress_pct"] = progress_pct
        MODEL_STATE["downloaded_mb"] = round(downloaded_mb, 1)
        MODEL_STATE["total_mb"] = round(total_mb, 1)
        MODEL_STATE["message"] = message


def is_model_cached(model_key: str) -> bool:
    if model_key not in MODELS:
        return False
    if model_key == "manga_bw":
        return True
    cfg = MODELS[model_key]
    min_bytes = cfg.get("min_bytes", 1_000_000)

    if "filename" in cfg:
        path = CACHE_DIR / cfg["filename"]
        return path.exists() and path.stat().st_size >= min_bytes

    if "hf_repo" in cfg:
        try:
            local_path = hf_hub_download(
                cfg["hf_repo"], cfg["hf_file"], local_files_only=True
            )
            return os.path.exists(local_path) and os.path.getsize(local_path) >= min_bytes
        except Exception:
            return False
    return False


def download_github_model_atomic(model_key: str, filename: str, url: str, min_bytes: int) -> str:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target_path = CACHE_DIR / filename
    temp_path = CACHE_DIR / f"{filename}.part"

    # Remove corrupted/incomplete target files from previous crashed runs
    if target_path.exists():
        if target_path.stat().st_size >= min_bytes:
            return str(target_path)
        log_event(f"Removing corrupted cached model {filename} ({target_path.stat().st_size} bytes)")
        try:
            target_path.unlink()
        except OSError:
            pass

    log_event(f"Starting atomic first-time download for {filename} from {url}...")
    update_model_state("downloading", model_key, 0, 0.0, 0.0, f"Downloading {model_key}...")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) BackgroundRemover/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            total_bytes = int(resp.headers.get("Content-Length", 0))
            total_mb = total_bytes / (1024 * 1024) if total_bytes else 0.0
            downloaded = 0
            chunk_size = 256 * 1024  # 256 KB chunks

            with open(temp_path, "wb") as out_file:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    dl_mb = downloaded / (1024 * 1024)
                    pct = int((downloaded * 100) / total_bytes) if total_bytes else 0
                    msg = (
                        f"Downloading {model_key}: {dl_mb:.1f} / {total_mb:.1f} MB ({pct}%)"
                        if total_bytes
                        else f"Downloading {model_key}: {dl_mb:.1f} MB"
                    )
                    update_model_state("downloading", model_key, pct, dl_mb, total_mb, msg)

        if not temp_path.exists() or temp_path.stat().st_size < min_bytes:
            raise IOError(f"Downloaded file for {model_key} is incomplete or corrupted.")

        # Atomic rename so interrupted downloads never masquerade as valid models
        os.replace(str(temp_path), str(target_path))
        log_event(f"Successfully downloaded and verified {filename}")
        return str(target_path)

    except Exception as exc:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        update_model_state("error", model_key, 0, 0.0, 0.0, f"Download failed: {exc}")
        raise RuntimeError(f"Failed to download {model_key}: {exc}") from exc


def resolve_model_file(model_key: str) -> str:
    if model_key not in MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    cfg = MODELS[model_key]
    min_bytes = cfg.get("min_bytes", 1_000_000)

    if "filename" in cfg:
        return download_github_model_atomic(model_key, cfg["filename"], cfg["url"], min_bytes)

    if "hf_repo" in cfg:
        repo = cfg["hf_repo"]
        hf_file = cfg["hf_file"]
        try:
            path = hf_hub_download(repo, hf_file, local_files_only=True)
            if os.path.exists(path) and os.path.getsize(path) >= min_bytes:
                return path
        except Exception:
            pass

        log_event(f"First-time download from HuggingFace: {repo} ({hf_file})...")
        update_model_state(
            "downloading",
            model_key,
            0,
            0.0,
            0.0,
            f"Downloading {model_key} from HuggingFace (first run)...",
        )
        path = hf_hub_download(repo, hf_file, local_files_only=False)
        return path

    raise ValueError(f"No file resolver configured for model: {model_key}")


def get_or_load_session(model_key: str):
    global ort_session, current_model_key
    with session_lock:
        if ort_session is not None and current_model_key == model_key:
            update_model_state("ready", model_key, 100, 0.0, 0.0, f"{model_key} ready")
            return ort_session

        if ort_session is not None:
            log_event(f"Unloading previous model ({current_model_key}) to free RAM...")
            del ort_session
            ort_session = None
            current_model_key = None
            gc.collect()

        t0 = time.perf_counter()
        model_path = resolve_model_file(model_key)

        update_model_state(
            "initializing",
            model_key,
            100,
            0.0,
            0.0,
            f"Initializing {model_key} in memory...",
        )

        opts = ort.SessionOptions()
        # Keep thread count reasonable for 2-4 core CPUs to prevent UI lockups
        opts.intra_op_num_threads = min(4, max(2, (os.cpu_count() or 4) // 2))
        opts.inter_op_num_threads = 1
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC

        log_event(f"Initializing ONNX session for '{model_key}'...")
        try:
            ort_session = ort.InferenceSession(
                model_path, sess_options=opts, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            # If the cached model file is unreadable by ONNX, delete it so next attempt re-downloads cleanly
            log_event(f"ONNX initialization failed for {model_path}: {exc}. Purging broken file.")
            try:
                if os.path.exists(model_path):
                    os.remove(model_path)
            except OSError:
                pass
            update_model_state("error", model_key, 0, 0.0, 0.0, f"Model init error: {exc}")
            raise

        current_model_key = model_key
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log_event(f"Model '{model_key}' ready in {elapsed_ms:.0f}ms")
        update_model_state("ready", model_key, 100, 0.0, 0.0, f"{model_key} ready")
        return ort_session


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -88.0, 88.0)))


def run_inference_mask(img: Image.Image, model_key: str) -> np.ndarray:
    t0 = time.perf_counter()

    if model_key == "manga_bw":
        gray = img.convert("L")
        arr = np.asarray(gray, dtype=np.float32) / 255.0
        mask = np.clip((1.0 - arr) * 1.4, 0.0, 1.0)
        log_event(f"[manga_bw] Line-art mask extracted in {(time.perf_counter() - t0)*1000:.1f}ms")
        return mask

    cfg = MODELS[model_key]
    sess = get_or_load_session(model_key)

    resized = img.resize(cfg["res"], Image.Resampling.BILINEAR)
    arr = np.asarray(resized, dtype=np.float32) / 255.0

    mean = np.array(cfg["mean"], dtype=np.float32)
    std = np.array(cfg["std"], dtype=np.float32)
    arr = (arr - mean) / std
    tensor = np.expand_dims(np.transpose(arr, (2, 0, 1)), axis=0)

    input_meta = sess.get_inputs()[0]
    if "float16" in input_meta.type:
        tensor = tensor.astype(np.float16)

    with session_lock:
        outputs = sess.run(None, {input_meta.name: tensor})

    del tensor
    raw = outputs[-1] if model_key in ("rmbg20", "birefnet_lite") else outputs[0]
    mask = np.squeeze(raw).astype(np.float32)
    del outputs, raw
    gc.collect()

    if mask.min() < 0.0 or mask.max() > 1.0:
        mask = sigmoid(mask)

    ma, mi = float(mask.max()), float(mask.min())
    if ma > mi:
        mask = (mask - mi) / (ma - mi)

    log_event(f"[{model_key}] AI inference finished in {(time.perf_counter() - t0)*1000:.1f}ms")
    return mask


def apply_mask_parameters(
    img: Image.Image,
    raw_mask: np.ndarray,
    feather: float = 1.0,
    threshold: float = 0.15,
    contrast: float = 1.2,
    erode_dilate: int = 0,
) -> Image.Image:
    t0 = time.perf_counter()
    orig_w, orig_h = img.size

    m = raw_mask.copy()
    if threshold > 0.0:
        denom = max(0.05, 1.0 - threshold)
        m = np.clip((m - threshold) / denom, 0.0, 1.0)

    if abs(contrast - 1.0) > 0.01:
        m = np.clip((m - 0.5) * contrast + 0.5, 0.0, 1.0)

    mask_uint8 = (m * 255.0).astype(np.uint8)
    mask_img = Image.fromarray(mask_uint8, mode="L").resize(
        (orig_w, orig_h), Image.Resampling.BILINEAR
    )

    if erode_dilate < 0:
        size = abs(int(erode_dilate)) * 2 + 1
        mask_img = mask_img.filter(ImageFilter.MinFilter(size))
    elif erode_dilate > 0:
        size = abs(int(erode_dilate)) * 2 + 1
        mask_img = mask_img.filter(ImageFilter.MaxFilter(size))

    if feather > 0.0:
        mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=float(feather)))

    rgba = img.copy()
    rgba.putalpha(mask_img)
    log_event(
        f"Mask parameters applied (feather={feather}, thresh={threshold}, contrast={contrast}, shift={erode_dilate}) in {(time.perf_counter() - t0)*1000:.1f}ms"
    )
    return rgba


def get_unique_save_path(base_name: str, ext: str) -> Path:
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    candidate = DOWNLOADS_DIR / f"{base_name}_no_bg.{ext}"
    counter = 1
    while candidate.exists():
        candidate = DOWNLOADS_DIR / f"{base_name}_no_bg ({counter}).{ext}"
        counter += 1
    return candidate


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/model-status", methods=["GET"])
def model_status():
    cached_map = {k: is_model_cached(k) for k in MODELS}
    with MODEL_STATE_LOCK:
        state_copy = dict(MODEL_STATE)
    return jsonify({
        "active_model": current_model_key,
        "status": state_copy,
        "cached": cached_map,
    })


@app.route("/logs", methods=["GET"])
def get_logs():
    with LOG_LOCK:
        text = "\n".join(LOG_BUFFER)
    return jsonify({"logs": text, "pid": os.getpid(), "ram_mb": round(get_ram_mb(), 1)})


@app.route("/client-log", methods=["POST"])
def client_log():
    data = request.get_json(silent=True) or {}
    log_event(f"[JS] {data.get('msg', '')}")
    return jsonify({"ok": True})


@app.route("/remove-bg", methods=["POST"])
def remove_bg():
    req_t0 = time.perf_counter()
    uploaded = request.files.get("image")
    out_format = request.form.get("format", "png").lower()
    model_key = request.form.get("model", "u2netp")
    if model_key not in MODELS:
        model_key = "u2netp"
    if out_format not in ("png", "webp"):
        out_format = "png"

    feather = float(request.form.get("feather", 1.0))
    threshold = float(request.form.get("threshold", 0.15))
    contrast = float(request.form.get("contrast", 1.2))
    erode_dilate = int(float(request.form.get("erode_dilate", 0)))
    reuse_mask = request.form.get("reuse_mask", "false") == "true"
    save_to_disk = request.form.get("save_to_disk", "false") == "true"

    if not uploaded and LAST_CACHE["rgb_image"] is None:
        return jsonify({"error": "Choose an image first."}), 400

    try:
        file_bytes = uploaded.read() if uploaded else None
        file_hash = hashlib.md5(file_bytes).hexdigest() if file_bytes else LAST_CACHE["file_hash"]
        orig_filename = (
            Path(uploaded.filename or "image").stem
            if uploaded
            else (LAST_CACHE["filename"] or "image")
        )

        if (
            reuse_mask
            and LAST_CACHE["rgb_image"] is not None
            and LAST_CACHE["raw_mask"] is not None
            and LAST_CACHE["model_key"] == model_key
            and LAST_CACHE["file_hash"] == file_hash
        ):
            log_event("Reusing cached AI mask for instant parameter update!")
            rgb_img = LAST_CACHE["rgb_image"]
            raw_mask = LAST_CACHE["raw_mask"]
        else:
            if not file_bytes and LAST_CACHE["rgb_image"] is not None:
                rgb_img = LAST_CACHE["rgb_image"]
            else:
                with Image.open(BytesIO(file_bytes)) as img:
                    rgb_img = ImageOps.exif_transpose(img).convert("RGB")

            raw_mask = run_inference_mask(rgb_img, model_key)
            LAST_CACHE["file_hash"] = file_hash
            LAST_CACHE["filename"] = orig_filename
            LAST_CACHE["model_key"] = model_key
            LAST_CACHE["rgb_image"] = rgb_img
            LAST_CACHE["raw_mask"] = raw_mask

        result = apply_mask_parameters(
            rgb_img, raw_mask, feather, threshold, contrast, erode_dilate
        )

        output = BytesIO()
        if out_format == "webp":
            result.save(output, format="WEBP", quality=92, method=0)
            mimetype = "image/webp"
        else:
            result.save(output, format="PNG", compress_level=1)
            mimetype = "image/png"

        result.close()
        gc.collect()

        dl_name = f"{orig_filename}_no_bg.{out_format}"
        saved_path_str = ""

        if save_to_disk:
            save_path = get_unique_save_path(orig_filename, out_format)
            with open(save_path, "wb") as f:
                f.write(output.getvalue())
            dl_name = save_path.name
            saved_path_str = str(save_path)
            log_event(
                f"Exported {save_path.name} | Total request: {(time.perf_counter() - req_t0)*1000:.1f}ms"
            )
        else:
            log_event(
                f"Converted preview ({dl_name}) | Total request: {(time.perf_counter() - req_t0)*1000:.1f}ms"
            )

        output.seek(0)
        response = send_file(
            output, mimetype=mimetype, as_attachment=False, download_name=dl_name
        )
        if saved_path_str:
            response.headers["X-Saved-Path"] = saved_path_str
        return response

    except Exception as error:
        log_event(f"ERROR: {error}\n{traceback.format_exc()}")
        gc.collect()
        return jsonify({"error": str(error)}), 500


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def preload_default_model():
    """Only preload u2netp at startup if it is already cached on disk, avoiding silent background bandwidth/lock contention."""
    try:
        if is_model_cached("u2netp"):
            get_or_load_session("u2netp")
    except Exception as exc:
        log_event(f"Startup preload skipped: {exc}")


if __name__ == "__main__":
    PORT = get_free_port()
    APP_URL = f"http://127.0.0.1:{PORT}"
    log_event(f"=== APP STARTUP on {APP_URL} ===")

    threading.Thread(target=preload_default_model, daemon=True).start()

    def run_server():
        app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)

    try:
        import webview

        threading.Thread(target=run_server, daemon=True).start()
        webview.create_window(
            title="background remover",
            url=APP_URL,
            width=980,
            height=660,
            min_size=(680, 480),
            background_color="#2a2a2a",
        )
        webview.start()
    except ImportError:
        threading.Timer(0.5, lambda: webbrowser.open(APP_URL)).start()
        run_server()