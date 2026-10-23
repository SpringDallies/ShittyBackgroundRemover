const input = document.getElementById("image-input");
const insertButton = document.getElementById("insert-button");
const exportButton = document.getElementById("export-button");
const saveDownloadsButton = document.getElementById("save-downloads-button");
const cancelExportButton = document.getElementById("cancel-export-button");
const compareButton = document.getElementById("compare-button");
const resetSettingsButton = document.getElementById("reset-settings-button");
const bgToggleButton = document.getElementById("bg-toggle-button");

const previewStage = document.getElementById("preview-stage");
const zoomContainer = document.getElementById("zoom-container");
const previewImage = document.getElementById("preview-image");
const compareOriginal = document.getElementById("compare-original");
const compareDivider = document.getElementById("compare-divider");

const formatButtons = document.querySelectorAll(".format-button[data-format]");
const sumthingContainer = document.getElementById("sumthing");
const statusBox = document.getElementById("status");
const processingText = document.getElementById("processing-text");
const processingWord = document.getElementById("processing-word");
const processingEta = document.getElementById("processing-eta");

const modelSelect = document.getElementById("model-select");
const paramFeather = document.getElementById("param-feather");
const paramThreshold = document.getElementById("param-threshold");
const paramContrast = document.getElementById("param-contrast");
const paramShift = document.getElementById("param-shift");

const valFeather = document.getElementById("val-feather");
const valThreshold = document.getElementById("val-threshold");
const valContrast = document.getElementById("val-contrast");
const valShift = document.getElementById("val-shift");

const DEFAULTS = {
    feather: "1.0",
    threshold: "0.15",
    contrast: "1.2",
    shift: "0",
};

const BG_MODES = [
    { cls: "bg-dark", label: "dark" },
    { cls: "bg-dark-checkered", label: "dark checkered" },
    { cls: "bg-white-checkered", label: "white checkered" },
    { cls: "bg-white", label: "white" },
];

let bgModeIndex = 0;
let selectedFile = null;
let selectedFormat = "png";
let originalURL = null;
let previewURL = null;
let isProcessing = false;
let hasProcessedCurrentImage = false;

let isComparing = false;
let comparePercent = 50;
let isDraggingCompare = false;

let zoomLevel = 1;
let panX = 0;
let panY = 0;
let isPanning = false;
let panStartX = 0;
let panStartY = 0;

let cachedModels = {};
let statusPollTimer = null;

const MAX_FILE_SIZE = 25 * 1024 * 1024;
const ALLOWED_TYPES = ["image/png", "image/jpeg", "image/webp"];

const MODEL_ETAS = {
    u2netp: "est. ~1–2s",
    silueta: "est. ~2–3s",
    u2net: "est. ~2–4s",
    u2net_human_seg: "est. ~2–4s",
    isnet_anime: "est. ~4–6s",
    manga_bw: "instant",
    isnet_general: "est. ~4–6s",
    birefnet_lite: "est. ~6–9s",
    rmbg14: "est. ~4–6s",
    rmbg20: "est. ~15–25s",
};

function setStatus(text) {
    if (statusBox) statusBox.textContent = text;
}

if (processingWord) {
    processingWord.innerHTML = "";
    [..."enshittifying"].forEach((char, index) => {
        const letter = document.createElement("span");
        letter.textContent = char;
        letter.style.setProperty("--i", index);
        processingWord.appendChild(letter);
    });
}

// Background Switcher
bgToggleButton?.addEventListener("click", () => {
    previewStage.classList.remove(BG_MODES[bgModeIndex].cls);
    bgModeIndex = (bgModeIndex + 1) % BG_MODES.length;
    const next = BG_MODES[bgModeIndex];
    previewStage.classList.add(next.cls);
    bgToggleButton.textContent = `[bg: ${next.label}]`;
    setStatus(`background set to ${next.label}`);
});

// Compare Slider
function setComparePosition(pct) {
    comparePercent = Math.max(0, Math.min(100, pct));
    if (compareOriginal) {
        compareOriginal.style.clipPath = `inset(0 ${100 - comparePercent}% 0 0)`;
    }
    if (compareDivider) {
        compareDivider.style.left = `${comparePercent}%`;
    }
}

