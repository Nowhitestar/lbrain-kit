const parameters = new URLSearchParams(location.search);
const legacyId = parameters.get("id") || "";
const popupMode = !legacyId;
const confirmationKey = legacyId
  ? `https://lbrain.invalid/confirmation/${encodeURIComponent(legacyId)}`
  : "";
const save = document.querySelector("#save");
const cancel = document.querySelector("#cancel");
const details = document.querySelector("#details");
let currentId = legacyId;
let currentJob = null;
let permissionOrigins = [];
let preparedCapture = null;
let preparedTab = null;
let popupPort = null;
let workerFailureId = "";
let legacyUnavailable = false;
let preflightId = "";
let preflightPromise = null;
let missingPermissionOrigins = [];

save.disabled = true;

function text(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value || "";
}

function phase(value, title, message, retry = false) {
  if (document.body) document.body.dataset.phase = value;
  const status = document.querySelector("#status");
  const preview = document.querySelector("#preview");
  const actions = document.querySelector("#actions");
  if (status) {
    status.hidden = value === "ready";
  }
  if (preview) preview.hidden = value !== "ready";
  if (details) details.hidden = value !== "ready";
  if (actions) actions.hidden = value !== "ready" && !retry;
  text("#status-title", title);
  text("#status-message", message);
  save.disabled = value !== "ready" && !retry;
  cancel.disabled = value === "saving";
  cancel.textContent = "取消";
  save.textContent = retry ? (currentJob?.preview ? "重试保存" : "重新读取") : "确认保存";
}

function loadPreview(message) {
  if (!message?.preview || !message.tab) return;
  currentId = message.id || currentId;
  currentJob = message;
  preparedCapture = message.capture || preparedCapture;
  preparedTab = message.tab;
  permissionOrigins = message.preview.permission_origins || [];
  text("#title", message.preview.title);
  text("#summary", message.preview.summary);
  if (details) {
    details.replaceChildren?.();
    if (!details.replaceChildren) details.textContent = "";
    for (const [key, value] of message.preview.details || []) {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = key;
      description.textContent = value;
      details.append(term, description);
    }
  }
  phase("ready", "", "");
  preparePermissions();
}

function preparePermissions() {
  if (!currentId) return;
  if (preflightId === currentId) {
    save.disabled = Boolean(preflightPromise);
    return preflightPromise;
  }
  const id = currentId;
  preflightId = id;
  save.disabled = true;
  preflightPromise = (popupMode ? Promise.resolve(null) : chrome.windows.getCurrent()).then((currentWindow) => (
    chrome.runtime.sendMessage({
      type: "confirmation.preflight",
      id,
      window_id: currentWindow?.id ?? null,
      permission_origins: permissionOrigins
    })
  )).then((response) => {
    if (response?.error) throw new Error(response.error);
    if (currentId !== id) return;
    missingPermissionOrigins = Array.isArray(response?.missing) ? response.missing : [];
    save.disabled = false;
  }).catch((error) => {
    if (currentId !== id) return;
    currentJob = { ...currentJob, preview: null };
    phase("failed", "准备失败", error instanceof Error ? error.message : String(error), true);
  }).finally(() => {
    if (preflightId === id) {
      preflightPromise = null;
      if (currentId === id && currentJob?.preview
          && ["ready", "failed"].includes(document.body?.dataset.phase)) save.disabled = false;
    }
  });
  return preflightPromise;
}

function terminalMessage(receipt) {
  if (receipt?.status === "already_saved") return ["已保存", `内容没有变化，无需重复写入。 ${receipt.target || ""}`.trim()];
  if (receipt?.status === "new_version") return ["已保存新版本", receipt.target || "新版本已写入 LBrain。"];
  if (receipt?.status === "partial") return ["已保存，部分媒体缺失", `正文已写入，可稍后重试缺失媒体。 ${receipt.target || ""}`.trim()];
  return ["保存成功", receipt?.target || "内容已写入 LBrain。"];
}

