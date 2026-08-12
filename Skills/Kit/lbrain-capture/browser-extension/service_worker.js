const HOST = "io.lbrain.capture";
const PAGE = "lbrain-save-page";
const SELECTION = "lbrain-save-selection";
const STREAM_PROTOCOL = "lbrain.capture.stream.v1";
const CHUNK_BYTES = 384 * 1024;
const CONFIRMATION_CACHE = "lbrain-confirmations-v1";
const SAVE_RESERVATION = "lbrain-save-reservation-v1";
const confirmations = new Map();
const confirmationWindows = new Map();
let saveReservation = null;

const DIRECT_TYPES = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
  doc: "application/msword",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ppt: "application/vnd.ms-powerpoint",
  pptx: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  xls: "application/vnd.ms-excel",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  csv: "text/csv",
  epub: "application/epub+zip",
  odp: "application/vnd.oasis.opendocument.presentation",
  ods: "application/vnd.oasis.opendocument.spreadsheet",
  odt: "application/vnd.oasis.opendocument.text",
  rtf: "application/rtf",
  txt: "text/plain"
};
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "m4v", "webm", "avi", "mkv"]);

chrome.runtime.onInstalled.addListener(() => {
  clearConfirmations().catch(() => {});
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: PAGE, title: "Save page to LBrain", contexts: ["page"] });
    chrome.contextMenus.create({ id: SELECTION, title: "Save selection to LBrain", contexts: ["selection"] });
  });
});
chrome.runtime.onStartup.addListener(() => clearConfirmations().catch(() => {}));

function directCapture(tab) {
  const origin = tab?.url || "";
  let parsed;
  try {
    parsed = new URL(origin);
  } catch (_) {
    return null;
  }
  let filename = decodeURIComponent(parsed.pathname.split("/").pop() || "Saved document");
  const extension = filename.split(".").pop()?.toLowerCase();
  const title = tab.title || filename;
  if (VIDEO_EXTENSIONS.has(extension)) {
    return {
      schema: "lbrain.capture.v1",
      title,
      summary: "Original video link captured without the video binary.",
      origin,
      scope: "page",
      author: "",
      published_at: "",
      content_markdown: `## Video\n\n- Original video: [${origin}](${origin})`,
      capture_kind: "video",
      has_video: true,
      preview_characters: 0,
      extraction_status: "complete",
      remote_assets: [],
      assets: []
    };
  }
  const declaredType = typeof tab.mimeType === "string" ? tab.mimeType.split(";", 1)[0].trim().toLowerCase() : "";
  const mediaType = DIRECT_TYPES[extension] || (Object.values(DIRECT_TYPES).includes(declaredType) ? declaredType : "");
  if (!mediaType) return null;
  if (mediaType === "application/pdf" && !filename.toLowerCase().endsWith(".pdf")) filename += ".pdf";
  const folder = mediaType.startsWith("image/") ? "images" : "documents";
  const label = mediaType === "application/pdf" ? "PDF" : "original file";
  return {
    schema: "lbrain.capture.v1",
    title,
    summary: `Direct ${label} captured from the current browser session.`,
    origin,
    scope: "page",
    author: "",
    published_at: "",
    content_markdown: `[Original ${label}](lbrain-asset://direct-document)`,
    capture_kind: mediaType.startsWith("image/") ? "image" : "document",
    preview_characters: 0,
    extraction_status: "complete",
    remote_assets: [{
      id: "direct-document",
      url: origin,
      name: `${folder}/${filename || `original.${extension}`}`,
      media_type: mediaType
    }],
    assets: []
  };
}

async function renderedCapture(tabId, scope) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["extractor.js"] });
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (captureScope) => globalThis.LBrainCapture.extract(captureScope),
    args: [scope]
  });
  if (!result?.result) throw new Error("The current page could not be extracted.");
  return result.result;
}

async function renderedContentType(tabId) {
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => document.contentType || ""
    });
    return result?.result || "";
  } catch (_) {
    return "";
  }
}