function updateCompareOverlay() {
    const active = isComparing && hasProcessedCurrentImage && Boolean(originalURL);
    compareOriginal?.classList.toggle("hidden", !active);
    compareDivider?.classList.toggle("hidden", !active);
    if (compareButton) {
        compareButton.classList.toggle("active", active);
        compareButton.setAttribute("aria-pressed", String(active));
    }
    if (active) {
        setComparePosition(comparePercent);
    }
}

function updateCompareFromPointer(clientX) {
    if (!zoomContainer) return;
    const rect = zoomContainer.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pct = ((clientX - rect.left) / rect.width) * 100;
    setComparePosition(pct);
}

compareDivider?.addEventListener("mousedown", e => {
    e.stopPropagation();
    e.preventDefault();
    isDraggingCompare = true;
});

compareButton?.addEventListener("click", () => {
    if (!hasProcessedCurrentImage || isProcessing) return;
    isComparing = !isComparing;
    updateCompareOverlay();
    setStatus(isComparing ? "compare slider active" : "compare slider off");
});

// Zoom & Pan
function clampPan() {
    if (zoomLevel <= 1) {
        panX = 0;
        panY = 0;
        return;
    }
    const baseW = zoomContainer ? zoomContainer.offsetWidth : 0;
    const baseH = zoomContainer ? zoomContainer.offsetHeight : 0;
    const maxX = Math.max(0, (baseW * (zoomLevel - 1)) / 2);
    const maxY = Math.max(0, (baseH * (zoomLevel - 1)) / 2);
    panX = Math.max(-maxX, Math.min(maxX, panX));
    panY = Math.max(-maxY, Math.min(maxY, panY));
}

function applyZoomTransform() {
    if (!zoomContainer) return;
    clampPan();
    zoomContainer.style.transform = `translate(${panX}px, ${panY}px) scale(${zoomLevel})`;
    previewStage.style.cursor = zoomLevel > 1 ? (isPanning ? "grabbing" : "grab") : "default";
}

function resetZoom() {
    zoomLevel = 1;
    panX = 0;
    panY = 0;
    applyZoomTransform();
}

previewStage.addEventListener(
    "wheel",
    e => {
        if (!selectedFile) return;
        e.preventDefault();

        const oldZoom = zoomLevel;
        const step = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        const newZoom = Math.min(8.0, Math.max(1.0, oldZoom * step));
        if (newZoom === oldZoom) return;

        const rect = previewStage.getBoundingClientRect();
        const cursorX = e.clientX - (rect.left + rect.width / 2);
        const cursorY = e.clientY - (rect.top + rect.height / 2);

        const ratio = newZoom / oldZoom;
        panX = cursorX - (cursorX - panX) * ratio;
        panY = cursorY - (cursorY - panY) * ratio;
        zoomLevel = newZoom;

        applyZoomTransform();
        setStatus(zoomLevel === 1 ? "zoom: 100%" : `zoom: ${Math.round(zoomLevel * 100)}%`);
    },
    { passive: false }
);

previewStage.addEventListener("mousedown", e => {
    if (e.button !== 0 || isDraggingCompare || !selectedFile) return;
    if (zoomLevel > 1) {
        e.preventDefault();
        isPanning = true;
        panStartX = e.clientX - panX;
        panStartY = e.clientY - panY;
        applyZoomTransform();
    }
});

window.addEventListener("mousemove", e => {
    if (isDraggingCompare) {
        updateCompareFromPointer(e.clientX);
    } else if (isPanning) {
        panX = e.clientX - panStartX;
        panY = e.clientY - panStartY;
        applyZoomTransform();
    }
});

window.addEventListener("mouseup", () => {
    if (isDraggingCompare) isDraggingCompare = false;
    if (isPanning) {
        isPanning = false;
        applyZoomTransform();
    }
});

// Model Status & Cache
async function refreshModelCacheStatus() {
    try {
        const res = await fetch("/model-status");
        if (!res.ok) return;
        const data = await res.json();
        cachedModels = data.cached || {};
    } catch {}
}

