const HOST = "io.lbrain.capture";
const PAGE = "lbrain-save-page";
const SELECTION = "lbrain-save-selection";
const STREAM_PROTOCOL = "lbrain.capture.stream.v1";
const CHUNK_BYTES = 384 * 1024;
const MEBIBYTE = 1024 * 1024;
const MAX_CAPTURE_PAYLOAD_BYTES = 32 * MEBIBYTE;
const MAX_CAPTURE_ASSET_BYTES = 256 * MEBIBYTE;
const MAX_CAPTURE_STREAM_BYTES = 512 * MEBIBYTE;
const MAX_CAPTURE_MEDIA_BYTES = MAX_CAPTURE_STREAM_BYTES - MAX_CAPTURE_PAYLOAD_BYTES;
const MAX_CAPTURE_ATTACHMENTS = 256;
const CONFIRMATION_CACHE = "lbrain-confirmations-v1";
const CONFIRMATION_KEY_BASE = "https://lbrain.invalid/confirmation/";
const SAVE_RESERVATION = "lbrain-save-reservation-v1";
const SAVE_RESERVATION_TTL = 10 * 60 * 1000;
const SAVE_RESERVATION_ALARM = "lbrain-save-reservation-expiry-v1";
const SAVE_RESERVATION_RETRY = 60 * 1000;
const PERMISSION_JOURNAL = "lbrain-temporary-origins-v1";
const POPUP_JOB = "lbrain-popup-job-v1";
const confirmations = new Map();
const confirmationWindows = new Map();
const popupPreparations = new Map();
const popupCaptures = new Map();
const popupWatches = new Map();
const armedDecisions = new Map();
let saveReservation = null;
let reservationMutation = Promise.resolve();
let popupMutation = Promise.resolve();

function mutateReservation(task) {
  const current = reservationMutation.then(task, task);
  reservationMutation = current.catch(() => {});
  return current;
}

function mutatePopupJob(task) {
  const current = popupMutation.then(task, task);
  popupMutation = current.catch(() => {});
  return current;
}

async function popupJob() {
  return (await chrome.storage.session.get(POPUP_JOB))[POPUP_JOB] || null;
}

function publishPopupJob(job) {
  for (const [port, id] of popupWatches) {
    if (id && job && job.id !== id) continue;
    try {
      port.postMessage({ type: "job", job });
    } catch (_) {
      popupWatches.delete(port);
    }
  }
}

async function persistPopupJob(job) {
  await chrome.storage.session.set({ [POPUP_JOB]: job });
  publishPopupJob(job);
  return job;
}

async function scheduleReservationExpiry(created, retry = false) {
  if (!chrome.alarms?.create) return;
  const when = retry
    ? Date.now() + SAVE_RESERVATION_RETRY
    : (Number.isFinite(created) ? created + SAVE_RESERVATION_TTL : Date.now() + SAVE_RESERVATION_RETRY);
  await chrome.alarms.create(SAVE_RESERVATION_ALARM, { when });
}

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

function decodedFilename(value, fallback) {
  let decoded = fallback;
  try {
    decoded = decodeURIComponent(value || fallback);
  } catch (_) {}
  decoded = decoded.replace(/[\x00-\x1f\x7f<>:"|?*\\/]/g, "-");
  const suffix = decoded.includes(".") ? decoded.split(".").pop() : "";
  const extension = suffix && suffix.length <= 10 ? `.${suffix}` : "";
  const stem = extension ? decoded.slice(0, -extension.length) : decoded;
  let shortened = "";
  for (const character of stem.slice(0, 512)) {
    if (new TextEncoder().encode(shortened + character + extension).length > 160) break;
    shortened += character;
  }
  return `${shortened || "Saved document"}${extension}`;
}

function sensitiveKey(key) {
  const normalized = String(key || "").toLowerCase();
  return /^x-(?:amz|goog)-/.test(normalized)
    || /^(?:sig|policy|key-pair-id|auth|auth_key|code|jwt|hmac|hdnea|hdnts)$/.test(normalized)
    || /(?:^|[_-])(?:token|signature|credential|secret)$/.test(normalized);
}

function signedQuery(parsed) {
  return Array.from(parsed.searchParams.keys()).some(sensitiveKey);
}

function signedFragment(parsed) {
  const fragment = parsed.hash.slice(1);
  const parameters = fragment.includes("?") ? fragment.split("?", 2)[1] || "" : fragment;
  return parameters.includes("=") && Array.from(new URLSearchParams(parameters).keys()).some(sensitiveKey);
}

function provenanceUrl(value) {
  try {
    const parsed = new URL(value);
    parsed.username = "";
    parsed.password = "";
    const signed = signedQuery(parsed);
    const privateFragment = signedFragment(parsed);
    if (signed) parsed.search = "";
    if (signed || privateFragment || !/^#(?:\/|!\/)/.test(parsed.hash)) parsed.hash = "";
    return parsed.href;
  } catch (_) {
    return "";
  }
}

function markdownUrl(value) {
  const clean = String(value || "").replace(/\\/g, "%5C").replace(/</g, "%3C").replace(/>/g, "%3E").replace(/\|/g, "%7C");
  return /[()[\]]/.test(clean) ? `<${clean}>` : clean;
}

function sanitizePersistedUrls(value, preserved = []) {
  const keep = new Set(preserved.flatMap((url) => [url, markdownUrl(url).replace(/^<|>$/g, "")]));
  return String(value || "").replace(/https?:\/\/[^\s<>"'`]+/gi, (token) => {
    let candidate = token;
    let suffix = "";
    while (/[.,;!?\])]/.test(candidate.slice(-1))) {
      const last = candidate.slice(-1);
      if (last === ")" && (candidate.match(/\(/g) || []).length >= (candidate.match(/\)/g) || []).length) break;
      if (last === "]" && (candidate.match(/\[/g) || []).length >= (candidate.match(/\]/g) || []).length) break;
      candidate = candidate.slice(0, -1);
      suffix = last + suffix;
    }
    const decoded = candidate.replaceAll("&amp;", "&");
    if (keep.has(decoded)) return token;
    let parsed;
    try {
      parsed = new URL(decoded);
    } catch (_) {
      return token;
    }
    const signed = signedQuery(parsed);
    const privateFragment = signedFragment(parsed);
    if (!signed && !privateFragment && !parsed.username && !parsed.password) return token;
    parsed.username = "";
    parsed.password = "";
    if (signed) parsed.search = "";
    if (signed || privateFragment) parsed.hash = "";
    const safe = parsed.href;
    return (candidate.includes("&amp;") ? safe.replaceAll("&", "&amp;") : safe) + suffix;
  });
}

chrome.runtime.onInstalled.addListener(() => {
  clearConfirmations().catch(() => {});
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: PAGE, title: "Save page to LBrain", contexts: ["page"] });
    chrome.contextMenus.create({ id: SELECTION, title: "Save selection to LBrain", contexts: ["selection"] });
  });
});
chrome.runtime.onStartup.addListener(() => clearConfirmations().catch(() => {}));

