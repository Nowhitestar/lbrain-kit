(() => {
  const NOISE = [
    "nav",
    "aside",
    "footer",
    "form",
    "script",
    "style",
    "noscript",
    "template",
    "[hidden]",
    "[aria-hidden='true']",
    "[role='navigation']",
    "[role='banner']",
    "[role='complementary']",
    "[role='group']",
    ".advertisement",
    ".ads",
    ".sponsor",
    ".sponsored",
    ".recommendations",
    ".related-posts",
    ".comments"
  ].join(",");

  const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
  const markdownText = (value) => value
    .replace(/([\\`*_[\]<>!|~#])/g, "\\$1")
    .replace(/(^|\n)([ \t]{0,3})([=-]+)(?=[ \t]*(?:\n|$))/g, "$1$2\\$3")
    .replace(/(^|\n)([ \t]{0,3})(~{3,})/g, "$1$2\\$3")
    .replace(/(^|\n) {4}/g, "$1&#32;   ")
    .replace(/(^|\n)\t/g, "$1&#9;")
    .replace(/(^|\n)([ \t]{0,3})([#>+-])(?=\s)/g, "$1$2\\$3")
    .replace(/(^|\n)([ \t]{0,3}\d+)([.)])(?=\s)/g, "$1$2\\$3");
  const markdownLabel = (value) => markdownText(String(value || "")).replace(/\s+/g, " ").trim();
  const markdownUrl = (value) => {
    const clean = String(value || "").replace(/\\/g, "%5C").replace(/</g, "%3C").replace(/>/g, "%3E").replace(/\|/g, "%7C");
    return /[()[\]]/.test(clean) ? `<${clean}>` : clean;
  };
  const url = (value) => {
    if (!value) return "";
    try {
      const parsed = new URL(value, document.baseURI);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  };
  const imageUrl = (node) => {
    const responsive = (node.getAttribute("srcset")
      || node.closest("picture")?.querySelector("source[srcset]")?.getAttribute("srcset")
      || "").split(",", 1)[0].trim().split(/\s+/, 1)[0];
    const source = url(
    node.getAttribute("data-src")
      || node.getAttribute("data-original")
      || node.currentSrc
      || node.getAttribute("src")
      || responsive
      || ""
    );
    return source === url(location.href) ? "" : source;
  };
  const pinRenderedImages = (originals, copies) => originals.forEach((image, index) => {
    const source = imageUrl(image);
    if (source) copies[index]?.setAttribute("src", source);
  });
  const renderedClone = (node) => {
    const clone = node.cloneNode(true);
    pinRenderedImages(Array.from(node.querySelectorAll("img")), Array.from(clone.querySelectorAll("img")));
    const originals = Array.from(node.querySelectorAll("*"));
    const copies = Array.from(clone.querySelectorAll("*"));
    originals.forEach((original, index) => {
      const media = original.closest("audio, video");
      const hiddenVideo = media?.tagName === "VIDEO" && hiddenByStyle(media);
      const inlineHiddenMedia = media && /(?:display\s*:\s*none|visibility\s*:\s*hidden)/i.test(media.getAttribute("style") || "");
      if (hiddenVideo || inlineHiddenMedia || hiddenByStyle(media ? media.parentElement : original)) copies[index]?.remove();
    });
    return clone;
  };
  const hiddenByStyle = (node) => {
    for (let current = node; current; current = current.parentElement) {
      if (current.hidden || current.getAttribute("aria-hidden") === "true") return true;
      const style = getComputedStyle(current);
      if (style.display === "none" || ["hidden", "collapse"].includes(style.visibility)
        || style.contentVisibility === "hidden" || style.opacity === "0") return true;
    }
    return false;
  };
  const visibleRoot = (node) => Boolean(node) && !node.closest(NOISE) && !hiddenByStyle(node);
  const children = (node, renderer) => Array.from(node.childNodes).map(renderer).join("");
  const transcriptSelector = "ytd-transcript-renderer, ytd-transcript-segment-list-renderer, [data-testid='transcript'], [data-lbrain-transcript]";

  function inline(node) {
    if (node.nodeType === Node.TEXT_NODE) return markdownText((node.nodeValue || "").replace(/\s+/g, " "));
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    if (node.matches(transcriptSelector)) return "";
    const tag = node.tagName;
    if (tag === "BR") return "\n";
    if (tag === "IMG") {
      const source = imageUrl(node);
      return source ? `![${markdownLabel(node.getAttribute("alt"))}](${markdownUrl(source)})` : "";
    }
    if (tag === "AUDIO") {
      const source = url(node.getAttribute("src") || node.querySelector("source[src]")?.getAttribute("src") || "");
      return source ? `[Audio](${markdownUrl(source)})` : "";
    }
    if (tag === "CODE") {
      const value = node.textContent || "";
      const fence = "`".repeat(Math.max(1, Math.max(0, ...Array.from(value.matchAll(/`+/g), (match) => match[0].length)) + 1));
      const padded = /^`|`$|^ | $/.test(value) ? ` ${value} ` : value;
      return `${fence}${padded}${fence}`;
    }
    const value = children(node, inline).replace(/\s+/g, " ");
    if (!value.trim() && tag !== "A") return "";
    if (tag === "A") {
      const href = url(node.getAttribute("href") || "");
      const label = node.querySelector("img")
        ? value.trim()
        : value.trim();
      return href && label ? `[${label}](${markdownUrl(href)})` : value;
    }
    if (tag === "STRONG" || tag === "B") return `**${value.trim()}**`;
    if (tag === "EM" || tag === "I") return `*${value.trim()}*`;
    if (tag === "DEL" || tag === "S") return `~~${value.trim()}~~`;
    return value;
  }

  function list(node, ordered, depth = 0) {
    return Array.from(node.children)
      .filter((item) => item.tagName === "LI")
      .map((item, index) => {
        const nested = Array.from(item.children).filter((child) => ["UL", "OL"].includes(child.tagName));
        const clone = item.cloneNode(true);
        clone.querySelectorAll(":scope > ul, :scope > ol").forEach((child) => child.remove());
        const marker = ordered ? `${index + 1}.` : "-";
        const line = `${"  ".repeat(depth)}${marker} ${inline(clone).trim()}`;
        const tail = nested.map((child) => list(child, child.tagName === "OL", depth + 1)).join("");
        return `${line}\n${tail}`;
      })
      .join("");
  }

  function table(node) {
    const rows = Array.from(node.querySelectorAll("tr")).map((row) =>
      Array.from(row.querySelectorAll(":scope > th, :scope > td")).map((cell) => inline(cell).trim())
    );
    if (!rows.length || !rows[0].length) return "";
    const width = Math.max(...rows.map((row) => row.length));
    const line = (row) => `| ${Array.from({ length: width }, (_, index) => row[index] || "").join(" | ")} |`;
    return `${line(rows[0])}\n${line(Array(width).fill("---"))}\n${rows.slice(1).map(line).join("\n")}\n\n`;
  }

  function block(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      const value = node.nodeValue || "";
      return value.trim() ? markdownText(value) : /[\r\n]/.test(value) ? "\n" : value ? " " : "";
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = node.tagName;
    if (node.matches?.(transcriptSelector)) return "";
    if (node.matches?.("article[data-testid='tweet']")) {
      return Array.from(node.querySelectorAll(
        "[data-testid='tweetText'], [data-testid='quoteTweet'], [data-testid='tweetPhoto']"
      )).filter((part) => !part.parentElement?.closest("[data-testid='quoteTweet'], [data-testid='tweetPhoto']"))
        .map(block).join("");
    }
    if (node.matches?.("[data-testid='User-Name']")) {
      const author = xAuthor(node);
      const handle = text(Array.from(node.querySelectorAll("a[href]"))
        .find((link) => !link.querySelector("time") && text(link).startsWith("@")));
      const timestamp = node.querySelector("a[href*='/status/'] time");
      const status = timestamp?.closest("a");
      const published = timestamp && status
        ? `[${markdownLabel(text(timestamp))}](${markdownUrl(url(status.getAttribute("href") || ""))})`
        : "";
      return `**${markdownLabel(author)}${handle ? ` (${markdownLabel(handle)})` : ""}**${published ? ` — ${published}` : ""}\n\n`;
    }
    if (node.matches?.("[data-testid='tweetText']")) return `${inline(node).trim()}\n\n`;
    if (node.matches?.("[data-testid='quoteTweet']")) {
      const value = children(node, block).trim() || inline(node).trim();
      return `${value.split("\n").map((line) => `> ${line}`.trimEnd()).join("\n")}\n\n`;
    }
    if (node.matches?.("[data-testid='tweetPhoto']")) {
      return `${Array.from(node.querySelectorAll("img")).map(block).join("").trim()}\n\n`;
    }
    if (node.classList?.contains("public-DraftStyleDefault-block")) return `${inline(node).trim()}\n\n`;
    if (/^H[1-6]$/.test(tag)) return `${"#".repeat(Number(tag[1]))} ${inline(node).trim()}\n\n`;
    if (tag === "P") return `${inline(node).trim()}\n\n`;
    if (tag === "UL" || tag === "OL") return `${list(node, tag === "OL")}\n`;
    if (tag === "BLOCKQUOTE") {
      const value = children(node, block).trim();
      return `${value.split("\n").map((line) => `> ${line}`.trimEnd()).join("\n")}\n\n`;
    }
    if (tag === "PRE") {
      const language = (node.querySelector("code")?.className || "").match(/language-([\w+-]+)/)?.[1] || "";
      const value = (node.textContent || "").trim();
      const fence = "`".repeat(Math.max(3, Math.max(0, ...Array.from(value.matchAll(/`+/g), (match) => match[0].length)) + 1));
      return `${fence}${language}\n${value}\n${fence}\n\n`;
    }
    if (tag === "TABLE") return table(node);
    if (tag === "HR") return "---\n\n";
    if (tag === "FIGURE") {
      const media = Array.from(node.children).filter((child) => child.tagName !== "FIGCAPTION").map(block).join("").trim();
      const caption = text(node.querySelector("figcaption"));
      return `${media}${caption ? `\n\n*${markdownText(caption)}*` : ""}\n\n`;
    }
    if (tag === "A" && node.querySelector("img")) return `${inline(node).trim()}\n\n`;
    if (tag === "IMG") return `${inline(node)}\n\n`;
    if (["DIV", "SECTION", "ARTICLE", "MAIN", "HEADER", "BODY"].includes(tag)) return children(node, block);
    return inline(node);
  }

  function selectedRoot() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const container = document.createElement("article");
    container.append(range.cloneContents());
    const originals = Array.from(document.querySelectorAll("img")).filter((image) => range.intersectsNode(image));
    pinRenderedImages(originals, Array.from(container.querySelectorAll("img")));
    return container;
  }

  function xStatusUrl(value) {
    const href = url(value);
    if (!href) return null;
    const parsed = new URL(href);
    const match = parsed.pathname.match(/^\/([^/]+)\/status\/(\d+)/);
    return match ? {
      href: `${parsed.origin}/${match[1]}/status/${match[2]}`,
      handle: match[1].toLowerCase(),
      id: match[2]
    } : null;
  }

  function xStatus(tweet) {
    const status = xStatusUrl(tweet?.querySelector("a[href*='/status/']")?.getAttribute("href") || "");
    return status ? {
      ...status,
      publishedAt: tweet.querySelector("time[datetime]")?.getAttribute("datetime") || ""
    } : null;
  }

  function xAuthor(node) {
    return text(node?.querySelector("[data-testid='User-Name'] span"));
  }

  function xThread(tweets, rootStatus, markedThread = false) {
    const root = document.createElement("article");
    let previous = null;
    let contiguous = markedThread;
    const accepted = new Set();
    const sources = [];
    const start = tweets.findIndex((tweet) => xStatus(tweet)?.id === rootStatus.id);
    if (start < 0) return null;
    for (const tweet of tweets.slice(start)) {
      const status = xStatus(tweet);
      if (!status) continue;
      if (status.handle !== rootStatus.handle) {
        if (accepted.size) contiguous = false;
        continue;
      }
      if (previous) {
        const tweetContent = tweet.querySelector(
          "[data-testid='tweetText'], [data-testid='tweetPhoto'], [data-testid='videoPlayer'], video"
        );
        const replyTarget = tweet.getAttribute("data-lbrain-reply-to")
          || tweet.getAttribute("data-in-reply-to-status-id")
          || Array.from(tweet.querySelectorAll("a[href*='/status/']"))
            .filter((link) => !link.closest("[data-testid='User-Name']")
              && !link.closest("[data-testid='tweetText']")
              && !link.closest("[data-testid='quoteTweet']")
              && tweetContent
              && Boolean(link.compareDocumentPosition(tweetContent) & Node.DOCUMENT_POSITION_FOLLOWING))
            .map((link) => (link.getAttribute("href") || "").match(/\/status\/(\d+)/)?.[1])
            .find((id) => id && id !== status.id);
        const selfReply = Array.from(tweet.querySelectorAll("a[href]"))
          .some((link) => text(link).replace(/^@/, "").toLowerCase() === rootStatus.handle
            && !link.closest("[data-testid='User-Name']")
            && !link.closest("[data-testid='tweetText']")
            && !link.closest("[data-testid='quoteTweet']")
            && tweetContent
            && Boolean(link.compareDocumentPosition(tweetContent) & Node.DOCUMENT_POSITION_FOLLOWING)
            && url(link.getAttribute("href") || "")
            && new URL(url(link.getAttribute("href") || "")).pathname.toLowerCase() === `/${rootStatus.handle}`);
        const chronological = !previous.publishedAt || !status.publishedAt
          || Date.parse(status.publishedAt) >= Date.parse(previous.publishedAt);
        const related = replyTarget ? accepted.has(replyTarget) : selfReply || contiguous;
        if (!related || !chronological) continue;
        root.append(document.createElement("hr"));
      }
      root.append(renderedClone(tweet));
      previous = status;
      accepted.add(status.id);
      sources.push(status);
    }
    if (accepted.size > 1) {
      const heading = document.createElement("h2");
      heading.textContent = "Thread sources";
      const list = document.createElement("ol");
      for (const [index, status] of sources.entries()) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = status.href;
        link.textContent = `Post ${index + 1}`;
        item.append(link);
        list.append(item);
      }
      root.append(heading, list);
    }
    return accepted.size > 1 ? root : null;
  }

  const ATTACHMENTS = {
    pdf: "application/pdf",
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
    txt: "text/plain",
    md: "text/markdown",
    vtt: "text/vtt",
    srt: "application/x-subrip"
  };

  function asset(source, index, folder, mediaType) {
    const fallback = `asset-${String(index + 1).padStart(3, "0")}.bin`;
    let decoded = fallback;
    try {
      decoded = decodeURIComponent(new URL(source).pathname.split("/").pop() || fallback);
    } catch (_) {}
    const basename = (decoded.replace(/[^A-Za-z0-9._-]+/g, "-") || fallback).slice(0, 120);
    return {
      id: `asset-${index + 1}`,
      url: source,
      name: `${folder}/${String(index + 1).padStart(3, "0")}-${basename}`,
      media_type: mediaType
    };
  }

  function media(root, videoOnly = false) {
    const seen = new Set();
    const candidates = [];
    for (const image of root.querySelectorAll("img")) {
      const source = imageUrl(image);
      const extension = new URL(source || "data:,x").pathname.split(".").pop()?.toLowerCase();
      const mediaType = ({ jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp", svg: "image/svg+xml" })[extension]
        || "application/octet-stream";
      candidates.push([source, "images", mediaType]);
    }
    for (const image of root.querySelectorAll("svg image")) {
      candidates.push([url(image.getAttribute("href") || image.getAttribute("xlink:href") || ""), "images", "image/svg+xml"]);
    }
    for (const poster of root.querySelectorAll("video[poster]")) {
      candidates.push([url(poster.getAttribute("poster") || ""), "images", "application/octet-stream"]);
    }
    for (const audio of root.querySelectorAll("audio[src], audio source[src]")) {
      const source = url(audio.getAttribute("src") || "");
      const extension = new URL(source || "data:,x").pathname.split(".").pop()?.toLowerCase();
      const mediaType = ({ mp3: "audio/mpeg", m4a: "audio/mp4", aac: "audio/aac", ogg: "audio/ogg", wav: "audio/wav", flac: "audio/flac" })[extension]
        || (audio.getAttribute("type") || "application/octet-stream").split(";", 1)[0];
      candidates.push([source, "audio", mediaType]);
    }
    for (const link of root.querySelectorAll("a[href]")) {
      const source = url(link.getAttribute("href") || "");
      const downloadable = link.hasAttribute("download");
      const download = link.getAttribute("download") || "";
      const extension = `${download || new URL(source || "data:,x").pathname}`.split(".").pop()?.toLowerCase();
      const declared = (link.getAttribute("type") || "").split(";", 1)[0].trim().toLowerCase();
      const mediaType = ((extension === "md" || extension === "txt") && !downloadable ? "" : ATTACHMENTS[extension])
        || (Object.values(ATTACHMENTS).includes(declared) ? declared : "")
        || (/\bpdf\b/i.test(text(link)) ? "application/pdf" : "");
      if (mediaType) candidates.push([source, "documents", mediaType]);
    }
    for (const track of root.querySelectorAll("track[kind='subtitles'], track[kind='captions']")) {
      const source = url(track.getAttribute("src") || "");
      const extension = new URL(source || "data:,x").pathname.split(".").pop()?.toLowerCase();
      candidates.push([source, "transcripts", ATTACHMENTS[extension] || "text/vtt"]);
    }
    return candidates
      .filter(([source, folder]) => {
        if (videoOnly && folder === "audio") return false;
        if (!source || source.startsWith("data:") || seen.has(source)) return false;
        seen.add(source);
        return true;
      })
      .map(([source, folder, mediaType], index) => asset(source, index, folder, mediaType));
  }

  function videoMarkdown(root, fallback = "") {
    const lines = [];
    for (const video of root.querySelectorAll("video")) {
      const direct = url(video.currentSrc || video.getAttribute("src") || video.querySelector("source")?.getAttribute("src") || "");
      const parsed = direct ? new URL(direct) : null;
      const stableDirect = direct && !direct.startsWith("blob:") && !parsed.search && !parsed.hash ? direct : "";
      const source = fallback || url(document.querySelector("link[rel='canonical']")?.getAttribute("href") || "")
        || url(location.href) || stableDirect;
      if (source) lines.push(`- Original video: [${markdownLabel(source)}](${markdownUrl(source)})`);
      for (const track of video.querySelectorAll("track[kind='subtitles'], track[kind='captions']")) {
        const href = url(track.getAttribute("src") || "");
        if (href) lines.push(`- ${markdownLabel(track.getAttribute("label") || "Subtitles")}: [subtitle file](${markdownUrl(href)})`);
      }
    }
    if (fallback && !lines.some((line) => line.startsWith("- Original video:"))) {
      lines.unshift(`- Original video: [${markdownLabel(fallback)}](${markdownUrl(fallback)})`);
    }
    const transcriptRoot = root.querySelector(transcriptSelector);
    const cueSelector = "p, [data-testid='cue'], .segment, ytd-transcript-segment-renderer";
    const transcriptParts = transcriptRoot
      ? Array.from(transcriptRoot.querySelectorAll(cueSelector))
        .filter((node) => !node.querySelector(cueSelector))
        .map((node) => markdownText(text(node))).filter(Boolean)
      : [];
    const transcript = transcriptParts.length ? transcriptParts.join("\n") : markdownText(text(transcriptRoot));
    if (!lines.length && !transcript) return "";
    return `\n\n## Video\n\n${lines.join("\n")}${transcript ? `\n\n## Transcript\n\n${transcript}` : ""}`;
  }

  function htmlSnapshot(root, title, stripAudio = false) {
    const copy = renderedClone(root);
    copy.querySelectorAll("base, script, style, noscript, template, form, input, textarea, select, button, iframe, object, embed, [aria-hidden='true'], [hidden]")
      .forEach((node) => node.remove());
    if (stripAudio) copy.querySelectorAll("audio").forEach((node) => node.remove());
    const allowed = new Set(["alt", "class", "colspan", "datetime", "height", "href", "id", "open", "poster", "rowspan", "src", "width", "xlink:href"]);
    const safeUrl = (value) => {
      try {
        const parsed = new URL(value, document.baseURI);
        return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
      } catch (_) {
        return "";
      }
    };
    for (const node of copy.querySelectorAll("*")) {
      for (const attribute of Array.from(node.attributes)) {
        if (!allowed.has(attribute.name.toLowerCase())) node.removeAttribute(attribute.name);
      }
      for (const attribute of ["href", "xlink:href"]) {
        if (!node.hasAttribute(attribute)) continue;
        const raw = node.getAttribute(attribute);
        const inSvg = node.closest("svg");
        const value = inSvg && node.tagName.toUpperCase() === "USE"
          ? (raw?.startsWith("#") ? raw : "")
          : (inSvg && !["A", "IMAGE"].includes(node.tagName.toUpperCase()) ? "" : safeUrl(raw));
        if (value) node.setAttribute(attribute, value);
        else node.removeAttribute(attribute);
      }
      if (node.hasAttribute("poster")) {
        const value = safeUrl(node.getAttribute("poster"));
        if (value) node.setAttribute("poster", value);
        else node.removeAttribute("poster");
      }
      if (node.hasAttribute("src") || node.tagName === "IMG") {
        const videoSource = node.tagName === "VIDEO" || node.closest("video");
        const value = videoSource ? "" : safeUrl(node.tagName === "IMG" ? imageUrl(node) : node.getAttribute("src"));
        if (value) node.setAttribute("src", value);
        else node.removeAttribute("src");
      }
    }
    const escape = (value) => value.replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    })[character]);
    return `<!doctype html>\n<html lang="${escape(document.documentElement.lang || "")}"><head><meta charset="utf-8"><title>${escape(title)}</title></head><body>${copy.outerHTML}</body></html>`;
  }

  function extract(scope = "page") {
    const visibleMatch = (selector) => Array.from(document.querySelectorAll(selector)).find(visibleRoot) || null;
    const wechatRoot = scope === "page" ? visibleMatch("#js_content") : null;
    const wechat = visibleRoot(wechatRoot) ? wechatRoot : null;
    const xArticle = scope === "page"
      ? Array.from(document.querySelectorAll("[data-testid='twitterArticleReadView']"))
        .find(visibleRoot) || null
      : null;
    const tweets = scope === "page" && !xArticle
      ? Array.from(document.querySelectorAll("article[data-testid='tweet']"))
        .filter(visibleRoot).map(renderedClone)
      : [];
    const firstStatus = xStatus(tweets[0]);
    const pageStatus = xStatusUrl(location.href)
      || xStatusUrl(document.querySelector("link[rel='canonical']")?.getAttribute("href") || "");
    const primaryTweet = pageStatus
      ? tweets.find((tweet) => xStatus(tweet)?.id === pageStatus.id)
      : null;
    const primaryStatus = xStatus(primaryTweet) || pageStatus || firstStatus;
    const markedThread = Boolean(primaryStatus && Array.from(document.querySelectorAll("a[href*='/thread/']"))
      .filter(visibleRoot).some((link) => {
        const href = url(link.getAttribute("href") || "");
        return href && new URL(href).pathname.toLowerCase()
          === `/${primaryStatus.handle}/thread/${primaryStatus.id}`;
      }));
    const thread = primaryStatus ? xThread(tweets, primaryStatus, markedThread) : null;
    const standaloneTweet = pageStatus && primaryTweet && !thread ? primaryTweet : null;
    const publishedMetadata = Boolean(document.querySelector("meta[property='article:published_time']"));
    const articleMetadata = publishedMetadata
      || Boolean(document.querySelector("meta[property='og:type'][content='article' i]"));
    const openGraphTitle = document.querySelector("meta[property='og:title']")?.content?.trim() || "";
    const normalizedPageTitles = [openGraphTitle || document.title]
      .map((value) => value.normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase())
      .filter(Boolean);
    const editorialSelector = "blockquote, figure, pre, table, time[datetime], [itemprop='author'], [rel='author']";
    const articleBodySelector = "[itemprop='articleBody'], [class~='body'][class~='markup']";
    const readableArticleBody = (node) => Array.from(node?.querySelectorAll(articleBodySelector) || [])
      .find((body) => visibleRoot(body) && text(body).length >= 350);
    const candidateViews = new WeakMap();
    const candidateView = (node) => {
      if (!candidateViews.has(node)) {
        const view = renderedClone(node);
        view.querySelectorAll(NOISE).forEach((noise) => noise.remove());
        candidateViews.set(node, view);
      }
      return candidateViews.get(node);
    };
    const candidateText = (node) => text(candidateView(node));
    const ownArticleView = (node) => {
      const clone = candidateView(node).cloneNode(true);
      clone.querySelectorAll("article, main, [role='main']").forEach((nested) => nested.remove());
      return clone;
    };
    const headingMatchScore = (node, heading) => {
      const candidate = text(heading).normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
      let score = 0;
      for (const expected of normalizedPageTitles) {
        if (expected === candidate) score = Math.max(score, 3);
        else if ([" | ", " — ", " – ", " - "].some((separator) =>
          expected.startsWith(`${candidate}${separator}`)
        )) score = Math.max(score, 2);
        else if ([" | ", " — ", " – ", " - "].some((separator) =>
          expected.endsWith(`${separator}${candidate}`)
        )) score = Math.max(score, 1);
      }
      if (!score) return 0;
      return score * 1000 + Math.min(candidate.length, 999);
    };
    const cardLike = (node) => {
      const schema = node?.getAttribute("itemtype") || "";
      return /(?:^|[-_\s])(card|catalog|course|plan|pricing|product|teaser|tile)(?:$|[-_\s])/i
        .test(`${node?.id || ""} ${node?.className || ""}`)
        || /schema\.org\/(?:Product|Offer|Course)(?:$|[/#])/i.test(schema);
    };
    const articleRoot = (node) => {
      if (!node || node.matches(NOISE) || node.parentElement?.closest(NOISE) || hiddenByStyle(node)) return false;
      const view = candidateView(node);
      const articleHeading = view.querySelector("h1")
        || (node.tagName === "ARTICLE" ? view.querySelector("h2") : null);
      if (!articleHeading || view.querySelectorAll("p").length < 2) return false;
      const length = text(view).length;
      const editorial = view.querySelector(editorialSelector);
      const cardNodes = Array.from(view.querySelectorAll("[id], [class], [itemtype]")).filter(cardLike);
      const cardLength = cardNodes
        .filter((item) => !cardNodes.some((other) => other !== item && other.contains(item)))
        .reduce((total, item) => total + text(item).length, 0);
      if (cardLike(node) || cardLength >= length / 2) return false;
      if (node.tagName === "ARTICLE" && view.querySelector("video") && length >= 50) return true;
      if (node.tagName === "MAIN" || node.getAttribute("role") === "main") {
        const longestParagraph = Math.max(...Array.from(view.querySelectorAll("p"), (item) => text(item).length));
        let container = view.querySelector("h1");
        while (container && container !== view.parentElement) {
          if (cardLike(container)) return false;
          container = container.parentElement;
        }
        return view.querySelectorAll("h1").length === 1
          && longestParagraph >= 120
          && length >= (articleMetadata || editorial ? 350 : 800)
          && view.querySelectorAll("article").length <= 1;
      }
      const pageMain = node.closest("main, [role='main']");
      if (!publishedMetadata && !editorial && pageMain
        && candidateView(pageMain).querySelectorAll("h1").length > view.querySelectorAll("h1").length) return false;
      if (!publishedMetadata && !editorial && view.querySelectorAll("p").length < 3) return false;
      return length >= (publishedMetadata ? 250 : 500);
    };
    const candidates = Array.from(document.querySelectorAll("article, main, [role='main']"));
    const semanticCandidates = candidates.filter(articleRoot);
    const eligibleCandidates = semanticCandidates.filter((node) => {
      const nested = semanticCandidates.filter((other) => other !== node && node.contains(other));
      if (!nested.length) return true;
      if (nested.some(readableArticleBody)) return false;
      // ponytail: retain wrapper mains only when their own body clearly dominates nested articles.
      return text(ownArticleView(node)).length >= nested.reduce((total, item) => total + candidateText(item).length, 0) * 1.5;
    });
    const readableCandidates = eligibleCandidates.filter(readableArticleBody);
    const rankedCandidates = readableCandidates.length ? readableCandidates : eligibleCandidates;
    const titleScores = new Map(rankedCandidates.map((node) => [
      node, headingMatchScore(node, candidateView(node).querySelector("h1, h2"))
    ]));
    const bestTitleScore = Math.max(0, ...titleScores.values());
    const titleMatchedArticles = rankedCandidates.filter((node) => titleScores.get(node) === bestTitleScore && bestTitleScore);
    const preferredArticles = titleMatchedArticles.length ? titleMatchedArticles : rankedCandidates;
    const specificArticles = preferredArticles.filter((node) =>
      !preferredArticles.some((other) => other !== node && node.contains(other))
    );
    const editorialSignal = (node) => Boolean(candidateView(node).querySelector(editorialSelector));
    const semanticArticle = (specificArticles.length ? specificArticles : preferredArticles)
      .sort((left, right) => Number(editorialSignal(right)) - Number(editorialSignal(left))
        || candidateText(right).length - candidateText(left).length)[0];
    const editorialBody = readableArticleBody(semanticArticle);
    const editorialSource = (() => {
      if (!editorialBody || !semanticArticle) return editorialBody;
      const article = document.createElement("article");
      const mediaWidth = (media) => {
        const image = media.tagName === "IMG" ? media : media.querySelector("img");
        return Math.max(
          media.getBoundingClientRect().width,
          image?.getBoundingClientRect().width || 0,
          Number(image?.getAttribute("width")) || 0
        );
      };
      const leadingMedia = Array.from(semanticArticle.querySelectorAll("figure, picture, img"))
        .filter((media) => !editorialBody.contains(media)
          && !media.closest(NOISE)
          && visibleRoot(media)
          && !media.parentElement?.closest("figure, picture")
          && mediaWidth(media) >= 240
          && Boolean(media.compareDocumentPosition(editorialBody) & Node.DOCUMENT_POSITION_FOLLOWING));
      leadingMedia.forEach((media) => article.append(renderedClone(media)));
      article.append(renderedClone(editorialBody));
      return article;
    })();
    const articleBody = (() => {
      if (!xArticle) return null;
      const richText = Array.from(xArticle.querySelectorAll("[data-testid='twitterArticleRichTextView']"))
        .find(visibleRoot);
      if (!richText) return xArticle;
      const article = document.createElement("article");
      const cover = Array.from(xArticle.querySelectorAll("[data-testid='tweetPhoto']")).find(visibleRoot);
      if (cover && !richText.contains(cover)) article.append(renderedClone(cover));
      article.append(renderedClone(richText));
      return article;
    })();
    const source = scope === "selection"
      ? selectedRoot()
      : wechat || articleBody || thread || standaloneTweet || editorialSource || semanticArticle
        || Array.from(document.querySelectorAll("main, [role='main']")).find(visibleRoot) || document.body;
    if (!source) throw new Error("No readable content was found on the current page.");
    const root = renderedClone(source);
    root.querySelectorAll(NOISE).forEach((node) => node.remove());
    const heading = semanticArticle
      ? candidateView(semanticArticle).querySelector("h1, h2")
      : root.querySelector("h1, h2");
    const xArticleView = xArticle ? renderedClone(xArticle) : null;
    const xArticleTitle = text(xArticleView?.querySelector("[data-testid='twitter-article-title'], h1"));
    const xOwnerSource = xArticle || primaryTweet
      || (thread ? tweets.find((tweet) => xStatus(tweet)?.id === primaryStatus?.id) : null);
    const xOwner = xAuthor(xArticleView || xOwnerSource);
    const title = (wechat ? text(visibleMatch("#activity-name")) : "")
      || (thread ? `${xOwner || primaryStatus.handle} — Thread` : "")
      || (standaloneTweet ? `${xOwner || pageStatus.handle} — X Post` : "")
      || xArticleTitle
      || (semanticArticle ? text(heading) : "")
      || document.querySelector("meta[property='og:title']")?.content
      || document.title.trim()
      || text(heading);
    const author = (wechat ? text(visibleMatch("#js_name")) : "")
      || xOwner
      || document.querySelector("meta[name='author'], meta[property='article:author']")?.content?.trim()
      || (semanticArticle ? text(candidateView(semanticArticle).querySelector("[rel='author'], .author, [itemprop='author']")) : "")
      || text(root.querySelector("[rel='author'], .author, [itemprop='author']"));
    const publishedAt = (wechat ? text(visibleMatch("#publish_time")) : "")
      || (thread || standaloneTweet ? primaryStatus?.publishedAt : "")
      || document.querySelector("meta[property='article:published_time']")?.content
      || (semanticArticle ? candidateView(semanticArticle).querySelector("time[datetime]")?.getAttribute("datetime") : "")
      || (xArticle || semanticArticle || scope === "selection"
        ? root.querySelector("time[datetime]")?.getAttribute("datetime")
        : "") || "";
    const canonical = (thread || standaloneTweet ? primaryStatus?.href : "")
      || url(document.querySelector("link[rel='canonical']")?.getAttribute("href") || "")
      || url(location.href);
    const genericPage = scope === "page" && !wechat && !xArticle && !thread && !standaloneTweet && !semanticArticle;
    const mediaRoot = genericPage ? renderedClone(document.body) : root;
    const signalRoot = genericPage ? mediaRoot.cloneNode(true) : root;
    if (genericPage) signalRoot.querySelectorAll(NOISE).forEach((node) => node.remove());
    const supportedVideoHost = /(^|\.)((youtube\.com)|(youtube-nocookie\.com)|(youtu\.be)|(bilibili\.com))$/i.test(location.hostname);
    const linkedVideo = Array.from(signalRoot.querySelectorAll("a[href]"), (link) => url(link.getAttribute("href") || ""))
      .find((href) => /https?:\/\/(?:www\.)?(?:youtube\.com|youtube-nocookie\.com|youtu\.be|bilibili\.com)\//i.test(href))
      || Array.from(signalRoot.querySelectorAll("iframe[src]"), (frame) => url(frame.getAttribute("src") || ""))
        .find((href) => /https?:\/\/(?:www\.)?(?:youtube\.com|youtube-nocookie\.com|youtu\.be|(?:player\.)?bilibili\.com)\//i.test(href));
    const transcriptPresent = Boolean(signalRoot.querySelector(transcriptSelector));
    const videoDetails = videoMarkdown(signalRoot, linkedVideo || (supportedVideoHost || transcriptPresent ? canonical : ""));
    const containsVideo = supportedVideoHost
      || Boolean(linkedVideo) || transcriptPresent || Boolean(signalRoot.querySelector("video"));
    const videoPage = supportedVideoHost || transcriptPresent;
    const articlePage = Boolean(wechat || xArticle || thread || semanticArticle);
    const videoOnlyCapture = scope === "page" && videoPage && !articlePage;
    if (containsVideo) root.querySelectorAll("audio").forEach((node) => node.remove());
    const renderedTranslation = Boolean((thread || standaloneTweet) && Array.from(root.querySelectorAll("button"))
      .some((button) => /^(显示原文|show original)$/i.test(
        (button.getAttribute("aria-label") || text(button)).trim()
      )));
    const translationNotice = renderedTranslation
      ? "> 捕获说明：X 当前显示自动翻译；以下保存的是浏览器中的可见译文。原文请通过来源链接查看。\n\n"
      : "";
    const rendered = (videoOnlyCapture ? videoDetails : `${translationNotice}${block(root).trim()}${videoDetails}`)
      .replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!title || !rendered) throw new Error("The rendered page did not contain a readable title and body.");
    const captureKind = scope === "selection"
      ? "selection"
      : thread ? "thread" : standaloneTweet ? "tweet" : articlePage ? "article" : videoPage ? "video" : "html";
    const content = captureKind === "html"
      ? `[打开保存的 HTML 快照](lbrain-asset://html-snapshot)\n\n- [原页面](${markdownUrl(canonical)})${videoDetails}`
      : rendered;
    const summary = ((thread || standaloneTweet) ? text(root.querySelector("[data-testid='tweetText']")).slice(0, 240) : "")
      || document.querySelector("meta[name='description'], meta[property='og:description']")?.content?.trim()
      || text(root).slice(0, 240);
    return {
      schema: "lbrain.capture.v1",
      title,
      summary,
      origin: canonical,
      scope,
      author,
      published_at: publishedAt,
      content_markdown: content,
      capture_kind: captureKind,
      rendered_translation: renderedTranslation,
      has_video: containsVideo,
      snapshot_html: captureKind === "html" ? htmlSnapshot(mediaRoot, title, containsVideo) : "",
      preview_characters: rendered.length,
      extraction_status: "complete",
      remote_assets: media(captureKind === "html" ? mediaRoot : root, containsVideo),
      assets: []
    };
  }

  globalThis.LBrainCapture = { extract };
})();
