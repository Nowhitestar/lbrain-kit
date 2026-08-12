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
    "[aria-hidden='true']",
    "[role='navigation']",
    "[role='banner']",
    "[role='complementary']",
    "[role='group']",
    ".advertisement",
    ".ads",
    ".recommendations",
    ".related-posts",
    ".comments"
  ].join(",");

  const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
  const url = (value) => {
    try {
      const parsed = new URL(value, document.baseURI);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
    } catch (_) {
      return "";
    }
  };
  const imageUrl = (node) => url(
    node.getAttribute("data-src")
      || node.getAttribute("data-original")
      || node.currentSrc
      || node.getAttribute("src")
      || ""
  );
  const children = (node, renderer) => Array.from(node.childNodes).map(renderer).join("");

  function inline(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = node.tagName;
    if (tag === "BR") return "\n";
    if (tag === "IMG") {
      const source = imageUrl(node);
      return source ? `![${node.getAttribute("alt") || ""}](${source})` : "";
    }
    if (tag === "AUDIO") {
      const source = url(node.getAttribute("src") || node.querySelector("source[src]")?.getAttribute("src") || "");
      return source ? `[Audio](${source})` : "";
    }
    const value = children(node, inline).replace(/\s+/g, " ");
    if (!value.trim() && tag !== "A") return "";
    if (tag === "A") {
      const href = url(node.getAttribute("href") || "");
      return href && value.trim() ? `[${value.trim()}](${href})` : value;
    }
    if (tag === "STRONG" || tag === "B") return `**${value.trim()}**`;
    if (tag === "EM" || tag === "I") return `*${value.trim()}*`;
    if (tag === "DEL" || tag === "S") return `~~${value.trim()}~~`;
    if (tag === "CODE") return `\`${value.trim()}\``;
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
      Array.from(row.querySelectorAll(":scope > th, :scope > td")).map((cell) => inline(cell).trim().replace(/\|/g, "\\|"))
    );
    if (!rows.length || !rows[0].length) return "";
    const width = Math.max(...rows.map((row) => row.length));
    const line = (row) => `| ${Array.from({ length: width }, (_, index) => row[index] || "").join(" | ")} |`;
    return `${line(rows[0])}\n${line(Array(width).fill("---"))}\n${rows.slice(1).map(line).join("\n")}\n\n`;
  }

  function block(node) {
    if (node.nodeType === Node.TEXT_NODE) return node.nodeValue || "";
    if (node.nodeType !== Node.ELEMENT_NODE) return "";
    const tag = node.tagName;
    if (/^H[1-6]$/.test(tag)) return `${"#".repeat(Number(tag[1]))} ${inline(node).trim()}\n\n`;
    if (tag === "P") return `${inline(node).trim()}\n\n`;
    if (tag === "UL" || tag === "OL") return `${list(node, tag === "OL")}\n`;
    if (tag === "BLOCKQUOTE") {
      const value = children(node, block).trim();
      return `${value.split("\n").map((line) => `> ${line}`.trimEnd()).join("\n")}\n\n`;
    }
    if (tag === "PRE") {
      const language = (node.querySelector("code")?.className || "").match(/language-([\w+-]+)/)?.[1] || "";
      return `\`\`\`${language}\n${(node.textContent || "").trim()}\n\`\`\`\n\n`;
    }
    if (tag === "TABLE") return table(node);
    if (tag === "HR") return "---\n\n";
    if (tag === "FIGURE") {
      const media = Array.from(node.children).filter((child) => child.tagName !== "FIGCAPTION").map(block).join("").trim();
      const caption = text(node.querySelector("figcaption"));
      return `${media}${caption ? `\n\n*${caption}*` : ""}\n\n`;
    }
    if (tag === "IMG") return `${inline(node)}\n\n`;
    if (["DIV", "SECTION", "ARTICLE", "MAIN", "HEADER", "BODY"].includes(tag)) return children(node, block);
    return inline(node);
  }

  function selectedRoot() {
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
    const container = document.createElement("article");
    container.append(selection.getRangeAt(0).cloneContents());
    return container;
  }

  function xStatus(tweet) {
    const link = tweet?.querySelector("a[href*='/status/']");
    if (!link) return null;
    const href = url(link.getAttribute("href") || "");
    if (!href) return null;
    const match = new URL(href).pathname.match(/^\/([^/]+)\/status\/(\d+)/);
    return match ? {
      href,
      handle: match[1].toLowerCase(),
      id: match[2],
      publishedAt: tweet.querySelector("time[datetime]")?.getAttribute("datetime") || ""
    } : null;
  }

  function xAuthor(node) {
    return text(node?.querySelector("[data-testid='User-Name'] span"));
  }

  function xThread(tweets, handle) {
    const root = document.createElement("article");
    let previous = null;
    const accepted = new Set();
    for (const tweet of tweets) {
      const status = xStatus(tweet);
      if (!status || status.handle !== handle) continue;
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
          .some((link) => text(link).replace(/^@/, "").toLowerCase() === handle
            && !link.closest("[data-testid='User-Name']")
            && !link.closest("[data-testid='tweetText']")
            && !link.closest("[data-testid='quoteTweet']")
            && tweetContent
            && Boolean(link.compareDocumentPosition(tweetContent) & Node.DOCUMENT_POSITION_FOLLOWING)
            && url(link.getAttribute("href") || "")
            && new URL(url(link.getAttribute("href") || "")).pathname.toLowerCase() === `/${handle}`);
        const chronological = !previous.publishedAt || !status.publishedAt
          || Date.parse(status.publishedAt) >= Date.parse(previous.publishedAt);
        const related = replyTarget ? accepted.has(replyTarget) : selfReply;
        if (!related || !chronological) continue;
        root.append(document.createElement("hr"));
      }
      root.append(tweet.cloneNode(true));
      previous = status;
      accepted.add(status.id);
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
      const download = link.getAttribute("download") || "";
      const extension = `${download || new URL(source || "data:,x").pathname}`.split(".").pop()?.toLowerCase();
      const declared = (link.getAttribute("type") || "").split(";", 1)[0].trim().toLowerCase();
      const mediaType = ATTACHMENTS[extension]
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

  function videoMarkdown(root) {
    const lines = [];
    for (const video of root.querySelectorAll("video")) {
      const direct = url(video.currentSrc || video.getAttribute("src") || video.querySelector("source")?.getAttribute("src") || "");
      const source = direct && !direct.startsWith("blob:")
        ? direct
        : url(document.querySelector("link[rel='canonical']")?.getAttribute("href") || "") || url(location.href);
      if (source) lines.push(`- Original video: [${source}](${source})`);
      for (const track of video.querySelectorAll("track[kind='subtitles'], track[kind='captions']")) {
        const href = url(track.getAttribute("src") || "");
        if (href) lines.push(`- ${track.getAttribute("label") || "Subtitles"}: [subtitle file](${href})`);
      }
    }
    const transcript = text(root.querySelector("[data-testid='transcript'], [itemprop='transcript'], [data-lbrain-transcript], ytd-transcript-renderer"));
    if (!lines.length && !transcript) return "";
    return `\n\n## Video\n\n${lines.join("\n")}${transcript ? `\n\n## Transcript\n\n${transcript}` : ""}`;
  }

  function htmlSnapshot(root, title) {
    const copy = root.cloneNode(true);
    copy.querySelectorAll("base, script, style, noscript, template, form, input, textarea, select, button, iframe, object, embed, [aria-hidden='true'], [hidden]")
      .forEach((node) => node.remove());
    const allowed = new Set(["alt", "class", "colspan", "datetime", "height", "href", "id", "open", "poster", "rowspan", "src", "title", "width", "xlink:href"]);
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
    const wechat = scope === "page" ? document.querySelector("#js_content") : null;
    const xArticle = scope === "page" ? document.querySelector("[data-testid='twitterArticleReadView']") : null;
    const tweets = scope === "page" && !xArticle
      ? Array.from(document.querySelectorAll("article[data-testid='tweet']"))
      : [];
    const firstStatus = xStatus(tweets[0]);
    const thread = firstStatus ? xThread(tweets, firstStatus.handle) : null;
    const publishedMetadata = Boolean(document.querySelector("meta[property='article:published_time']"));
    const articleMetadata = publishedMetadata
      || Boolean(document.querySelector("meta[property='og:type'][content='article' i]"));
    const cardLike = (node) => {
      const schema = node?.getAttribute("itemtype") || "";
      return /(?:^|[-_\s])(card|catalog|course|item|plan|pricing|product|teaser|tile)(?:$|[-_\s])/i
        .test(`${node?.id || ""} ${node?.className || ""}`)
        || /schema\.org\/(?:Product|Offer|Course)(?:$|[/#])/i.test(schema);
    };
    const articleRoot = (node) => {
      if (!node || !node.querySelector("h1") || node.querySelectorAll("p").length < 2) return false;
      const length = text(node).length;
      const editorial = node.querySelector("blockquote, figure, pre, table, time[datetime], [itemprop='author'], [rel='author']");
      if (node.querySelector("video") && length >= 50) return true;
      if (node.tagName === "MAIN" || node.getAttribute("role") === "main") {
        const longestParagraph = Math.max(...Array.from(node.querySelectorAll("p"), (item) => text(item).length));
        const cardLength = Math.max(0, ...Array.from(
          node.querySelectorAll("[id], [class], [itemtype]"),
          (item) => cardLike(item) ? text(item).length : 0
        ));
        if (cardLength >= length / 2) return false;
        let container = node.querySelector("h1");
        while (container && container !== node.parentElement) {
          if (cardLike(container)) return false;
          container = container.parentElement;
        }
        return node.querySelectorAll("h1").length === 1
          && longestParagraph >= 120
          && length >= (articleMetadata || editorial ? 350 : 800)
          && node.querySelectorAll("article").length <= 1;
      }
      if (cardLike(node)) return false;
      const pageMain = node.closest("main, [role='main']");
      if (!publishedMetadata && pageMain
        && pageMain.querySelectorAll("h1").length > node.querySelectorAll("h1").length) return false;
      if (!publishedMetadata && !editorial && node.querySelectorAll("p").length < 3) return false;
      return length >= (publishedMetadata ? 250 : 500);
    };
    const candidates = Array.from(document.querySelectorAll("article, main, [role='main']"));
    const semanticArticle = candidates.find(articleRoot);
    const source = scope === "selection"
      ? selectedRoot()
      : wechat || xArticle || thread || semanticArticle || document.querySelector("main, [role='main']") || document.body;
    if (!source) throw new Error("No readable content was found on the current page.");
    const root = source.cloneNode(true);
    root.querySelectorAll(NOISE).forEach((node) => node.remove());
    const heading = root.querySelector("h1");
    const xOwner = xAuthor(xArticle || tweets[0]);
    const title = (wechat ? text(document.querySelector("#activity-name")) : "")
      || (thread ? `${xOwner || firstStatus.handle} — Thread` : "")
      || (xArticle || semanticArticle ? text(heading) : "")
      || document.querySelector("meta[property='og:title']")?.content
      || document.title.trim()
      || text(heading);
    const author = (wechat ? text(document.querySelector("#js_name")) : "")
      || xOwner
      || document.querySelector("meta[name='author'], meta[property='article:author']")?.content?.trim()
      || text(document.querySelector("[rel='author'], .author, [itemprop='author']"));
    const publishedAt = (wechat ? text(document.querySelector("#publish_time")) : "")
      || document.querySelector("meta[property='article:published_time'], time[datetime]")?.content
      || document.querySelector("time[datetime]")?.getAttribute("datetime") || "";
    const canonical = (thread ? firstStatus?.href : "")
      || url(document.querySelector("link[rel='canonical']")?.getAttribute("href") || "")
      || url(location.href);
    const rendered = `${block(root).trim()}${videoMarkdown(root)}`
      .replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (!title || !rendered) throw new Error("The rendered page did not contain a readable title and body.");
    const videoPage = /(^|\.)((youtube\.com)|(youtu\.be)|(bilibili\.com))$/i.test(location.hostname)
      || Boolean(root.querySelector("video, ytd-transcript-renderer, [data-testid='transcript'], [itemprop='transcript']"));
    const articlePage = Boolean(wechat || xArticle || thread || semanticArticle);
    const captureKind = scope === "selection"
      ? "selection"
      : thread ? "thread" : articlePage ? "article" : videoPage ? "video" : "html";
    const content = captureKind === "html"
      ? `[打开保存的 HTML 快照](lbrain-asset://html-snapshot)\n\n- 原页面：[${canonical}](${canonical})`
      : rendered;
    const summary = document.querySelector("meta[name='description'], meta[property='og:description']")?.content?.trim()
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
      has_video: videoPage,
      snapshot_html: captureKind === "html" ? htmlSnapshot(document.body, title) : "",
      preview_characters: rendered.length,
      extraction_status: "complete",
      remote_assets: media(captureKind === "html" ? document.body : root, videoPage),
      assets: []
    };
  }

  globalThis.LBrainCapture = { extract };
})();