function directCapture(tab) {
  const sourceUrl = tab?.url || "";
  let parsed;
  try {
    parsed = new URL(sourceUrl);
  } catch (_) {
    return null;
  }
  const origin = provenanceUrl(sourceUrl);
  let filename = decodedFilename(parsed.pathname.split("/").pop(), "Saved document");
  const extension = filename.split(".").pop()?.toLowerCase();
  const title = String(tab.title || filename).split(sourceUrl).join(origin);
  if (VIDEO_EXTENSIONS.has(extension)) {
    return {
      schema: "lbrain.capture.v1",
      title,
      summary: "Original video link captured without the video binary.",
      origin,
      scope: "page",
      author: "",
      published_at: "",
      content_markdown: `## Video\n\n- Original video: [Open original video](${markdownUrl(origin)})`,
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
      url: sourceUrl,
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

function exactPermissionOrigin(value) {
  try {
    const parsed = new URL(value);
    const exact = `${parsed.origin}/*`;
    return ["http:", "https:"].includes(parsed.protocol)
      && Boolean(parsed.hostname)
      && !parsed.hostname.includes("*")
      && value === exact
      ? exact
      : "";
  } catch (_) {
    return "";
  }
}

function previewFor(capture, pageUrl = capture.origin) {
  const assets = (capture.remote_assets || []).slice(0, MAX_CAPTURE_ATTACHMENTS);
  const image = (asset) => asset.media_type.startsWith("image/") || asset.name.startsWith("images/");
  const images = assets.filter(image).length;
  const documents = assets.filter((asset) => !image(asset) && !asset.media_type.startsWith("video/")).length;
  const labels = {
    article: ["文章正文", "将保存可读正文和文章内媒体。"],
    tweet: ["X 推文", "将保存当前推文、引用内容和媒体。"],
    thread: ["X Thread", "将按顺序保存作者 Thread 和媒体。"],
    selection: ["选中内容", "将保存当前选区和其中的媒体。"],
    video: ["视频字幕与链接", "将保存原链接和可获得的字幕，不保存视频文件。"],
    document: ["原始文档", "将保存当前 PDF 或文档原文件。"],
    image: ["原始图片", "将保存当前图片原文件。"],
    html: ["HTML 快照", "未识别到合适的文章正文，将保存当前页面的可离线 HTML 快照。"]
  };
  const [kind, baseSummary] = labels[capture.capture_kind] || labels.html;
  let summary = capture.has_video && capture.capture_kind !== "video"
    ? `${baseSummary} 页面内视频仅保存原链接和可获得的字幕，不保存视频文件。`
    : baseSummary;
  if (capture.rendered_translation) {
    summary += " 当前 X 页面显示自动译文，将保存可见译文；如需原文，请取消并先点“显示原文”。";
  }
  let captureOrigin = "";
  try {
    captureOrigin = new URL(pageUrl).origin;
  } catch (_) {
    // The extractor validates normal web origins; keeping this empty makes a malformed origin request no permission.
  }
  const permissionOrigins = [];
  for (const asset of assets) {
    if (asset.media_type.startsWith("video/")) continue;
    try {
      const origin = new URL(asset.url).origin;
      const permission = exactPermissionOrigin(`${origin}/*`);
      if (permission && origin !== captureOrigin) permissionOrigins.push(permission);
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
      ["原始链接", provenanceUrl(capture.origin) || capture.origin]
    ]
  };
}

async function digest(bytes) {
  return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function byteLength(value) {
  if (value?.reader) return value.size;
  return value instanceof Blob ? value.size : value.length;
}

async function byteSlice(value, start, end) {
  return value instanceof Blob
    ? new Uint8Array(await value.slice(start, end).arrayBuffer())
    : value.subarray(start, end);
}

async function* byteChunks(value) {
  if (!value?.reader) {
    for (let offset = 0; offset < byteLength(value); offset += CHUNK_BYTES) {
      yield await byteSlice(value, offset, offset + CHUNK_BYTES);
    }
    return;
  }
  try {
    while (true) {
      const next = await value.reader.read();
      if (next.done) return;
      const bytes = next.value instanceof Uint8Array ? next.value : new Uint8Array(next.value);
      for (let offset = 0; offset < bytes.length; offset += CHUNK_BYTES) {
        yield bytes.subarray(offset, offset + CHUNK_BYTES);
      }
    }
  } finally {
    value.reader.releaseLock();
  }
}

async function preparePayload(capture) {
  const rawOrigin = capture.origin || "";
  const origin = provenanceUrl(rawOrigin) || rawOrigin;
  const assetUrls = (capture.remote_assets || []).map((asset) => String(asset?.url || ""));
  const sanitize = (value, preserveAssets = false) => {
    let clean = String(value || "");
    if (rawOrigin && rawOrigin !== origin) {
      clean = clean.split(markdownUrl(rawOrigin)).join(markdownUrl(origin));
      clean = clean.split(rawOrigin.replaceAll("&", "&amp;"))
        .join(origin.replaceAll("&", "&amp;"));
      clean = clean.split(rawOrigin).join(origin);
    }
    return sanitizePersistedUrls(clean, preserveAssets ? assetUrls : []);
  };
  const title = sanitize(capture.title).trim();
  const summary = sanitize(capture.summary).trim();
  const author = sanitize(capture.author).trim();
  const publishedAt = sanitize(capture.published_at).trim();
  const contentMarkdown = sanitize(capture.content_markdown, true).trim();
  const snapshotHtml = sanitize(capture.snapshot_html, true).trim();
  const stableAssetContent = (value) => (capture.remote_assets || [])
    .flatMap((asset) => {
      const sourceUrl = String(asset?.url || "");
      const placeholder = asset?.id ? `lbrain-asset://${asset.id}` : "";
      return sourceUrl && placeholder
        ? [sourceUrl, markdownUrl(sourceUrl), sourceUrl.replaceAll("&", "&amp;")]
          .map((variant) => [variant, placeholder])
        : [];
    })
    .sort((left, right) => right[0].length - left[0].length)
    .reduce((clean, [variant, placeholder]) => clean.replace(
      new RegExp(`(?<![A-Za-z0-9%/?=&])${variant.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=$|[\\s\"'<>\\]\\)])`, "g"),
      placeholder
    ), value);
  const stableMarkdown = stableAssetContent(contentMarkdown);
  const stableSnapshot = stableAssetContent(snapshotHtml);
  const sourceContent = capture.capture_kind === "html"
    ? `${stableMarkdown}\u0000${stableSnapshot}`
    : stableMarkdown;
  const source = [title, author, publishedAt, sourceContent].join("\u0000");
  return {
    ...capture,
    title,
    summary,
    origin,
    author,
    published_at: publishedAt,
    content_markdown: contentMarkdown,
    snapshot_html: snapshotHtml,
    source_content_markdown: sourceContent,
    source_content_hash: await digest(new TextEncoder().encode(source)),
    assets: []
  };
}

async function fetchFromPage(source, pageUrl, signal) {
  const sameOrigin = new URL(source).origin === new URL(pageUrl).origin;
  const options = { cache: "no-store", signal };
  if (!sameOrigin) return fetch(source, { ...options, credentials: "omit" });
  try {
    return await fetch(source, { ...options, credentials: "include", redirect: "error" });
  } catch (_) {
    return fetch(source, { ...options, credentials: "omit" });
  }
}

async function cancelResponseBody(response) {
  try {
    await response.body?.cancel?.();
  } catch (_) {}
}

async function responseBlobWithin(response, limit) {
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > limit) {
    await cancelResponseBody(response);
    throw new Error("Capture media exceeds the 256 MiB per-file limit.");
  }
  if (!response.body?.getReader) {
    const blob = await response.blob();
    if (blob.size > limit) throw new Error("Capture media exceeds the 256 MiB per-file limit.");
    return blob;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      const bytes = next.value instanceof Uint8Array ? next.value : new Uint8Array(next.value);
      if (!bytes.byteLength) continue;
      size += bytes.byteLength;
      if (size > limit) {
        try {
          await reader.cancel();
        } catch (_) {}
        throw new Error("Capture media exceeds the 256 MiB per-file limit.");
      }
      chunks.push(bytes);
    }
  } finally {
    reader.releaseLock();
  }
  return new Blob(chunks, { type: response.headers.get("content-type") || "" });
}

async function fetchAttachments(capture, pageUrl) {
  const assets = (capture.remote_assets || [])
    .filter((asset) => !asset.media_type.startsWith("video/"))
    .slice(0, MAX_CAPTURE_ATTACHMENTS);
  const attachments = Array(assets.length);
  const signal = AbortSignal.timeout(30000);
  let capturedBytes = 0;
  for (const [index, asset] of assets.entries()) {
    try {
      const response = await fetchFromPage(asset.url, pageUrl, signal);
      const contentType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
      if (!response.ok || (contentType === "text/html" && asset.media_type !== "text/html")) {
        await cancelResponseBody(response);
        continue;
      }
      const bytes = await responseBlobWithin(
        response,
        Math.min(MAX_CAPTURE_ASSET_BYTES, MAX_CAPTURE_MEDIA_BYTES - capturedBytes)
      );
      capturedBytes += bytes.size;
      attachments[index] = { id: asset.id, mediaType: contentType, bytes };
    } catch (_) {
      // The authenticated page archive remains the fallback; an absent resource becomes partial.
    }
  }
  return attachments.filter(Boolean);
}

async function snapshotFor(tab, capture) {
  if (["document", "image"].includes(capture.capture_kind)) {
    const source = capture.remote_assets?.[0]?.url || tab.url || capture.origin;
    const response = await fetchFromPage(source, tab.url || source, AbortSignal.timeout(30000));
    if (!response.ok) {
      await cancelResponseBody(response);
      throw new Error(`The current file could not be read (${response.status}).`);
    }
    const mediaType = (response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
    if (mediaType.startsWith("video/")) {
      await cancelResponseBody(response);
      throw new Error("Video binaries are not saved.");
    }
    return {
      kind: "binary",
      mediaType,
      bytes: await responseBlobWithin(response, MAX_CAPTURE_ASSET_BYTES),
      attachments: []
    };
  }
  if (capture.capture_kind === "video" && !(capture.remote_assets || []).length) {
    return { kind: "none", mediaType: "", bytes: new Uint8Array(), attachments: [] };
  }
  const attachments = await fetchAttachments(capture, tab.url);
  return { kind: "none", mediaType: "", bytes: new Uint8Array(), attachments };
}

function encode(bytes) {
  let value = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    value += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(value);
}

function capturePayloadBytes(payload) {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload));
  if (payloadBytes.length > MAX_CAPTURE_PAYLOAD_BYTES) {
    throw new Error("Capture text exceeds the 32 MiB payload limit.");
  }
  return payloadBytes;
}

async function streamCapture(payload, snapshot) {
  const payloadBytes = capturePayloadBytes(payload);
  const mediaSizes = [byteLength(snapshot.bytes), ...snapshot.attachments.map(
    (attachment) => byteLength(attachment.bytes)
  )];
  if (mediaSizes.some((size) => size > MAX_CAPTURE_ASSET_BYTES)
      || payloadBytes.length + mediaSizes.reduce((total, size) => total + size, 0) > MAX_CAPTURE_STREAM_BYTES) {
    throw new Error("Capture media exceeds the 256 MiB per-file or 512 MiB total capture limit.");
  }
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
      if (typeof port.disconnect === "function") port.disconnect();
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
        try {
          for await (const chunk of byteChunks(bytes)) {
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
        } catch (error) {
          throw new Error(`Could not read ${channel}: ${error instanceof Error ? error.message : String(error)}`);
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
    iconUrl: "icon.png",
    title: "LBrain",
    message: `${receipt.status.replace("_", " ")}: ${receipt.target}`,
    buttons: receipt.open_uri ? [{ title: "Open in Obsidian" }] : []
  });
}

async function showFailure(error) {
  await chrome.notifications.create(`lbrain-error-${Date.now()}`, {
    type: "basic",
    iconUrl: "icon.png",
    title: "LBrain capture needs attention",
    message: error instanceof Error ? error.message : String(error)
  });
}

async function savePrepared(tab, capture) {
  const payload = await preparePayload(capture);
  const identityOrigin = payload.origin.trim().replace(/\/+$/, "");
  const recoveryPrefix = "capture-recovery:";
  const recoveryKey = `capture-recovery:${JSON.stringify([identityOrigin, payload.scope])}`;
  const stored = await chrome.storage.local.get(null);
  const storedRecovery = stored[recoveryKey];
  const captureId = await digest(new TextEncoder().encode(`${identityOrigin}\0${payload.scope}`));
  const targetPattern = new RegExp(`-${captureId.slice(0, 8)}(?:-v\\d+)?\\.md$`);
  const legacyRecoveries = [];
  for (const [key, value] of Object.entries(stored)) {
    if (key === recoveryKey || !key.startsWith(recoveryPrefix)) continue;
    const encoded = key.slice(recoveryPrefix.length);
    let legacyOrigin, legacyScope = "";
    try {
      [legacyOrigin, legacyScope = ""] = encoded.startsWith("[")
        ? JSON.parse(encoded)
        : encoded.split("\0", 2);
    } catch (_) {
      continue;
    }
    if (String(legacyOrigin || "").trim().replace(/\/+$/, "") !== identityOrigin) continue;
    if (legacyScope && legacyScope !== payload.scope) continue;
    if (targetPattern.test(String(value?.recovery_target || ""))) legacyRecoveries.push([key, value]);
  }
  const matchingLegacy = legacyRecoveries
    .map(([, value]) => value)
    .find((value) => value.source_content_hash === payload.source_content_hash);
  const recovery = storedRecovery?.source_content_hash === payload.source_content_hash
    ? storedRecovery
    : matchingLegacy;
  if (recovery) Object.assign(payload, recovery);
  capturePayloadBytes(payload);
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
  for (const [key] of legacyRecoveries) await chrome.storage.local.remove(key);
  await showReceipt(receipt);
  return receipt;
}

async function storeConfirmation(id, value) {
  const cache = await caches.open(CONFIRMATION_CACHE);
  await cache.put(
    `${CONFIRMATION_KEY_BASE}${encodeURIComponent(id)}`,
    new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } })
  );
}