function showJob(message) {
  const job = message?.type === "job" ? message.job : (message?.job || message);
  if (!job?.phase) return;
  if (currentId && job.id && job.id !== currentId) return;
  currentId = job.id || currentId;
  currentJob = { ...currentJob, ...job };
  if (job.preview) {
    preparedTab = job.tab || preparedTab;
    permissionOrigins = job.preview.permission_origins || permissionOrigins;
  }
  if (job.phase === "ready") {
    loadPreview(job);
    return;
  }
  if (job.phase === "preparing") {
    phase("preparing", "正在读取当前页面…", "识别正文和可保存的媒体。");
    return;
  }
  if (job.phase === "saving") {
    phase("saving", "正在保存…", "正在整理媒体并写入 LBrain；关闭弹窗也会继续。");
    return;
  }
  if (job.phase === "complete") {
    const [title, messageText] = terminalMessage(job.receipt);
    phase("complete", title, messageText, true);
    save.textContent = "再次保存";
    cancel.textContent = "关闭";
    return;
  }
  if (job.phase === "failed") {
    const saveFailure = Boolean(currentJob?.preview);
    phase(
      "failed",
      saveFailure ? "保存失败" : "读取失败",
      job.error || (saveFailure ? "未能写入 LBrain，请重试。" : "未能读取当前页面，请重试。"),
      true
    );
    if (popupMode && saveFailure) {
      preparePermissions();
    }
  }
}

function watchJob() {
  if (!popupMode || !currentId) return;
  if (!popupPort) {
    const connected = chrome.runtime.connect({ name: "lbrain-popup" });
    popupPort = connected;
    connected.onMessage.addListener((message) => {
      const job = message?.type === "job" ? message.job : message?.job;
      if (job?.phase === "failed") workerFailureId = job.id || currentId;
      showJob(message);
    });
    connected.onDisconnect?.addListener(() => {
      if (popupPort !== connected) return;
      popupPort = null;
      if (!preflightPromise) preflightId = "";
      queueMicrotask(() => {
        if (!popupPort && currentId) {
          try { watchJob(); } catch (_) {}
        }
      });
    });
  }
  popupPort.postMessage({ type: "watch", id: currentId });
}

async function preparePopup() {
  phase("preparing", "正在读取当前页面…", "识别正文和可保存的媒体。");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !tab.url) throw new Error("无法读取当前页面。");
    const job = await chrome.runtime.sendMessage({
      type: "confirmation.prepare", tab: { id: tab.id, title: tab.title || "", url: tab.url }, scope: "page"
    });
    if (job?.error) throw new Error(job.error);
    showJob(job);
    watchJob();
  } catch (error) {
    currentJob = null;
    phase("failed", "读取失败", error instanceof Error ? error.message : String(error), true);
  }
}

function startLegacyConfirmation() {
  phase("preparing", "正在读取当前页面…", "识别正文和可保存的媒体。");
  const port = chrome.runtime.connect({ name: "lbrain-confirm" });
  port.onMessage.addListener((message) => {
    if (message?.type === "error") {
      port.disconnect();
      legacyUnavailable = message.error === "This capture confirmation is no longer available.";
      phase("failed", legacyUnavailable ? "读取已中断" : "读取失败", message.error, true);
      if (legacyUnavailable) save.textContent = "关闭后重新发起";
      return;
    }
    if (message?.type !== "preview") return;
    legacyUnavailable = false;
    loadPreview({ ...message, id: legacyId, phase: "ready" });
    port.disconnect();
  });
  port.postMessage({ type: "ready", id: legacyId });
}

