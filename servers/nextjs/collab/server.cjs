// Real-time co-editing relay (Yjs). One in-memory Y.Doc per presentation, shared by
// every browser that opens it. Persistence stays with Presenton: clients keep
// auto-saving the merged deck through the normal API, so this process holds no data.
//
// ws://<host>/collab/<presentationId>  (nginx proxies /collab/ here)
// Access check: the upgrade request's cookies/Authorization are replayed against
// FastAPI GET /api/v1/ppt/presentation/<id>; only a 200 lets the socket through.
const http = require("http");
const { WebSocketServer } = require("ws");
const { setupWSConnection } = require("y-websocket/bin/utils");

const PORT = Number(process.env.COLLAB_PORT || 1234);
const HOST = process.env.COLLAB_HOST || "127.0.0.1";
const FASTAPI = (process.env.COLLAB_FASTAPI_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function presentationIdFrom(url) {
  const path = (url || "").split("?")[0].replace(/\/+$/, "");
  const id = path.split("/").pop();
  return UUID_RE.test(id || "") ? id.toLowerCase() : null;
}

function canAccess(id, req) {
  return new Promise((resolve) => {
    const headers = {};
    if (req.headers.cookie) headers.cookie = req.headers.cookie;
    if (req.headers.authorization) headers.authorization = req.headers.authorization;
    const check = http.request(
      `${FASTAPI}/api/v1/ppt/presentation/${id}`,
      { method: "GET", headers, timeout: 10000 },
      (res) => {
        res.resume();
        resolve(res.statusCode === 200);
      },
    );
    check.on("timeout", () => check.destroy());
    check.on("error", () => resolve(false));
    check.end();
  });
}

const server = http.createServer((req, res) => {
  res.writeHead(req.url === "/collab/health" ? 200 : 404, { "content-type": "text/plain" });
  res.end(req.url === "/collab/health" ? "ok" : "not found");
});
const wss = new WebSocketServer({ noServer: true, maxPayload: 32 * 1024 * 1024 });

server.on("upgrade", async (req, socket, head) => {
  const id = presentationIdFrom(req.url);
  if (!id || !(await canAccess(id, req))) {
    socket.write("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
    socket.destroy();
    return;
  }
  wss.handleUpgrade(req, socket, head, (ws) => {
    setupWSConnection(ws, req, { docName: id, gc: true });
  });
});

server.listen(PORT, HOST, () => {
  console.log(`[collab] Yjs relay listening on ${HOST}:${PORT} (auth via ${FASTAPI})`);
});