async function confirmationResponse(id) {
  const key = `${CONFIRMATION_KEY_BASE}${encodeURIComponent(id)}`;
  if (typeof caches.match === "function") {
    return caches.match(key, { cacheName: CONFIRMATION_CACHE });
  }
  const cache = await caches.open(CONFIRMATION_CACHE);
  return cache.match(key);
}

async function storedCapture(id) {
  const response = await confirmationResponse(id);
  if (!response) throw new Error("This capture confirmation is no longer available.");
  return response.json();
}

async function persistPopupCapture(id) {
  if (await confirmationResponse(id)) {
    popupCaptures.delete(id);
    return true;
  }
  const prepared = popupCaptures.get(id);
  if (!prepared) return false;
  await storeConfirmation(id, prepared);
  popupCaptures.delete(id);
  return true;
}

const MISSING_POPUP_CAPTURE = "The prepared capture was lost after the extension worker restarted. Read the current page again.";

async function markPopupCaptureUnavailable(id) {
  return mutatePopupJob(async () => {
    const current = await popupJob();
    if (current?.id !== id || !current.preview || !["ready", "failed"].includes(current.phase)) return current;
    if (popupCaptures.has(id) || await confirmationResponse(id)) return current;
    const failed = { ...current, phase: "failed", preview: null, error: MISSING_POPUP_CAPTURE };
    delete failed.receipt;
    return persistPopupJob(failed);
  });
}