function startStatusPolling(modelKey) {
    stopStatusPolling();
    statusPollTimer = setInterval(async () => {
        try {
            const res = await fetch("/model-status");
            if (!res.ok) return;
            const data = await res.json();
            cachedModels = data.cached || cachedModels;
            const st = data.status;
            if (!st) return;

            if (st.state === "downloading") {
                setStatus(st.message || `downloading ${modelKey}...`);
                if (processingEta) {
                    processingEta.textContent = st.progress_pct > 0
                        ? `${st.progress_pct}%`
                        : "downloading...";
                }
            } else if (st.state === "initializing") {
                setStatus(st.message || `initializing ${modelKey}...`);
                if (processingEta) {
                    processingEta.textContent = "loading model...";
                }
            } else if (st.state === "ready" && st.model_key === modelKey) {
                setStatus(`running ${modelKey}...`);
                if (processingEta) {
                    processingEta.textContent = MODEL_ETAS[modelKey] || "processing...";
                }
            }
        } catch {}
    }, 350);
}

function stopStatusPolling() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
        statusPollTimer = null;
    }
}

function setProcessing(state) {
    isProcessing = state;
    insertButton.disabled = state;
    exportButton.disabled = state || !selectedFile;
    if (modelSelect) modelSelect.disabled = state;
    if (resetSettingsButton) resetSettingsButton.disabled = state;
    if (saveDownloadsButton) {
        saveDownloadsButton.disabled = state || !hasProcessedCurrentImage;
    }
    if (compareButton) {
        compareButton.disabled = state || !hasProcessedCurrentImage;
    }
    processingText?.classList.toggle("hidden", !state);
}

function setPreviewBlob(blobOrFile) {
    if (previewURL) URL.revokeObjectURL(previewURL);
    previewURL = URL.createObjectURL(blobOrFile);
    previewImage.src = previewURL;
    previewImage.classList.remove("hidden");
}

function selectImage(file) {
    if (!file || isProcessing) return;

    if (!ALLOWED_TYPES.includes(file.type)) {
        setStatus(`Unsupported type: ${file.type}`);
        return;
    }

    if (file.size > MAX_FILE_SIZE) {
        setStatus("File exceeds 25MB limit");
        return;
    }

    selectedFile = file;
    hasProcessedCurrentImage = false;
    isComparing = false;
    comparePercent = 50;
    resetZoom();

    if (saveDownloadsButton) saveDownloadsButton.disabled = true;
    if (compareButton) compareButton.disabled = true;

    if (originalURL) URL.revokeObjectURL(originalURL);
    originalURL = URL.createObjectURL(file);
    if (compareOriginal) compareOriginal.src = originalURL;

    setPreviewBlob(file);
    updateCompareOverlay();
    exportButton.disabled = false;
    setStatus(`loaded: ${file.name} (${(file.size / 1024).toFixed(0)} KB)`);
}

// Export options toggle: hide export/compare, show png/webp/cancel
function showExportOptions(show) {
    compareButton?.classList.toggle("hidden", show);
    saveDownloadsButton?.classList.toggle("hidden", show);
    formatButtons.forEach(btn => btn.classList.toggle("hidden", !show));
    cancelExportButton?.classList.toggle("hidden", !show);
}

saveDownloadsButton?.addEventListener("click", () => {
    if (!hasProcessedCurrentImage || isProcessing) return;
    showExportOptions(true);
    setStatus("select export format");
});

cancelExportButton?.addEventListener("click", () => {
    showExportOptions(false);
    setStatus("export cancelled");
});

formatButtons.forEach(button => {
    button.addEventListener("click", () => {
        selectedFormat = button.dataset.format;
        formatButtons.forEach(item => {
            const active = item === button;
            item.classList.toggle("active", active);
            item.setAttribute("aria-pressed", String(active));
        });
        showExportOptions(false);
        runProcess(true, true);
    });
});

