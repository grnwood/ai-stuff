// proxy.js
import express from "express";
import cors from "cors";
import { Readable } from "node:stream";

// If you're on Node 18+, fetch is built-in. If on older Node, `npm i node-fetch` and:
// import fetch from "node-fetch";

const app = express();
const PORT = 4567;

const PROXY_TARGET_API = process.env.PROXY_TARGET_API ?? "https://api.openai.com"; // or your proxy target
const API_KEY = process.env.OPENAI_API_KEY; // required for OpenAI-style targets

app.use(cors());
app.use(express.json({ limit: "2mb" })); // adjust if you send large payloads

function buildHeaders(req) {
  // Forward only safe headers; always set auth+JSON
  const h = {
    "Authorization": `Bearer ${API_KEY}`,
    "Content-Type": "application/json",
  };
  // Optional: forward org / project headers if provided by client
  if (req.header("OpenAI-Organization")) {
    h["OpenAI-Organization"] = req.header("OpenAI-Organization");
  }
  if (req.header("OpenAI-Project")) {
    h["OpenAI-Project"] = req.header("OpenAI-Project");
  }
  return h;
}

async function proxyRequest(req, res, targetPath, method = "POST") {
  try {
    const url = `${PROXY_TARGET_API}${targetPath}`;
    const headers = buildHeaders(req);

    const isPost = method === "POST";
    const wantsStream = isPost && req.body && req.body.stream === true;

    const controller = new AbortController();
    req.on("close", () => controller.abort()); // stop upstream if client disconnects

    const upstream = await fetch(url, {
      method,
      headers,
      // For GET /v1/models, don't include body
      body: isPost ? JSON.stringify(req.body) : undefined,
      signal: controller.signal,
    });

    const contentType = upstream.headers.get("content-type") || "";
    const isSSE =
      wantsStream || contentType.includes("text/event-stream");

    if (isSSE && upstream.body) {
      // Pass through Server-Sent Events as a stream
      res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
      res.setHeader("Cache-Control", "no-cache, no-transform");
      res.setHeader("Connection", "keep-alive");
      // Some proxies like seeing this to start chunking immediately
      res.flushHeaders?.();

      Readable.fromWeb(upstream.body).pipe(res);
      return;
    }

    // Non-streaming JSON response
    const text = await upstream.text();
    // Try to preserve status and parse JSON if possible
    let payload;
    try { payload = JSON.parse(text); } catch { payload = text; }
    res.status(upstream.status).send(payload);
  } catch (err) {
    console.error("Proxy error:", err);
    if (!res.headersSent) {
      res
        .status(500)
        .json({ error: "Proxy error", details: err.message ?? String(err) });
    }
  }
}

// Routes -> Targets
app.get("/mods", (req, res) => proxyRequest(req, res, "/v1/models", "GET"));
app.post("/ccomp", (req, res) => proxyRequest(req, res, "/v1/chat/completions"));
app.post("/comp", (req, res) => proxyRequest(req, res, "/v1/completions"));
app.post("/emb", (req, res) => proxyRequest(req, res, "/v1/embeddings"));

// Boot
app.listen(PORT, () => {
  console.log(`Proxy server running at http://localhost:${PORT}`);
  console.log(`→ GET  /mods  ->  ${PROXY_TARGET_API}/v1/models`);
  console.log(`→ POST /ccomp ->  ${PROXY_TARGET_API}/v1/chat/completions`);
  console.log(`→ POST /comp  ->  ${PROXY_TARGET_API}/v1/completions`);
  console.log(`→ POST /emb   ->  ${PROXY_TARGET_API}/v1/embeddings`);
});