async function reconcilePopupJob(id) {
  return mutateReservation(async () => {
    const result = await mutatePopupJob(async () => {
      const current = await popupJob();
      if (current?.id !== id) return { job: null, orphaned: "" };
      const reservation = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
      const active = activeSavingReservation(reservation, id);
      const orphaned = !active && (
        current.phase === "saving"
        || (reservation?.id === id && reservation.state === "saving")
      );
      let next = current;
      if (current.phase === "saving" && !active) {
        next = {
          ...current,
          phase: "failed",
          error: "The previous save was interrupted. Retry to save this prepared capture."
        };
        delete next.receipt;
      }
      if (next.preview && ["ready", "failed"].includes(next.phase)
          && !popupCaptures.has(id) && !(await confirmationResponse(id))) {
        next = { ...next, phase: "failed", preview: null, error: MISSING_POPUP_CAPTURE };
        delete next.receipt;
      }
      if (next !== current) await persistPopupJob(next);
      return { job: next, orphaned: orphaned ? id : "" };
    });
    if (result.orphaned) await cleanupOrphanedSave(result.orphaned);
    return result.job;
  });
}

async function requirePersistedPopupCapture(id) {
  if (await persistPopupCapture(id)) return;
  await markPopupCaptureUnavailable(id);
  throw new Error(MISSING_POPUP_CAPTURE);
}

async function deleteConfirmation(id) {
  popupCaptures.delete(id);
  if (typeof caches.has === "function" && !(await caches.has(CONFIRMATION_CACHE))) return;
  const cache = await caches.open(CONFIRMATION_CACHE);
  await cache.delete(`${CONFIRMATION_KEY_BASE}${encodeURIComponent(id)}`);
}

function popupTab(value) {
  if (!Number.isInteger(value?.id) || !/^https?:\/\//.test(String(value.url || ""))) {
    throw new Error("The current tab cannot be captured.");
  }
  return { id: value.id, title: String(value.title || ""), url: String(value.url) };
}

function samePopupTab(left, right) {
  return left?.id === right.id && left?.url === right.url;
}

async function transitionPopupJob(id, phase, details = {}) {
  return mutatePopupJob(async () => {
    const current = await popupJob();
    if (current?.id !== id) return null;
    const next = { ...current, ...details, phase };
    if (phase !== "complete") delete next.receipt;
    if (phase !== "failed") delete next.error;
    return persistPopupJob(next);
  });
}