async function saveCapture() {
  workerFailureId = "";
  const requestedOrigins = [...missingPermissionOrigins];
  let armRequest = Promise.resolve(null);
  let permissionRequest = Promise.resolve(false);
  let grantedPermissions = false;
  if (requestedOrigins.length) {
    try {
      if (popupMode) {
        popupPort?.postMessage({ type: "arm", id: currentId });
        armRequest = chrome.runtime.sendMessage({ type: "confirmation.arm", id: currentId });
      }
      permissionRequest = chrome.permissions.request({ origins: requestedOrigins });
    } catch (_) {}
  }
  phase(
    "saving",
    "正在准备保存…",
    requestedOrigins.length ? "正在等待页面权限；授权后会在后台继续。" : "正在交给 LBrain 保存。"
  );
  let reserved = !popupMode;
  try {
    if (requestedOrigins.length) {
      const granted = await permissionRequest.catch(() => false);
      grantedPermissions = granted;
      if (popupMode) {
        const armed = await armRequest;
        if (armed?.error) throw new Error(armed.error);
        preflightId = "";
        missingPermissionOrigins = [];
        const response = await chrome.runtime.sendMessage({
          type: "confirmation.permission_result", id: currentId, granted
        });
        if (response?.error && !response?.phase) throw new Error(response.error);
        if (response?.phase) showJob(response);
        return;
      }
    }
    if (!popupMode) {
      if (!preparedCapture || !preparedTab) throw new Error("The capture preview is unavailable.");
      const cache = await caches.open("lbrain-confirmations-v1");
      await cache.put(confirmationKey, new Response(JSON.stringify({ capture: preparedCapture, tab: preparedTab })));
    }
    if (popupMode) {
      preflightId = "";
      missingPermissionOrigins = [];
    }
    const response = await chrome.runtime.sendMessage({
      type: "confirmation.decide", id: currentId
    });
    if (response?.error && !response?.phase) throw new Error(response.error);
    reserved = false;
    if (popupMode) showJob(response?.phase ? response : { id: currentId, phase: "complete", receipt: response });
    else window.close();
  } catch (error) {
    if (grantedPermissions && requestedOrigins.length) {
      await chrome.runtime.sendMessage({
        type: "confirmation.permissions",
        id: currentId,
        origins: requestedOrigins,
        cleanup: true
      }).catch(() => {});
    }
    if (!preflightPromise && workerFailureId !== currentId) {
      preflightId = "";
      missingPermissionOrigins = [];
    }
    if (!popupMode) {
      const cache = await caches.open("lbrain-confirmations-v1");
      await cache.delete(confirmationKey);
    }
    if (reserved) await chrome.runtime.sendMessage({ type: "confirmation.release", id: currentId }).catch(() => {});
    const message = error instanceof Error ? error.message : String(error);
    if (popupMode) showJob({ id: currentId, phase: "failed", preview: currentJob?.preview, error: message });
    else {
      text("#summary", message);
      phase("failed", "保存失败", message, true);
      preparePermissions();
    }
  }
}

save.addEventListener("click", async () => {
  const currentPhase = document.body?.dataset.phase;
  if (!popupMode && currentPhase === "failed" && !currentJob?.preview) {
    if (legacyUnavailable) {
      window.close();
      return;
    }
    if (!preparedCapture || !preparedTab) {
      startLegacyConfirmation();
      return;
    }
    currentJob = { ...currentJob, preview: {} };
    preflightId = "";
    missingPermissionOrigins = [];
    phase("ready", "", "");
    await preparePermissions();
    return;
  }
  if (popupMode && (currentPhase === "complete" || (currentPhase === "failed" && !currentJob?.preview))) {
    if (currentId) await chrome.runtime.sendMessage({ type: "confirmation.cancel", id: currentId }).catch(() => {});
    currentId = "";
    currentJob = null;
    await preparePopup();
    return;
  }
  return saveCapture();
});

cancel.addEventListener("click", async () => {
  if (popupMode && currentId) await chrome.runtime.sendMessage({ type: "confirmation.cancel", id: currentId }).catch(() => {});
  window.close();
});

if (popupMode) preparePopup();
else startLegacyConfirmation();