async function prepareCapture(tab, scope) {
  let capture = scope === "page" ? directCapture(tab) : null;
  if (!capture && scope === "page") {
    capture = directCapture({ ...tab, mimeType: await renderedContentType(tab.id) });
  }
  return capture || renderedCapture(tab.id, scope);
}

function previewFor(capture) {
  const assets = capture.remote_assets || [];
  const image = (asset) => asset.media_type.startsWith("image/") || asset.name.startsWith("images/");
  const images = assets.filter(image).length;
  const documents = assets.filter((asset) => !image(asset) && !asset.media_type.startsWith("video/")).length;
  const labels = {
    article: ["文章正文", "将保存可读正文和文章内媒体。"],
    thread: ["X Thread", "将按顺序保存作者 Thread 和媒体。"],
    selection: ["选中内容", "将保存当前选区和其中的媒体。"],
    video: ["视频字幕与链接", "将保存原链接和可获得的字幕，不保存视频文件。"],
    document: ["原始文档", "将保存当前 PDF 或文档原文件。"],
    image: ["原始图片", "将保存当前图片原文件。"],
    html: ["HTML 快照", "未识别到合适的文章正文，将保存当前页面的可离线 HTML 快照。"]
  };
  const [kind, baseSummary] = labels[capture.capture_kind] || labels.html;
  const summary = capture.has_video && capture.capture_kind !== "video"
    ? `${baseSummary} 页面内视频仅保存原链接和可获得的字幕，不保存视频文件。`
    : baseSummary;
  let captureOrigin = "";
  try {
    captureOrigin = new URL(capture.origin).origin;
  } catch (_) {
    // The extractor validates normal web origins; keeping this empty makes a malformed origin request no permission.
  }
  const permissionOrigins = [];
  for (const asset of assets) {
    if (image(asset) || asset.media_type.startsWith("video/")) continue;
    try {
      const origin = new URL(asset.url).origin;
      if (origin !== captureOrigin && ["http:", "https:"].includes(new URL(asset.url).protocol)) permissionOrigins.push(`${origin}/*`);
    } catch (_) {
      // Invalid asset URLs are rejected by extraction/persistence; they never become optional permissions.
    }
  }
  return {
    title: capture.title,
    summary,
    permission_origins: Array.from(new Set(permissionOrigins)),
    details: [
      ["保存内容", kind],
      ["正文规模", `${capture.preview_characters || 0} 字符`],
      ["本地媒体", `${images} 张图片，${documents} 个文档/字幕`],
      ["进入位置", "Inbox / Captures"],
      ["原始链接", capture.origin]
    ]
  };
}

async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function byteLength(value) {
  return value instanceof Blob ? value.size : value.length;
}

async function byteSlice(value, start, end) {
  return value instanceof Blob
    ? new Uint8Array(await value.slice(start, end).arrayBuffer())
    : value.subarray(start, end);
}

async function preparePayload(capture) {
  const sourceContent = capture.capture_kind === "html"
    ? `${capture.content_markdown}\u0000${capture.snapshot_html || ""}`
    : capture.content_markdown;
  const source = [capture.title, capture.author, capture.published_at, sourceContent].join("\u0000");
  return {
    ...capture,
    source_content_markdown: sourceContent,
    source_content_hash: await digest(new TextEncoder().encode(source)),
    assets: []
  };
}

function saveAsMHTML(tabId) {
  return new Promise((resolve, reject) => {
    chrome.pageCapture.saveAsMHTML({ tabId }, (blob) => {
      if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
      else if (!blob) reject(new Error("Chrome could not create a page snapshot."));
      else resolve(blob);
    });
  });
}

async function preloadMedia(tabId, sources) {
  await chrome.scripting.executeScript({
    target: { tabId },
    func: async (requested) => {
      const wanted = new Set(requested);
      const images = Array.from(document.images).filter((image) => {
        const source = image.getAttribute("data-src") || image.getAttribute("data-original") || image.currentSrc || image.src;
        try {
          return wanted.has(new URL(source, document.baseURI).href);
        } catch (_) {
          return false;
        }
      });
      for (const image of images) {
        const source = image.getAttribute("data-src") || image.getAttribute("data-original");
        if (source) image.src = source;
      }
      await Promise.race([
        Promise.allSettled(images.map((image) => image.complete ? undefined : new Promise((resolve) => {
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", resolve, { once: true });
        }))),
        new Promise((resolve) => setTimeout(resolve, 4000))
      ]);
    },
    args: [sources]
  });
}