async function beginPopupSave(id, reservation) {
  return mutatePopupJob(async () => {
    const current = await popupJob();
    if (current?.id !== id) throw new Error("This capture confirmation is no longer available.");
    if (!["ready", "failed"].includes(current.phase)) {
      throw new Error("This capture is not ready; its save slot is already active.");
    }
    const saving = { ...current, phase: "saving" };
    delete saving.receipt;
    delete saving.error;
    reservation.created = Date.now();
    reservation.state = "saving";
    reservation.window_id = null;
    delete reservation.save_intent;
    delete reservation.awaiting_arm;
    await chrome.storage.session.set({
      [SAVE_RESERVATION]: reservation,
      [POPUP_JOB]: saving
    });
    await scheduleReservationExpiry(reservation.created);
    publishPopupJob(saving);
    return saving;
  });
}

function activeSavingReservation(value, id) {
  return saveReservation === id
    && value?.id === id
    && value.state === "saving";
}

function pendingPermissionReservation(value, id) {
  return value?.id === id
    && value.state === "permission_pending"
    && value.save_intent === true
    && Number.isFinite(value.created)
    && value.created > Date.now() - SAVE_RESERVATION_TTL;
}

async function reservationHasLiveOwner(value) {
  if (!value?.id) return false;
  if (Array.from(popupWatches.values()).includes(value.id)) return true;
  if (confirmationWindows.has(value.id)) return true;
  if (!Number.isInteger(value.window_id) || !chrome.windows?.get) return false;
  try {
    await chrome.windows.get(value.window_id);
    return true;
  } catch (_) {
    return false;
  }
}

function startPopupPreparation(job, tab, scope) {
  if (popupPreparations.has(job.id)) return;
  const preparation = (async () => {
    try {
      const capture = await prepareCapture(tab, scope);
      popupCaptures.set(job.id, { capture, tab });
      const ready = await transitionPopupJob(job.id, "ready", {
        preview: previewFor(capture, tab.url)
      });
      if (!ready) await deleteConfirmation(job.id);
    } catch (error) {
      await deleteConfirmation(job.id);
      await transitionPopupJob(job.id, "failed", {
        error: error instanceof Error ? error.message : String(error)
      });
    }
  })().finally(() => popupPreparations.delete(job.id));
  popupPreparations.set(job.id, preparation);
}

async function preparePopupJob(value, scope) {
  if (scope !== "page") throw new Error("The popup only captures the current page.");
  const tab = popupTab(value);
  return mutateReservation(async () => {
    const result = await mutatePopupJob(async () => {
      let current = await popupJob();
      let orphaned = "";
      const reservation = current
        ? (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION]
        : null;
      if (current?.phase === "saving") {
        if (activeSavingReservation(reservation, current.id)) {
          return { job: current, launch: false, replaced: "", orphaned: "" };
        }
        orphaned = current.id;
        current = { ...current, phase: "failed", error: "The previous save was interrupted. Retry to save this prepared capture." };
        delete current.receipt;
        await persistPopupJob(current);
      }
      if (current && !samePopupTab(current.tab, tab) && pendingPermissionReservation(reservation, current.id)) {
        return { job: current, launch: false, replaced: "", orphaned };
      }
      if (current && !samePopupTab(current.tab, tab)
          && Array.from(popupWatches.values()).includes(current.id)) {
        throw new Error("Another LBrain capture preview is already open.");
      }
      const missingPreparedCapture = Boolean(
        current
        && samePopupTab(current.tab, tab)
        && current.preview
        && ["ready", "failed"].includes(current.phase)
        && !popupCaptures.has(current.id)
        && !(await confirmationResponse(current.id))
      );
      if (current && samePopupTab(current.tab, tab) && !missingPreparedCapture) {
        const watched = Array.from(popupWatches.values()).includes(current.id);
        const pendingPermission = pendingPermissionReservation(reservation, current.id);
        if (current.phase !== "ready" || watched || pendingPermission) {
          return { job: current, launch: current.phase === "preparing", replaced: "", orphaned };
        }
      }
      const job = {
        id: crypto.randomUUID(),
        phase: "preparing",
        tab
      };
      await persistPopupJob(job);
      return { job, launch: true, replaced: current?.id || "", orphaned };
    });
    if (result.orphaned) await cleanupOrphanedSave(result.orphaned);
    if (result.replaced) {
      await deleteConfirmation(result.replaced);
      if (result.replaced !== result.orphaned) await releaseSaveReservation(result.replaced);
    }
    if (result.launch) startPopupPreparation(result.job, tab, scope);
    return result.job;
  });
}

async function cancelPopupJob(id) {
  const cancelled = await mutatePopupJob(async () => {
    const current = await popupJob();
    if (current?.id !== id || current.phase === "saving") return false;
    await chrome.storage.session.remove(POPUP_JOB);
    publishPopupJob(null);
    return true;
  });
  if (!cancelled) return { cancelled: false };
  await deleteConfirmation(id);
  await releaseSaveReservation(id);
  return { cancelled: true };
}

async function journaledPermissions() {
  const stored = (await chrome.storage.local.get(PERMISSION_JOURNAL))[PERMISSION_JOURNAL];
  return Array.isArray(stored) ? stored : [];
}

async function recordPermissions(origins) {
  if (!origins.length) return;
  await chrome.storage.local.set({
    [PERMISSION_JOURNAL]: Array.from(new Set([...(await journaledPermissions()), ...origins]))
  });
}

async function forgetPermissions(origins) {
  const remaining = (await journaledPermissions()).filter((origin) => !origins.includes(origin));
  if (remaining.length) await chrome.storage.local.set({ [PERMISSION_JOURNAL]: remaining });
  else await chrome.storage.local.remove(PERMISSION_JOURNAL);
}

async function removeRecordedPermissions(stored) {
  const origins = stored?.release_origins || [];
  if (!origins.length) return true;
  for (const origin of origins) {
    try {
      const removed = await chrome.permissions.remove({ origins: [origin] });
      if (!removed && await chrome.permissions.contains({ origins: [origin] })) return false;
      await forgetPermissions([origin]);
    } catch (_) {
      return false;
    }
  }
  return true;
}