async function runProcess(reuseMask = false, saveToDisk = false) {
    if (!selectedFile || isProcessing) return;

    const modelKey = modelSelect ? modelSelect.value : "u2netp";
    const isFirstRun = !reuseMask && !cachedModels[modelKey] && modelKey !== "manga_bw";

    if (processingEta) {
        processingEta.textContent = reuseMask
            ? "updating mask..."
            : isFirstRun
            ? "first-run download..."
            : (MODEL_ETAS[modelKey] || "processing...");
    }

    const t0 = performance.now();
    setProcessing(true);

    if (saveToDisk) {
        setStatus(`saving to Downloads (${selectedFormat})...`);
    } else if (reuseMask) {
        setStatus("applying parameters...");
    } else if (isFirstRun) {
        setStatus(`downloading/initializing ${modelKey}... (first run)`);
        startStatusPolling(modelKey);
    } else {
        setStatus(`running ${modelKey}...`);
        startStatusPolling(modelKey);
    }

    try {
        const formData = new FormData();
        formData.append("image", selectedFile);
        formData.append("format", selectedFormat);
        formData.append("model", modelKey);
        formData.append("feather", paramFeather ? paramFeather.value : DEFAULTS.feather);
        formData.append("threshold", paramThreshold ? paramThreshold.value : DEFAULTS.threshold);
        formData.append("contrast", paramContrast ? paramContrast.value : DEFAULTS.contrast);
        formData.append("erode_dilate", paramShift ? paramShift.value : DEFAULTS.shift);
        formData.append("reuse_mask", String(reuseMask));
        formData.append("save_to_disk", String(saveToDisk));

        const response = await fetch("/remove-bg", {
            method: "POST",
            body: formData,
        });

        if (!response.ok) {
            let msg = `Server error ${response.status}`;
            try {
                const err = await response.json();
                msg = err.error || msg;
            } catch {}
            throw new Error(msg);
        }

        const savedPath = response.headers.get("X-Saved-Path");
        const resultBlob = await response.blob();
        setPreviewBlob(resultBlob);
        hasProcessedCurrentImage = true;
        updateCompareOverlay();

        const elapsed = ((performance.now() - t0) / 1000).toFixed(2);
        if (saveToDisk && savedPath) {
            setStatus(`saved ${savedPath} in ${elapsed}s`);
        } else {
            setStatus(`converted in ${elapsed}s`);
        }
    } catch (err) {
        setStatus(`error: ${err.message}`);
    } finally {
        stopStatusPolling();
        setProcessing(false);
        refreshModelCacheStatus();
    }
}

function bindSlider(inputEl, labelEl, onChangeReapply = true) {
    if (!inputEl || !labelEl) return;
    inputEl.addEventListener("input", () => {
        labelEl.textContent = inputEl.value;
    });
    if (onChangeReapply) {
        inputEl.addEventListener("change", () => {
            if (hasProcessedCurrentImage && !isProcessing) {
                runProcess(true, false);
            }
        });
    }
}

bindSlider(paramFeather, valFeather);
bindSlider(paramThreshold, valThreshold);
bindSlider(paramContrast, valContrast);
bindSlider(paramShift, valShift);

resetSettingsButton?.addEventListener("click", () => {
    if (isProcessing) return;
    if (paramFeather && valFeather) {
        paramFeather.value = DEFAULTS.feather;
        valFeather.textContent = DEFAULTS.feather;
    }
    if (paramThreshold && valThreshold) {
        paramThreshold.value = DEFAULTS.threshold;
        valThreshold.textContent = DEFAULTS.threshold;
    }
    if (paramContrast && valContrast) {
        paramContrast.value = DEFAULTS.contrast;
        valContrast.textContent = DEFAULTS.contrast;
    }
    if (paramShift && valShift) {
        paramShift.value = DEFAULTS.shift;
        valShift.textContent = DEFAULTS.shift;
    }

    if (hasProcessedCurrentImage) {
        runProcess(true, false);
    } else {
        setStatus("settings reset to default");
    }
});

modelSelect?.addEventListener("change", () => {
    hasProcessedCurrentImage = false;
    isComparing = false;
    if (saveDownloadsButton) saveDownloadsButton.disabled = true;
    if (compareButton) compareButton.disabled = true;
    updateCompareOverlay();
    setStatus(`switched model to ${modelSelect.value}`);
});

insertButton.addEventListener("click", () => input.click());

input.addEventListener("change", () => {
    selectImage(input.files[0]);
    input.value = "";
});

exportButton.addEventListener("click", () => runProcess(false, false));

previewStage.addEventListener("dragover", e => e.preventDefault());
previewStage.addEventListener("drop", e => {
    e.preventDefault();
    selectImage(e.dataTransfer.files[0]);
});

// Drag & drop onto the left panel
const leftPanel = document.getElementById("left");
leftPanel?.addEventListener("dragover", e => e.preventDefault());
leftPanel?.addEventListener("drop", e => {
    e.preventDefault();
    selectImage(e.dataTransfer.files[0]);
});

window.addEventListener("beforeunload", () => {
    if (previewURL) URL.revokeObjectURL(previewURL);
    if (originalURL) URL.revokeObjectURL(originalURL);
});

refreshModelCacheStatus();