async function fetchAttachments(capture) {
  const attachments = [];
  for (const asset of capture.remote_assets || []) {
    if (asset.media_type.startsWith("video/")) continue;
    try {
      const response = await fetch(asset.url, { credentials: "include", cache: "no-store" });
      const contentType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
      if (!response.ok || (contentType === "text/html" && asset.media_type !== "text/html")) continue;
      attachments.push({ id: asset.id, mediaType: contentType, bytes: await response.blob() });
    } catch (_) {
      // The authenticated page archive remains the fallback; an absent resource becomes partial.
    }
  }
  return attachments;
}

async function snapshotFor(tab, capture) {
  if (["document", "image"].includes(capture.capture_kind)) {
    const response = await fetch(capture.origin, { credentials: "include", cache: "no-store" });
    if (!response.ok) throw new Error(`The current file could not be read (${response.status}).`);
    const mediaType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
    if (mediaType.startsWith("video/")) throw new Error("Video binaries are not saved.");
    return { kind: "binary", mediaType, bytes: await response.blob(), attachments: [] };
  }
  if (capture.capture_kind === "video" && !(capture.remote_assets || []).length) {
    return { kind: "none", mediaType: "", bytes: new Uint8Array(), attachments: [] };
  }
  const imageSources = (capture.remote_assets || [])
    .filter((asset) => asset.media_type.startsWith("image/") || asset.name.startsWith("images/"))
    .map((asset) => asset.url);
  await preloadMedia(tab.id, imageSources);
  const blob = await saveAsMHTML(tab.id);
  return {
    kind: "mhtml",
    mediaType: "multipart/related",
    bytes: blob,
    attachments: await fetchAttachments(capture)
  };
}

function encode(bytes) {
  let value = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    value += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(value);
}

async function streamCapture(payload, snapshot) {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  const attachmentMetadata = [];
  for (const attachment of snapshot.attachments) {
    attachmentMetadata.push({
      id: attachment.id,
      size: byteLength(attachment.bytes),
      media_type: attachment.mediaType
    });
  }
  const begin = {
    protocol: STREAM_PROTOCOL,
    type: "begin",
    acknowledgements: true,
    integrity: "sha256-chunks",
    stream_id: crypto.randomUUID(),
    payload_size: payloadBytes.length,
    payload_sha256: await digest(payloadBytes),
    snapshot_kind: snapshot.kind,
    snapshot_size: byteLength(snapshot.bytes),
    snapshot_sha256: "",
    snapshot_media_type: snapshot.mediaType,
    attachments: attachmentMetadata
  };
  const port = chrome.runtime.connectNative(HOST);
  return new Promise((resolve, reject) => {
    let settled = false;
    let pendingAck = null;
    let timeout;
    const armTimeout = () => {
      clearTimeout(timeout);
      timeout = setTimeout(() => finish(reject, new Error("LBrain capture timed out while idle.")), 120000);
    };
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      callback(value);
    };
    armTimeout();
    port.onMessage.addListener((response) => {
      if (response?.type === "ack" && pendingAck) {
        const { channel, sequence, resolve: acknowledge } = pendingAck;
        if (response.channel !== channel || response.sequence !== sequence) {
          finish(reject, new Error("LBrain Native Host acknowledged the wrong stream chunk."));
          return;
        }
        pendingAck = null;
        armTimeout();
        acknowledge();
      } else if (!response || response.status === "failed") finish(reject, new Error(response?.error || "Capture failed"));
      else finish(resolve, response);
    });
    port.onDisconnect.addListener(() => {
      if (!settled) finish(reject, new Error(chrome.runtime.lastError?.message || "LBrain Native Host disconnected."));
    });
    const postChunk = (message) => new Promise((acknowledge, fail) => {
      if (settled) {
        fail(new Error("LBrain capture ended before the stream completed."));
        return;
      }
      pendingAck = { channel: message.channel, sequence: message.sequence, resolve: acknowledge };
      try {
        port.postMessage(message);
      } catch (error) {
        pendingAck = null;
        fail(error);
      }
    });
    (async () => {
      port.postMessage(begin);
      const channels = [["payload", payloadBytes], ["snapshot", snapshot.bytes], ...snapshot.attachments.map(
        (attachment) => [`asset:${attachment.id}`, attachment.bytes]
      )];
      for (const [channel, bytes] of channels) {
        let sequence = 0;
        for (let offset = 0; offset < byteLength(bytes); offset += CHUNK_BYTES) {
          const chunk = await byteSlice(bytes, offset, offset + CHUNK_BYTES);
          await postChunk({
            protocol: STREAM_PROTOCOL,
            type: "chunk",
            stream_id: begin.stream_id,
            channel,
            sequence,
            data: encode(chunk),
            sha256: await digest(chunk)
          });
          sequence += 1;
        }
      }
      clearTimeout(timeout);
      port.postMessage({ protocol: STREAM_PROTOCOL, type: "end", stream_id: begin.stream_id });
    })().catch((error) => finish(reject, error));
  });
}