async function clearConfirmations() {
  const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
  const releaseOrigins = Array.from(new Set([
    ...(stored?.release_origins || []),
    ...(await journaledPermissions())
  ]));
  popupCaptures.clear();
  await caches.delete(CONFIRMATION_CACHE);
  await chrome.storage.session.remove(POPUP_JOB);
  publishPopupJob(null);
  if (await removeRecordedPermissions({ release_origins: releaseOrigins })) {
    await chrome.storage.session.remove(SAVE_RESERVATION);
    await chrome.alarms?.clear?.(SAVE_RESERVATION_ALARM);
  } else {
    await scheduleReservationExpiry(Date.now(), true);
  }
}

async function releaseSaveReservation(id) {
  if (saveReservation === id) saveReservation = null;
  try {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (stored?.id === id) {
      const release = {
        ...stored,
        release_origins: Array.from(new Set([
          ...(stored.release_origins || []),
          ...(await journaledPermissions())
        ]))
      };
      if (await removeRecordedPermissions(release)) {
        await chrome.storage.session.remove(SAVE_RESERVATION);
        await chrome.alarms?.clear?.(SAVE_RESERVATION_ALARM);
      } else {
        await scheduleReservationExpiry(Date.now(), true);
      }
    }
  } catch (_) {
    // Reservation expiry remains the crash-safe fallback.
  }
}

async function cleanupOrphanedSave(id) {
  if (saveReservation === id) saveReservation = null;
  const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
  if (stored?.id === id) {
    const release = {
      ...stored,
      release_origins: Array.from(new Set([
        ...(stored.release_origins || []),
        ...(await journaledPermissions())
      ]))
    };
    if (await removeRecordedPermissions(release)) {
      await chrome.storage.session.remove(SAVE_RESERVATION);
      await chrome.alarms?.clear?.(SAVE_RESERVATION_ALARM);
    } else {
      await scheduleReservationExpiry(Date.now(), true);
    }
    return;
  }
  if (!stored?.id) {
    if (await removeRecordedPermissions({ release_origins: await journaledPermissions() })) {
      await chrome.alarms?.clear?.(SAVE_RESERVATION_ALARM);
    } else {
      await scheduleReservationExpiry(Date.now(), true);
    }
  }
}

function requestedPermissionOrigins(message) {
  return Array.isArray(message.permission_origins)
    ? message.permission_origins.map(exactPermissionOrigin).filter(Boolean)
    : [];
}

async function reserveConfirmation(message, state = "") {
  const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
  if (stored?.id === message.id && stored.state === "saving") {
    throw new Error("This LBrain capture is already being saved.");
  }
  if (stored?.id && stored.id !== message.id
      && (activeSavingReservation(stored, stored.id)
        || pendingPermissionReservation(stored, stored.id)
        || await reservationHasLiveOwner(stored))) {
    throw new Error("Another LBrain capture is already being saved.");
  }
  if (stored?.id && stored.id !== message.id && !await removeRecordedPermissions(stored)) {
    throw new Error("The previous temporary permission could not be released.");
  }
  const same = stored?.id === message.id ? { ...stored } : {};
  if (same.save_intent && (!Number.isFinite(same.created)
      || same.created <= Date.now() - SAVE_RESERVATION_TTL)) {
    delete same.save_intent;
    delete same.awaiting_arm;
  }
  const reservation = {
    ...same,
    id: message.id,
    created: Date.now(),
    window_id: Number.isInteger(message.window_id) ? message.window_id : (same.window_id ?? null),
    allowed_origins: Array.from(new Set([
      ...(same.allowed_origins || []),
      ...requestedPermissionOrigins(message)
    ])),
    release_origins: Array.from(new Set([
      ...(same.release_origins || []),
      ...(await journaledPermissions())
    ]))
  };
  if (state) reservation.state = state;
  await chrome.storage.session.set({ [SAVE_RESERVATION]: reservation });
  await scheduleReservationExpiry(reservation.created);
  saveReservation = message.id;
  return reservation;
}

async function preflightConfirmation(message, sender) {
  const job = await popupJob();
  const popup = job?.id === message.id && ["ready", "failed"].includes(job.phase);
  const legacy = Number.isInteger(message.window_id) && (
    confirmationWindows.get(message.id) === message.window_id
    || (sender?.url === chrome.runtime.getURL(`confirm.html?id=${encodeURIComponent(message.id)}`)
      && sender?.tab?.windowId === message.window_id)
  );
  if (!popup && !legacy) {
    throw new Error("This capture confirmation is no longer available.");
  }
  const reservation = await reserveConfirmation(message, "permission_pending");
  try {
    const missing = [];
    for (const origin of reservation.allowed_origins) {
      if (!await chrome.permissions.contains({ origins: [origin] })) missing.push(origin);
    }
    await recordPermissions(missing);
    reservation.release_origins = Array.from(new Set([
      ...reservation.release_origins,
      ...missing
    ]));
    if (missing.length) reservation.state = "permission_pending";
    else delete reservation.state;
    await chrome.storage.session.set({ [SAVE_RESERVATION]: reservation });
    return { reserved: true, missing };
  } catch (error) {
    return {
      reserved: true,
      missing: [],
      warning: `Cross-origin media access was skipped: ${error instanceof Error ? error.message : String(error)}`
    };
  }
}

async function armedPermissionsReady(reservation) {
  if (!reservation.allowed_origins?.length) return true;
  try {
    return await chrome.permissions.contains({ origins: reservation.allowed_origins });
  } catch (_) {
    return false;
  }
}

function runArmedDecision(id) {
  if (armedDecisions.has(id)) return armedDecisions.get(id);
  const decision = decideConfirmation({ id }).finally(() => armedDecisions.delete(id));
  armedDecisions.set(id, decision);
  return decision;
}

