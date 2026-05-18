/** Shared fetch helpers for dashboard API calls. */

export function httpErrorMessage(res, text) {
  const snippet = (text || "").slice(0, 120);
  if (res.status === 404) {
    return "API not found — restart python server.py (old process may still be on port 8080)";
  }
  return snippet ? `HTTP ${res.status}: ${snippet}` : `HTTP ${res.status}`;
}

/**
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<{ ok: boolean, data?: unknown, error?: string, status: number }>}
 */
export async function fetchJson(url, options) {
  try {
    const res = await fetch(url, options);
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      return {
        ok: false,
        error: res.ok ? "Invalid JSON response" : httpErrorMessage(res, text),
        status: res.status,
      };
    }
    if (!res.ok) {
      const msg =
        (data && typeof data === "object" && (data.error || data.message)) ||
        httpErrorMessage(res, text);
      return { ok: false, error: String(msg), status: res.status, data };
    }
    return { ok: true, data, status: res.status };
  } catch (e) {
    return { ok: false, error: String(e), status: 0 };
  }
}
