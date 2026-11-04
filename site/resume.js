/**
 * Local-only résumé text extraction (browser).
 * Never uploads file contents. Lazy-loads PDF/DOCX parsers only when needed.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  }
  root.GitHiredResume = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const MAX_BYTES = 5 * 1024 * 1024;
  const PRIVACY_NOTICE =
    "Your résumé stays in your browser. We don't upload or store it on our servers.";

  function assertSize(file) {
    if (!file) throw new Error("No file selected");
    if (file.size > MAX_BYTES) {
      throw new Error("File exceeds 5 MB limit");
    }
  }

  function extOf(file) {
    const name = String(file.name || "").toLowerCase();
    const i = name.lastIndexOf(".");
    return i >= 0 ? name.slice(i + 1) : "";
  }

  function readAsArrayBuffer(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("Could not read file"));
      reader.readAsArrayBuffer(file);
    });
  }

  function readAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error("Could not read file"));
      reader.readAsText(file);
    });
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[data-githired-lib="${src}"]`);
      if (existing) {
        if (existing.dataset.loaded === "1") return resolve();
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", () => reject(new Error("Failed to load parser")));
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.async = true;
      s.dataset.githiredLib = src;
      s.onload = () => {
        s.dataset.loaded = "1";
        resolve();
      };
      s.onerror = () => reject(new Error("Failed to load parser library"));
      document.head.appendChild(s);
    });
  }

  async function extractTxt(file) {
    const text = await readAsText(file);
    return text.trim();
  }

  function g() {
    return typeof globalThis !== "undefined" ? globalThis : window;
  }

  async function extractDocx(file) {
    // mammoth — browser build; parses OOXML text only (no macros executed)
    await loadScript("https://unpkg.com/mammoth@1.8.0/mammoth.browser.min.js");
    const mammoth = g().mammoth;
    if (!mammoth || !mammoth.extractRawText) {
      throw new Error("DOCX parser unavailable");
    }
    const buffer = await readAsArrayBuffer(file);
    const result = await mammoth.extractRawText({ arrayBuffer: buffer });
    return String(result.value || "").trim();
  }

  async function extractPdf(file) {
    // Prefer UMD build for broader compatibility without modules
    await loadScript("https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js");
    const pdfjsLib = g().pdfjsLib;
    if (!pdfjsLib) throw new Error("PDF parser unavailable");
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    const buffer = await readAsArrayBuffer(file);
    const loadingTask = pdfjsLib.getDocument({
      data: new Uint8Array(buffer),
      disableAutoFetch: true,
      disableStream: true,
      // Do not execute JS in PDFs
      isEvalSupported: false,
    });
    const pdf = await loadingTask.promise;
    const parts = [];
    const maxPages = Math.min(pdf.numPages, 40);
    for (let i = 1; i <= maxPages; i += 1) {
      const page = await pdf.getPage(i);
      const content = await page.getTextContent();
      parts.push(content.items.map((it) => it.str || "").join(" "));
    }
    return parts.join("\n").trim();
  }

  /**
   * @returns {Promise<{text:string, source:string}>}
   */
  async function extractResumeText(file) {
    assertSize(file);
    const ext = extOf(file);
    const type = String(file.type || "").toLowerCase();
    if (ext === "txt" || type === "text/plain") {
      return { text: await extractTxt(file), source: "txt" };
    }
    if (
      ext === "docx" ||
      type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ) {
      return { text: await extractDocx(file), source: "docx" };
    }
    if (ext === "pdf" || type === "application/pdf") {
      return { text: await extractPdf(file), source: "pdf" };
    }
    if (ext === "doc") {
      throw new Error("Legacy .doc is not supported — use PDF, DOCX, or TXT");
    }
    throw new Error("Unsupported file type — use PDF, DOCX, or TXT");
  }

  return {
    MAX_BYTES,
    PRIVACY_NOTICE,
    extractResumeText,
    assertSize,
  };
});
