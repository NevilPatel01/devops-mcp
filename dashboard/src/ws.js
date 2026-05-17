/**
 * WebSocket singleton + simple event bus (Phase 1: live snapshots).
 */

const WS_URL =
  (typeof window !== "undefined" &&
    `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws`) ||
  "ws://127.0.0.1:8080/ws";

let socket = null;
const listeners = new Map();

function emit(type, payload) {
  const set = listeners.get(type);
  if (set) {
    set.forEach((fn) => fn(payload));
  }
  const all = listeners.get("*");
  if (all) {
    all.forEach((fn) => fn({ type, ...payload }));
  }
}

export function on(eventType, handler) {
  if (!listeners.has(eventType)) {
    listeners.set(eventType, new Set());
  }
  listeners.get(eventType).add(handler);
  return () => listeners.get(eventType)?.delete(handler);
}

export function connect() {
  if (socket?.readyState === WebSocket.OPEN) {
    return socket;
  }
  socket = new WebSocket(WS_URL);
  socket.addEventListener("open", () => emit("open", {}));
  socket.addEventListener("message", (ev) => {
    try {
      const data = JSON.parse(ev.data);
      emit(data.type || "*", data);
    } catch {
      emit("error", { message: "Invalid JSON from server" });
    }
  });
  socket.addEventListener("close", () => emit("close", {}));
  socket.addEventListener("error", () => emit("error", { message: "WebSocket error" }));
  return socket;
}

export function send(message) {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify(message));
  }
}

export function getStatus() {
  if (!socket) return "disconnected";
  return ["connecting", "open", "closing", "closed"][socket.readyState] || "unknown";
}