async function maybeRunArmedDecision(id, allowMissing = false) {
  if (armedDecisions.has(id)) return armedDecisions.get(id);
  const ready = await mutateReservation(async () => {
    const reservation = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (reservation?.id !== id || !reservation.save_intent) return false;
    const fresh = Number.isFinite(reservation.created)
      && reservation.created > Date.now() - SAVE_RESERVATION_TTL;
    if (!fresh) {
      delete reservation.save_intent;
      delete reservation.awaiting_arm;
      await chrome.storage.session.set({ [SAVE_RESERVATION]: reservation });
      if (saveReservation === id) saveReservation = null;
      if (await removeRecordedPermissions(reservation)) {
        await chrome.storage.session.remove(SAVE_RESERVATION);
        await chrome.alarms?.clear?.(SAVE_RESERVATION_ALARM);
      } else {
        await scheduleReservationExpiry(Date.now(), true);
      }
      await mutatePopupJob(async () => {
        const current = await popupJob();
        if (current?.id !== id || current.phase !== "ready") return;
        const failed = {
          ...current,
          phase: "failed",
          error: "The permission request expired before saving. Retry to continue."
        };
        delete failed.receipt;
        await persistPopupJob(failed);
      });
      return false;
    }
    return allowMissing || await armedPermissionsReady(reservation);
  });
  if (!ready) return null;
  return runArmedDecision(id);
}

async function armConfirmation(message) {
  if (armedDecisions.has(message.id)) return { armed: true, started: true };
  const reservation = await mutateReservation(async () => {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    const job = await popupJob();
    if (job?.id === message.id && (job.phase === "saving" || job.phase === "complete"
        || (job.phase === "failed" && stored?.id !== message.id))) return null;
    if (stored?.id !== message.id || stored.state !== "permission_pending"
        || job?.id !== message.id || !["ready", "failed"].includes(job.phase)) {
      throw new Error("This capture permission request is no longer available.");
    }
    await requirePersistedPopupCapture(message.id);
    stored.created = Date.now();
    stored.save_intent = true;
    delete stored.awaiting_arm;
    await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
    await scheduleReservationExpiry(stored.created);
    return stored;
  });
  if (!reservation) return { armed: true, started: true };
  const started = await armedPermissionsReady(reservation);
  if (started) runArmedDecision(message.id).catch(() => {});
  return { armed: true, started };
}

async function markPopupSaveIntent(message) {
  return mutateReservation(async () => {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    const job = await popupJob();
    if (job?.id === message.id && ["saving", "complete"].includes(job.phase)) return;
    if (stored?.id !== message.id || stored.state !== "permission_pending"
        || job?.id !== message.id || !["ready", "failed"].includes(job.phase)) {
      throw new Error("This capture permission request is no longer available.");
    }
    if (stored.save_intent && !stored.awaiting_arm) return;
    await requirePersistedPopupCapture(message.id);
    stored.created = Date.now();
    stored.save_intent = true;
    stored.awaiting_arm = true;
    await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
    await scheduleReservationExpiry(stored.created);
  });
}

async function permissionResult(message) {
  const decision = await maybeRunArmedDecision(message.id, true);
  if (decision) return decision;
  const job = await popupJob();
  if (job?.id === message.id && ["saving", "complete", "failed"].includes(job.phase)) return job;
  throw new Error("This capture save intent is no longer available.");
}

async function decideConfirmation(message) {
  const { popupFlow } = await mutateReservation(async () => {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (stored?.id !== message.id) throw new Error("This capture no longer owns the save slot.");
    const popup = await popupJob();
    const popupFlow = popup?.id === message.id;
    if (popupFlow) {
      await requirePersistedPopupCapture(message.id);
      await beginPopupSave(message.id, stored);
    } else {
      if (stored.state === "saving") throw new Error("This LBrain capture is already being saved.");
      stored.created = Date.now();
      stored.state = "saving";
      stored.window_id = null;
      await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
      await scheduleReservationExpiry(stored.created);
    }
    saveReservation = message.id;
    return { popupFlow };
  });
  let released = false;
  try {
    const pending = await storedCapture(message.id);
    if (!pending || typeof pending !== "object" || !pending.capture || !pending.tab) {
      throw new Error("This capture confirmation is no longer available.");
    }
    if (!popupFlow) {
      const receipt = await savePrepared(pending.tab, pending.capture);
      await deleteConfirmation(message.id);
      confirmationWindows.delete(message.id);
      return receipt;
    }
    const receipt = await savePrepared(pending.tab, pending.capture);
    const complete = await transitionPopupJob(message.id, "complete", { receipt });
    await deleteConfirmation(message.id);
    return complete;
  } catch (error) {
    await mutateReservation(() => releaseSaveReservation(message.id));
    released = true;
    if (popupFlow && (await popupJob())?.phase === "saving") {
      await transitionPopupJob(message.id, "failed", {
        error: error instanceof Error ? error.message : String(error)
      });
      await showFailure(error).catch(() => {});
    }
    if (!popupFlow) {
      await deleteConfirmation(message.id);
    }
    throw error;
  } finally {
    if (!released) await mutateReservation(() => releaseSaveReservation(message.id));
  }
}

async function confirmCapture(tab, capture) {
  const id = crypto.randomUUID();
  return new Promise(async (resolve, reject) => {
    confirmations.set(id, {
      preview: previewFor(capture, tab.url),
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message?.type?.startsWith("confirmation.")) return;
  if (message.type === "confirmation.prepare") {
    preparePopupJob(message.tab, message.scope).then(
      sendResponse,
      (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) })
    );
    return true;
  }
  if (typeof message.id !== "string") return;
  if (message.type === "confirmation.decide") {
    decideConfirmation(message).then(
      sendResponse,
      (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) })
    );
    return true;
  }
  if (message.type === "confirmation.arm") {
    armConfirmation(message).then(
      sendResponse,
      (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) })
    );
    return true;
  }
  if (message.type === "confirmation.permission_result") {
    permissionResult(message).then(
      sendResponse,
      (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) })
    );
    return true;
  }
  mutateReservation(async () => {
    if (message.type === "confirmation.cancel") return cancelPopupJob(message.id);
    if (message.type === "confirmation.preflight") return preflightConfirmation(message, sender);
    if (message.type === "confirmation.reserve") {
      await reserveConfirmation(message);
      return { reserved: true };
    }
    if (message.type === "confirmation.permissions") {
      const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
      const cleanup = message.cleanup === true;
      if (stored?.id !== message.id && !cleanup) {
        throw new Error("This capture no longer owns the save slot.");
      }
      const allowed = new Set(stored?.allowed_origins || []);
      const added = Array.isArray(message.origins)
        ? message.origins.filter((origin) => cleanup
          ? /^https?:\/\/[^/]+\/\*$/.test(origin)
          : allowed.has(origin))
        : [];
      await recordPermissions(added);
      if (stored?.id !== message.id) {
        const transferred = added.filter((origin) => allowed.has(origin));
        if (stored && transferred.length) {
          stored.release_origins = Array.from(new Set([
            ...(stored.release_origins || []),
            ...transferred
          ]));
          await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
        }
        const released = await removeRecordedPermissions({
          release_origins: added.filter((origin) => !allowed.has(origin))
        });
        return { recorded: true, released: released && !transferred.length };
      }
      stored.release_origins = Array.from(new Set([
        ...(stored.release_origins || []),
        ...added
      ]));
      await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
      if (cleanup && stored.state !== "saving") {
        await releaseSaveReservation(message.id);
        const remaining = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
        return { recorded: true, released: remaining?.id !== message.id };
      }
      return { recorded: true };
    }
    if (message.type === "confirmation.release") {
      await releaseSaveReservation(message.id);
      return { released: true };
    }
    return undefined;
  }).then(sendResponse, (error) => sendResponse({ error: error instanceof Error ? error.message : String(error) }));
  return true;
});

