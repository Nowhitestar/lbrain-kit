const id = new URLSearchParams(location.search).get("id") || "";
const port = chrome.runtime.connect({ name: "lbrain-confirm" });
let permissionOrigins = [];
let preparedCapture = null;
let preparedTab = null;
const save = document.querySelector("#save");
const cancel = document.querySelector("#cancel");
save.disabled = true;

function loadPreview(message) {
  if (message?.type === "error") throw new Error(message.error);
  if (message?.type !== "preview" || !message.capture || !message.tab) return;
  preparedCapture = message.capture;
  preparedTab = message.tab;
  document.querySelector("#title").textContent = message.preview.title;
  document.querySelector("#summary").textContent = message.preview.summary;
  permissionOrigins = message.preview.permission_origins || [];
  const details = document.querySelector("#details");
  for (const [key, value] of message.preview.details) {
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = key;
    description.textContent = value;
    details.append(term, description);
  }
  save.disabled = false;
}

port.onMessage.addListener((message) => {
  try {
    loadPreview(message);
    if (message?.type === "preview") port.disconnect();
  } catch (error) {
    document.querySelector("#summary").textContent = error instanceof Error ? error.message : String(error);
  }
});
port.postMessage({ type: "ready", id });

save.addEventListener("click", async () => {
  save.disabled = true;
  cancel.disabled = true;
  save.textContent = "正在保存…";
  const releaseOrigins = [];
  let reserved = false;
  try {
    const confirmationWindow = await chrome.windows.getCurrent();
    const reservation = await chrome.runtime.sendMessage({
      type: "confirmation.reserve", id, window_id: confirmationWindow?.id, permission_origins: permissionOrigins
    });
    if (reservation?.error) throw new Error(reservation.error);
    reserved = true;
    const missing = [];
    for (const origin of permissionOrigins) {
      if (!await chrome.permissions.contains({ origins: [origin] })) missing.push(origin);
    }
    if (missing.length) {
      await chrome.runtime.sendMessage({ type: "confirmation.permissions", id, origins: missing });
      if (await chrome.permissions.request({ origins: missing })) releaseOrigins.push(...missing);
      else await chrome.runtime.sendMessage({ type: "confirmation.permissions", id, origins: [] });
    }
  } catch (_) {
    // The authenticated page archive remains the fallback; missing attachments become partial.
  }
  try {
    if (!preparedCapture || !preparedTab) throw new Error("The capture preview is unavailable.");
    const cache = await caches.open("lbrain-confirmations-v1");
    const target = chrome.runtime.getURL(`confirmation/${id}`);
    await cache.put(target, new Response(JSON.stringify({ capture: preparedCapture, tab: preparedTab })));
    const response = await chrome.runtime.sendMessage({
      type: "confirmation.decide", id, release_origins: releaseOrigins
    });
    if (response?.error) throw new Error(response.error);
    reserved = false;
    window.close();
  } catch (error) {
    const cache = await caches.open("lbrain-confirmations-v1");
    await cache.delete(chrome.runtime.getURL(`confirmation/${id}`));
    if (releaseOrigins.length) await chrome.permissions.remove({ origins: releaseOrigins });
    if (reserved) await chrome.runtime.sendMessage({ type: "confirmation.release", id }).catch(() => {});
    document.querySelector("#summary").textContent = error instanceof Error ? error.message : String(error);
    cancel.disabled = false;
    save.textContent = "保存失败";
  }
});
cancel.addEventListener("click", async () => {
  window.close();
});
