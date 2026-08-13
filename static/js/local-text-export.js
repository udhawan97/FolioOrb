/** Native/browser text saving shared by reports and CSV exports only. */
(function installLocalTextExport(root, factory) {
    if (typeof module === "object" && module.exports) {
        module.exports = { createLocalTextExport: factory };
        return;
    }
    root.createLocalTextExport = factory;
    root.LocalTextExport = factory({
        getNativeSaver: () => {
            const api = root.pywebview && root.pywebview.api;
            return api && typeof api.save_file === "function"
                ? api.save_file.bind(api)
                : null;
        },
        browserSaver: ({ filename, content, mediaType }) => {
            const blob = new Blob([content], { type: mediaType });
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement("a");
            try {
                anchor.href = url;
                anchor.download = filename;
                document.body.appendChild(anchor);
                anchor.click();
                anchor.remove();
            } finally {
                URL.revokeObjectURL(url);
            }
        },
    });
})(typeof window !== "undefined" ? window : globalThis, function createLocalTextExport({
    getNativeSaver,
    browserSaver,
}) {
    function safeFilename(value, fallback = "folioorb-export.txt") {
        const leaf = String(value || "").split(/[\\/]/).pop();
        const cleaned = (leaf || "").replace(/[\u0000-\u001f\u007f]/g, "").trim();
        return cleaned || fallback;
    }

    function responseFilename(response, fallback) {
        const disposition = response.headers.get("Content-Disposition") || "";
        const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (encoded) {
            try { return safeFilename(decodeURIComponent(encoded[1]), fallback); }
            catch (_) { /* fall back to the ordinary filename form */ }
        }
        const match = disposition.match(/filename="?([^";]+)"?/i);
        return safeFilename(match ? match[1] : fallback, fallback);
    }

    async function savePayload(filename, content, mediaType, nativeText = null) {
        const safe = safeFilename(filename);
        const nativeSaver = getNativeSaver();
        if (nativeSaver) {
            const text = nativeText === null ? String(content) : nativeText;
            const result = await nativeSaver(safe, text);
            if (result?.saved) {
                return { status: "saved", filename: safe, path: result.path || null };
            }
            if (result?.error) throw new Error(String(result.error));
            return { status: "cancelled", filename: safe, path: null };
        }
        await browserSaver({ filename: safe, content, mediaType });
        return { status: "saved", filename: safe, path: null };
    }

    function saveText(filename, text, mediaType = "text/plain;charset=utf-8") {
        return savePayload(filename, String(text), mediaType, String(text));
    }

    async function saveResponse(response, { fallbackFilename, mediaType }) {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const filename = responseFilename(response, fallbackFilename);
        const bytes = new Uint8Array(await response.arrayBuffer());
        // ignoreBOM=true means the BOM remains a U+FEFF character in the string.
        // The desktop writer then preserves an existing CSV BOM or adds exactly
        // one when absent; the browser receives the untouched bytes directly.
        const nativeText = new TextDecoder("utf-8", { ignoreBOM: true }).decode(bytes);
        return savePayload(filename, bytes, mediaType, nativeText);
    }

    return { saveText, saveResponse };
});