async function showReceipt(receipt) {
  const id = `lbrain-${receipt.capture_id}-${receipt.version}`;
  if (receipt.open_uri) await chrome.storage.session.set({ [id]: receipt.open_uri });
  await chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icon.svg",
    title: "LBrain",
    message: `${receipt.status.replace("_", " ")}: ${receipt.target}`,
    buttons: receipt.open_uri ? [{ title: "Open in Obsidian" }] : []
  });
}

async function showFailure(error) {
  await chrome.notifications.create(`lbrain-error-${Date.now()}`, {
    type: "basic",
    iconUrl: "icon.svg",
    title: "LBrain capture needs attention",
    message: error instanceof Error ? error.message : String(error)
  });
}

async function savePrepared(tab, capture) {
  const payload = await preparePayload(capture);
  const recoveryKey = `capture-recovery:${capture.origin}\u0000${capture.scope}`;
  const recovery = (await chrome.storage.local.get(recoveryKey))[recoveryKey];
  if (recovery?.source_content_hash === payload.source_content_hash) Object.assign(payload, recovery);
  const receipt = await streamCapture(payload, await snapshotFor(tab, capture));
  if (receipt.status === "partial") {
    await chrome.storage.local.set({
      [recoveryKey]: {
        recovery_target: receipt.target,
        expected_hash: receipt.expected_hash,
        source_content_hash: receipt.source_content_hash
      }
    });
  } else {
    await chrome.storage.local.remove(recoveryKey);
  }
  await showReceipt(receipt);
  return receipt;
}

async function storedCapture(id) {
  const cache = await caches.open(CONFIRMATION_CACHE);
  const response = await cache.match(chrome.runtime.getURL(`confirmation/${id}`));
  if (!response) throw new Error("This capture confirmation is no longer available.");
  return response.json();
}

async function deleteConfirmation(id) {
  const cache = await caches.open(CONFIRMATION_CACHE);
  await cache.delete(chrome.runtime.getURL(`confirmation/${id}`));
}

async function clearConfirmations() {
  await caches.delete(CONFIRMATION_CACHE);
  await chrome.storage.session.remove(SAVE_RESERVATION);
}

async function releaseSaveReservation(id) {
  if (saveReservation === id) saveReservation = null;
  try {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (stored?.id === id) await chrome.storage.session.remove(SAVE_RESERVATION);
  } catch (_) {
    // Reservation expiry remains the crash-safe fallback.
  }
}