chrome.permissions?.onAdded?.addListener((permissions) => {
  (async () => {
    const armedId = await mutateReservation(async () => {
      const reservation = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
      const added = requestedPermissionOrigins({ permission_origins: permissions?.origins });
      if (added.length) {
        await recordPermissions(added);
        const allowed = new Set(reservation?.allowed_origins || []);
        const transferred = added.filter((origin) => allowed.has(origin));
        if (reservation && transferred.length) {
          reservation.release_origins = Array.from(new Set([
            ...(reservation.release_origins || []),
            ...transferred
          ]));
          await chrome.storage.session.set({ [SAVE_RESERVATION]: reservation });
        }
        await removeRecordedPermissions({
          release_origins: added.filter((origin) => !allowed.has(origin))
        });
      }
      return reservation?.save_intent && !reservation.awaiting_arm ? reservation.id : "";
    });
    if (armedId) await maybeRunArmedDecision(armedId);
  })().catch(() => {});
});

chrome.alarms?.onAlarm?.addListener((alarm) => {
  if (alarm?.name !== SAVE_RESERVATION_ALARM) return;
  return mutateReservation(async () => {
    const stored = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (!stored?.id) {
      if (await removeRecordedPermissions({ release_origins: await journaledPermissions() })) {
        await chrome.alarms.clear(SAVE_RESERVATION_ALARM);
      } else {
        await scheduleReservationExpiry(Date.now(), true);
      }
      return;
    }
    const fresh = Number.isFinite(stored.created)
      && stored.created > Date.now() - SAVE_RESERVATION_TTL;
    if (fresh) {
      await scheduleReservationExpiry(stored.created);
      return;
    }
    const live = stored.state === "saving"
      ? activeSavingReservation(stored, stored.id)
      : await reservationHasLiveOwner(stored);
    if (live) {
      await scheduleReservationExpiry(Date.now(), true);
      return;
    }
    if (stored.state === "saving") {
      await mutatePopupJob(async () => {
        const current = await popupJob();
        if (current?.id !== stored.id || current.phase !== "saving") return;
        let failed = {
          ...current,
          phase: "failed",
          error: "The previous save was interrupted. Retry to save this prepared capture."
        };
        delete failed.receipt;
        if (failed.preview && !popupCaptures.has(stored.id) && !(await confirmationResponse(stored.id))) {
          failed = { ...failed, preview: null, error: MISSING_POPUP_CAPTURE };
        }
        await persistPopupJob(failed);
      });
    }
    stored.release_origins = Array.from(new Set([
      ...(stored.release_origins || []),
      ...(await journaledPermissions())
    ]));
    await chrome.storage.session.set({ [SAVE_RESERVATION]: stored });
    await cleanupOrphanedSave(stored.id);
    const remaining = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
    if (remaining?.id === stored.id || (await journaledPermissions()).length) {
      await scheduleReservationExpiry(Date.now(), true);
    } else {
      await chrome.alarms.clear(SAVE_RESERVATION_ALARM);
    }
  }).catch(() => scheduleReservationExpiry(Date.now(), true).catch(() => {}));
});

chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "lbrain-popup") {
    popupWatches.set(port, "");
    port.onMessage.addListener((message) => {
      if (message?.type === "arm" && typeof message.id === "string") {
        if (popupWatches.get(port) === message.id) markPopupSaveIntent(message).catch(() => {});
        return;
      }
      if (message?.type !== "watch" || typeof message.id !== "string") return;
      popupWatches.set(port, message.id);
      reconcilePopupJob(message.id).then((job) => {
        try {
          port.postMessage({ type: "job", job: job?.id === message.id ? job : null });
        } catch (_) {
          popupWatches.delete(port);
        }
      });
    });
    port.onDisconnect.addListener(() => {
      const id = popupWatches.get(port);
      popupWatches.delete(port);
      if (!id) return;
      if (Array.from(popupWatches.values()).includes(id)) return;
      mutateReservation(async () => {
        if (Array.from(popupWatches.values()).includes(id)) return;
        const reservation = (await chrome.storage.session.get(SAVE_RESERVATION))[SAVE_RESERVATION];
        if (reservation?.id === id && (
          reservation.state === "saving" || pendingPermissionReservation(reservation, id)
        )) return;
        await cancelPopupJob(id);
      }).catch(() => {});
    });
    return;
  }
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
  mutateReservation(async () => {
    const value = await chrome.storage.session.get(SAVE_RESERVATION);
    const stored = value[SAVE_RESERVATION];
    if (stored?.state !== "saving" && stored?.window_id === windowId) await releaseSaveReservation(stored.id);
  }).catch(() => {});
  for (const [id, savedWindowId] of confirmationWindows) {
    if (savedWindowId !== windowId) continue;
    confirmationWindows.delete(id);
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

chrome.notifications.onButtonClicked.addListener(async (id, button) => {
  if (button !== 0) return;
  const value = await chrome.storage.session.get(id);
  if (value[id]) await chrome.tabs.create({ url: value[id] });
});

globalThis.LBrainCaptureWorker = {
  directCapture, popupJob, preparePayload, preparePopupJob, previewFor, savePrepared, snapshotFor, streamCapture,
  capturePayloadBytes, responseBlobWithin
};