async function confirmCapture(tab, capture) {
  const id = crypto.randomUUID();
  return new Promise(async (resolve, reject) => {
    confirmations.set(id, {
      preview: previewFor(capture),
      capture,
      tab: { id: tab.id, title: tab.title || "", url: tab.url || "" },
      resolve,
      reject
    });
    try {
      const created = await chrome.windows.create({
        url: chrome.runtime.getURL(`confirm.html?id=${encodeURIComponent(id)}`),
        type: "popup",
        focused: true,
        width: 460,
        height: 560
      });
      const pending = confirmations.get(id);
      if (created?.id !== undefined) {
        confirmationWindows.set(id, created.id);
        if (pending) pending.windowId = created.id;
      }
    } catch (error) {
      confirmations.delete(id);
      reject(error);
    }
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || typeof message.id !== "string" || !message.type?.startsWith("confirmation.")) return;
  (async () => {
    if (message.type === "confirmation.reserve") {
      if (saveReservation) throw new Error("Another LBrain capture is already being saved.");
      saveReservation = message.id;
      try {
        const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
        if (stored?.id && stored.id !== message.id && Date.now() - stored.created < 10 * 60 * 1000) {
          throw new Error("Another LBrain capture is already being saved.");
        }
        await chrome.storage.session.set({ [SAVE_RESERVATION]: { id: message.id, created: Date.now() } });
      } catch (error) {
        saveReservation = null;
        throw error;
      }
      return { reserved: true };
    }
    if (message.type === "confirmation.release") {
      await releaseSaveReservation(message.id);
      confirmationWindows.delete(message.id);
      return { released: true };
    }
    if (message.type !== "confirmation.decide") return undefined;
    if (saveReservation !== message.id) {
      const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
      if (stored?.id !== message.id) throw new Error("This capture no longer owns the save slot.");
      saveReservation = message.id;
    }
    try {
      const pending = await storedCapture(message.id);
      if (!pending || typeof pending !== "object" || !pending.capture || !pending.tab) {
        throw new Error("This capture confirmation is no longer available.");
      }
      const allowed = new Set(previewFor(pending.capture).permission_origins || []);
      const releaseOrigins = Array.isArray(message.release_origins)
        ? message.release_origins.filter((origin) => allowed.has(origin))
        : [];
      try {
        return await savePrepared(pending.tab, pending.capture);
      } finally {
        if (releaseOrigins.length) await chrome.permissions.remove({ origins: releaseOrigins }).catch(() => {});
        await deleteConfirmation(message.id);
        confirmationWindows.delete(message.id);
      }
    } finally {
      await releaseSaveReservation(message.id);
    }
  })().then(sendResponse, (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) }));
  return true;
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "lbrain-confirm") return;
  port.onMessage.addListener((message) => {
    if (message?.type !== "ready" || typeof message.id !== "string") return;
    const pending = confirmations.get(message.id);
    if (!pending) {
      port.postMessage({ type: "error", error: "This capture confirmation is no longer available." });
      return;
    }
    port.postMessage({
      type: "preview",
      preview: pending.preview,
      capture: pending.capture,
      tab: pending.tab
    });
    confirmations.delete(message.id);
    pending.resolve();
  });
});

chrome.windows.onRemoved.addListener((windowId) => {
  for (const [id, savedWindowId] of confirmationWindows) {
    if (savedWindowId !== windowId) continue;
    confirmationWindows.delete(id);
    if (saveReservation === id) {
      releaseSaveReservation(id).catch(() => {});
    }
  }
  for (const [id, pending] of confirmations) {
    if (pending.windowId === windowId) {
      confirmations.delete(id);
      pending.resolve();
    }
  }
});

async function interactiveSave(tab, scope) {
  try {
    const capture = await prepareCapture(tab, scope);
    await confirmCapture(tab, capture);
  } catch (error) {
    await showFailure(error);
  }
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === PAGE) interactiveSave(tab, "page");
  if (info.menuItemId === SELECTION) interactiveSave(tab, "selection");
});

chrome.action.onClicked.addListener((tab) => interactiveSave(tab, "page"));

chrome.notifications.onButtonClicked.addListener(async (id, button) => {
  if (button !== 0) return;
  const value = await chrome.storage.session.get(id);
  if (value[id]) await chrome.tabs.create({ url: value[id] });
});

globalThis.LBrainCaptureWorker = { directCapture, preparePayload, previewFor, streamCapture };
