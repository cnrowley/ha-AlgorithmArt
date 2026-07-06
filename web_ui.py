"""AlgorithmArt Web UI — Flask blueprint.

Serves the full management interface at http://<addon-ip>:8765/ui
All actions call the same JSON API endpoints used by the HA integration,
so the UI and HA are always in sync.
"""

from __future__ import annotations

from flask import Blueprint, render_template_string

ui = Blueprint("ui", __name__)

# ── Colour options (must match fractalgen.go and goban.go) ─────────────────
FRACTAL_COLOURS = ["black", "white", "green", "blue", "red", "yellow", "orange"]
GOBAN_BG        = ["white", "black"]
GOBAN_BOARD     = ["yellow", "white"]
GOBAN_WHITE     = ["white", "green", "blue", "red"]
GOBAN_BLACK     = ["black", "red"]
GOBAN_HIGHLIGHT = ["ring", "dot", "none"]

_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AlgorithmArt</title>
<style>
  :root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #22263a;
    --border: #2e3350; --accent: #6c8ef5; --accent2: #a78bfa;
    --green: #34d399; --red: #f87171; --yellow: #fbbf24;
    --text: #e2e8f0; --muted: #64748b;
    --radius: 10px; --gap: 16px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
         font-size: 14px; min-height: 100vh; }

  /* ── Layout ── */
  header { background: var(--surface); border-bottom: 1px solid var(--border);
           padding: 14px 24px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 18px; font-weight: 700; letter-spacing: .5px; }
  header .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); }
  header .dot.ok { background: var(--green); }
  header .dot.err { background: var(--red); }
  .container { max-width: 1100px; margin: 0 auto; padding: 24px; display: grid;
               grid-template-columns: 260px 1fr; gap: var(--gap); }
  @media(max-width:700px){ .container{ grid-template-columns:1fr; } }

  /* ── Sidebar ── */
  .sidebar { display: flex; flex-direction: column; gap: var(--gap); }
  .mode-btn { display: flex; align-items: center; gap: 10px; padding: 12px 16px;
              background: var(--surface); border: 1px solid var(--border);
              border-radius: var(--radius); cursor: pointer; color: var(--text);
              font-size: 14px; font-weight: 500; transition: all .15s; width: 100%; }
  .mode-btn:hover, .mode-btn.active { border-color: var(--accent);
                                       background: var(--surface2); }
  .mode-btn .icon { font-size: 20px; width: 28px; text-align: center; }
  .mode-btn.active .label { color: var(--accent); }

  .status-card { background: var(--surface); border: 1px solid var(--border);
                 border-radius: var(--radius); padding: 16px; }
  .status-card h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
                    color: var(--muted); margin-bottom: 12px; }
  .stat { display: flex; justify-content: space-between; align-items: center;
          padding: 4px 0; border-bottom: 1px solid var(--border); }
  .stat:last-child { border: none; }
  .stat .key { color: var(--muted); font-size: 12px; }
  .stat .val { font-weight: 600; font-size: 13px; }

  /* ── Main panel ── */
  .main { display: flex; flex-direction: column; gap: var(--gap); }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 20px; }
  .card h2 { font-size: 15px; font-weight: 600; margin-bottom: 16px;
             padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .panel { display: none; flex-direction: column; gap: var(--gap); }
  .panel.active { display: flex; }

  /* ── Form elements ── */
  .row { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px,1fr)); gap: 12px; }
  .field { display: flex; flex-direction: column; gap: 6px; }
  label { font-size: 12px; color: var(--muted); font-weight: 500; }
  select, input[type=number], input[type=text] {
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 10px; color: var(--text);
    font-size: 13px; width: 100%; }
  select:focus, input:focus { outline: none; border-color: var(--accent); }

  /* ── Colour swatches ── */
  .swatch-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .swatch { width: 32px; height: 32px; border-radius: 6px; cursor: pointer;
            border: 2px solid transparent; transition: all .15s; }
  .swatch:hover { transform: scale(1.1); }
  .swatch.selected { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
  .swatch.black  { background: #111; }
  .swatch.white  { background: #f0f0f0; }
  .swatch.green  { background: #22c55e; }
  .swatch.blue   { background: #3b82f6; }
  .swatch.red    { background: #ef4444; }
  .swatch.yellow { background: #eab308; }
  .swatch.orange { background: #f97316; }

  /* ── Buttons ── */
  .btn { padding: 9px 18px; border-radius: 7px; border: none; cursor: pointer;
         font-size: 13px; font-weight: 600; transition: all .15s; }
  .btn-primary { background: var(--accent); color: #fff; }
  .btn-primary:hover { filter: brightness(1.15); }
  .btn-primary:disabled { opacity: .4; cursor: not-allowed; }
  .btn-secondary { background: var(--surface2); color: var(--text);
                   border: 1px solid var(--border); }
  .btn-secondary:hover { border-color: var(--accent); }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-danger:hover { filter: brightness(1.15); }
  .btn-row { display: flex; gap: 10px; flex-wrap: wrap; }

  /* ── Progress bar ── */
  .progress-wrap { background: var(--surface2); border-radius: 20px;
                   height: 8px; overflow: hidden; }
  .progress-bar  { height: 100%; border-radius: 20px;
                   background: linear-gradient(90deg, var(--accent), var(--accent2));
                   transition: width .4s ease; }
  .progress-label { font-size: 11px; color: var(--muted); margin-top: 4px; }

  /* ── Game table ── */
  .search-bar { width: 100%; margin-bottom: 12px; }
  .game-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .game-table th { text-align: left; color: var(--muted); font-weight: 500;
                   padding: 6px 8px; border-bottom: 1px solid var(--border);
                   position: sticky; top: 0; background: var(--surface); }
  .game-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
  .game-table tr:hover td { background: var(--surface2); }
  .game-table tr.current td { background: color-mix(in srgb, var(--accent) 15%, transparent); }
  .game-table .pick-btn { padding: 3px 10px; font-size: 11px; }
  .table-wrap { max-height: 320px; overflow-y: auto; border: 1px solid var(--border);
                border-radius: 6px; }

  /* ── Toast ── */
  #toast { position: fixed; bottom: 24px; right: 24px; background: var(--surface2);
           border: 1px solid var(--border); border-radius: var(--radius);
           padding: 12px 18px; font-size: 13px; opacity: 0; pointer-events: none;
           transition: opacity .3s; z-index: 999; }
  #toast.show { opacity: 1; }
  #toast.ok  { border-color: var(--green); }
  #toast.err { border-color: var(--red); }

  /* ── Generate banner ── */
  .gen-banner { background: var(--surface2); border: 1px solid var(--border);
                border-radius: var(--radius); padding: 16px 20px;
                display: flex; align-items: center; justify-content: space-between;
                gap: 12px; }
  .gen-banner .gen-info { font-size: 12px; color: var(--muted); }
  .gen-banner .gen-info strong { color: var(--text); display: block; font-size: 14px; }
  #gen-btn { font-size: 15px; padding: 12px 28px; min-width: 160px; }
</style>
</head>
<body>

<header>
  <div class="dot" id="health-dot"></div>
  <h1>⬡ AlgorithmArt</h1>
  <span id="health-text" style="font-size:12px;color:var(--muted)">checking…</span>
</header>

<div class="container">

  <!-- Sidebar -->
  <aside class="sidebar">
    <button class="mode-btn active" data-panel="dashboard" onclick="switchPanel('dashboard',this)">
      <span class="icon">🏠</span><span class="label">Dashboard</span>
    </button>
    <button class="mode-btn" data-panel="dla" onclick="switchPanel('dla',this)">
      <span class="icon">🌿</span><span class="label">DLA</span>
    </button>
    <button class="mode-btn" data-panel="fractal" onclick="switchPanel('fractal',this)">
      <span class="icon">∞</span><span class="label">Fractal</span>
    </button>
    <button class="mode-btn" data-panel="goban" onclick="switchPanel('goban',this)">
      <span class="icon">⬡</span><span class="label">Go / Goban</span>
    </button>

    <div class="status-card" id="status-card">
      <h3>Current State</h3>
      <div class="stat"><span class="key">Source</span><span class="val" id="s-source">—</span></div>
      <div class="stat"><span class="key">Art type</span><span class="val" id="s-arttype">—</span></div>
      <div class="stat"><span class="key">DLA frame</span><span class="val" id="s-dlaframe">—</span></div>
      <div class="stat"><span class="key">Fractal mode</span><span class="val" id="s-fracmode">—</span></div>
      <div class="stat"><span class="key">Go game</span><span class="val" id="s-gogame" style="font-size:11px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">—</span></div>
      <div class="stat"><span class="key">Move</span><span class="val" id="s-move">—</span></div>
    </div>
  </aside>

  <!-- Main content -->
  <main class="main">

    <!-- Generate banner (always visible) -->
    <div class="gen-banner">
      <div class="gen-info">
        <strong id="gen-label">Generate &amp; Display</strong>
        <span id="gen-sublabel">Press to push next image to PhotoPainter</span>
      </div>
      <button class="btn btn-primary" id="gen-btn" onclick="generate()">▶ Generate</button>
    </div>

    <!-- Dashboard -->
    <div class="panel active" id="panel-dashboard">
      <div class="card">
        <h2>Quick status</h2>
        <div id="dash-content" style="color:var(--muted);font-size:13px">Loading…</div>
      </div>
    </div>

    <!-- DLA panel -->
    <div class="panel" id="panel-dla">
      <div class="card">
        <h2>🌿 DLA — Diffusion-Limited Aggregation</h2>
        <p style="color:var(--muted);font-size:12px;margin-bottom:16px">
          Each Generate press advances one frame in a 120-frame sequence.
          The cluster grows organically from a seed particle.
        </p>
        <div style="margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <label>Sequence progress</label>
            <span id="dla-frame-label" style="font-size:12px;color:var(--muted)">frame 1 / 120</span>
          </div>
          <div class="progress-wrap"><div class="progress-bar" id="dla-progress" style="width:0%"></div></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" onclick="dlaReset()">↺ Reset sequence</button>
          <button class="btn btn-primary" onclick="setSource('generative','dla');generate()">▶ Generate DLA frame</button>
        </div>
      </div>
    </div>

    <!-- Fractal panel -->
    <div class="panel" id="panel-fractal">
      <div class="card">
        <h2>∞ Fractal — fractalgen</h2>
        <div class="row" style="margin-bottom:16px">
          <div class="field">
            <label>Mode</label>
            <select id="frac-mode" onchange="saveFractalSettings()">
              <option value="single">Single frame</option>
              <option value="zoom_sequence">Zoom sequence</option>
            </select>
          </div>
        </div>
        <div class="field" style="margin-bottom:16px">
          <label>Foreground colour</label>
          <div class="swatch-row" id="fg-swatches"></div>
          <input type="hidden" id="frac-fg" value="white">
        </div>
        <div class="field" style="margin-bottom:16px">
          <label>Background colour</label>
          <div class="swatch-row" id="bg-swatches"></div>
          <input type="hidden" id="frac-bg" value="black">
        </div>
        <div id="zoom-status" style="margin-bottom:16px;display:none">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <label>Zoom step</label>
            <span id="frac-zoom-label" style="font-size:12px;color:var(--muted)">step 0</span>
          </div>
          <div class="progress-wrap"><div class="progress-bar" id="frac-progress" style="width:5%"></div></div>
        </div>
        <div class="btn-row">
          <button class="btn btn-secondary" id="frac-reset-btn" onclick="fractalReset()" style="display:none">↺ Reset zoom</button>
          <button class="btn btn-primary" onclick="setSource('generative','fractal');generate()">▶ Generate fractal</button>
        </div>
      </div>
    </div>

    <!-- Goban panel -->
    <div class="panel" id="panel-goban">
      <div class="card">
        <h2>⬡ Go / Goban</h2>

        <!-- Current game info -->
        <div id="current-game-info" style="background:var(--surface2);border-radius:8px;padding:14px;margin-bottom:16px">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
            <div>
              <div style="font-weight:600;margin-bottom:2px" id="cg-name">No game selected</div>
              <div style="font-size:11px;color:var(--muted)" id="cg-path">—</div>
            </div>
            <span id="cg-badge" style="font-size:10px;padding:3px 8px;border-radius:20px;background:var(--accent);color:#fff">RANDOM</span>
          </div>
          <div style="margin-bottom:6px;display:flex;justify-content:space-between">
            <label>Move progress</label>
            <span id="cg-move-label" style="font-size:12px;color:var(--muted)">move — / —</span>
          </div>
          <div class="progress-wrap"><div class="progress-bar" id="cg-progress" style="width:0%"></div></div>
        </div>

        <!-- Selection mode -->
        <div class="row" style="margin-bottom:16px">
          <div class="field">
            <label>Game selection</label>
            <select id="goban-mode" onchange="setGobanMode(this.value)">
              <option value="random">Random</option>
              <option value="sequential">Sequential</option>
              <option value="manual">Manual (picked below)</option>
            </select>
          </div>
          <div class="field">
            <label>Jump to move</label>
            <input type="number" id="goban-move-input" min="0" value="1"
                   placeholder="move number">
          </div>
        </div>

        <!-- Colour / style options -->
        <details style="margin-bottom:16px">
          <summary style="cursor:pointer;font-size:12px;color:var(--muted);padding:6px 0">
            Board colours &amp; style ▾
          </summary>
          <div style="padding-top:12px;display:flex;flex-direction:column;gap:12px">
            <div class="row">
              <div class="field">
                <label>Background</label>
                <select id="goban-bg" onchange="saveGobanStyle()">
                  <option value="white">White</option>
                  <option value="black">Black</option>
                </select>
              </div>
              <div class="field">
                <label>Board colour</label>
                <select id="goban-board" onchange="saveGobanStyle()">
                  <option value="yellow">Yellow</option>
                  <option value="white">White</option>
                </select>
              </div>
              <div class="field">
                <label>White stones</label>
                <select id="goban-white" onchange="saveGobanStyle()">
                  <option value="green">Green</option>
                  <option value="white">White</option>
                  <option value="blue">Blue</option>
                  <option value="red">Red</option>
                </select>
              </div>
              <div class="field">
                <label>Black stones</label>
                <select id="goban-black" onchange="saveGobanStyle()">
                  <option value="black">Black</option>
                  <option value="red">Red</option>
                </select>
              </div>
              <div class="field">
                <label>Grid thickness</label>
                <select id="goban-grid" onchange="saveGobanStyle()">
                  <option value="1">1</option>
                  <option value="2">2</option>
                </select>
              </div>
              <div class="field">
                <label>Last-move marker</label>
                <select id="goban-highlight" onchange="saveGobanStyle()">
                  <option value="ring">Ring</option>
                  <option value="dot">Dot</option>
                  <option value="none">None</option>
                </select>
              </div>
            </div>
          </div>
        </details>

        <!-- Action buttons -->
        <div class="btn-row" style="margin-bottom:16px">
          <button class="btn btn-secondary" onclick="gobanRestart()">↺ Restart game</button>
          <button class="btn btn-secondary" onclick="gobanSkip()">⏭ Skip to next game</button>
          <button class="btn btn-secondary" onclick="gobanJumpMove()">⤳ Jump to move</button>
          <button class="btn btn-primary" onclick="setSource('generative','goban');generate()">▶ Generate frame</button>
        </div>

        <!-- Game library table -->
        <div style="margin-top:8px">
          <input class="search-bar" type="text" placeholder="🔍 Search games…" oninput="filterGames(this.value)">
          <div class="table-wrap">
            <table class="game-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Game</th>
                  <th>Folder</th>
                  <th>Size</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="game-tbody"></tbody>
            </table>
          </div>
          <div id="game-count" style="font-size:11px;color:var(--muted);margin-top:6px"></div>
        </div>
      </div>
    </div>

  </main>
</div>

<div id="toast"></div>

<script>
// ── State ───────────────────────────────────────────────────────────────────
const S = {
  source: 'generative',
  artType: 'dla',
  dlaFrame: 1,
  fracFg: 'white', fracBg: 'black', fracMode: 'single', fracZoom: 0,
  gobanMode: 'random',
  gobanGameId: null, gobanGameName: '', gobanGamePath: '',
  gobanMove: 1, gobanTotal: 0,
  gobanBg: 'white', gobanBoard: 'yellow',
  gobanWhite: 'green', gobanBlack: 'black',
  gobanGrid: 1, gobanHighlight: 'ring',
  generating: false,
  games: [],
  filteredGames: [],
  currentGameId: null,
};

// ── Toast ───────────────────────────────────────────────────────────────────
let toastTimer;
function toast(msg, type='ok') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = '', 2800);
}

// ── Panel switching ─────────────────────────────────────────────────────────
function switchPanel(name, btn) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  btn.classList.add('active');
  updateGenLabel();
}

function updateGenLabel() {
  const labels = {
    dla:     ['Generate DLA frame',    'Advance the DLA sequence one frame'],
    fractal: ['Generate fractal',      'Render fractal and push to display'],
    goban:   ['Generate Go frame',     'Advance the game one move'],
    dashboard: ['Generate & Display',  'Push next image to PhotoPainter'],
  };
  const panel = document.querySelector('.mode-btn.active')?.dataset.panel || 'dashboard';
  const [main, sub] = labels[panel] || labels.dashboard;
  document.getElementById('gen-label').textContent = main;
  document.getElementById('gen-sublabel').textContent = sub;
}

// ── Health check ─────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    const r = await fetch('/health');
    const d = await r.json();
    const dot = document.getElementById('health-dot');
    const txt = document.getElementById('health-text');
    const all = Object.values(d.generators || {}).every(Boolean);
    dot.className = 'dot ' + (all ? 'ok' : 'err');
    const gens = Object.entries(d.generators || {})
      .map(([k,v]) => k + ':' + (v ? '✓' : '✗')).join('  ');
    txt.textContent = gens;
  } catch { document.getElementById('health-dot').className = 'dot err'; }
}

// ── Status polling ───────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await fetch('/status');
    if (!r.ok) return;
    const d = await r.json();

    // DLA
    S.dlaFrame = d.dla?.next_frame || 1;
    const dlaFrac = (S.dlaFrame - 1) / 120;
    document.getElementById('dla-progress').style.width = (dlaFrac * 100) + '%';
    document.getElementById('dla-frame-label').textContent =
      'frame ' + S.dlaFrame + ' / 120';

    // Fractal
    S.fracZoom = d.fractal?.zoom_step || 0;
    document.getElementById('frac-zoom-label').textContent = 'step ' + S.fracZoom;
    document.getElementById('frac-progress').style.width =
      Math.min(S.fracZoom * 5, 95) + '%';

    // Goban
    const gs = d.goban || {};
    S.gobanMode     = gs.selection_mode || 'random';
    S.currentGameId = gs.current_game_id;
    S.gobanMove     = gs.current_move || 0;
    S.gobanTotal    = gs.total_moves || 0;
    S.gobanGameName = gs.game_name || '—';
    S.gobanGamePath = gs.game_path || '—';

    document.getElementById('goban-mode').value = S.gobanMode;
    document.getElementById('cg-name').textContent = S.gobanGameName;
    document.getElementById('cg-path').textContent = S.gobanGamePath;
    document.getElementById('cg-badge').textContent = S.gobanMode.toUpperCase();
    const pct = S.gobanTotal > 0
      ? Math.round((S.gobanMove / S.gobanTotal) * 100) : 0;
    document.getElementById('cg-progress').style.width = pct + '%';
    document.getElementById('cg-move-label').textContent =
      'move ' + S.gobanMove + ' / ' + S.gobanTotal;

    // Sidebar stats
    document.getElementById('s-source').textContent  = d.image_source || '—';
    document.getElementById('s-arttype').textContent = d.art_type || '—';
    document.getElementById('s-dlaframe').textContent = S.dlaFrame + ' / 120';
    document.getElementById('s-fracmode').textContent = S.fracMode || '—';
    document.getElementById('s-gogame').textContent  = S.gobanGameName;
    document.getElementById('s-move').textContent    =
      S.gobanMove + ' / ' + S.gobanTotal;

    // Dashboard
    document.getElementById('dash-content').innerHTML = `
      <div class="row">
        <div class="stat"><span class="key">Image source</span>
          <span class="val">${d.image_source || '—'}</span></div>
        <div class="stat"><span class="key">Art type</span>
          <span class="val">${d.art_type || '—'}</span></div>
        <div class="stat"><span class="key">DLA frame</span>
          <span class="val">${S.dlaFrame} / 120</span></div>
        <div class="stat"><span class="key">Fractal zoom</span>
          <span class="val">step ${S.fracZoom}</span></div>
        <div class="stat"><span class="key">Go game</span>
          <span class="val" style="font-size:12px">${S.gobanGameName}</span></div>
        <div class="stat"><span class="key">Go move</span>
          <span class="val">${S.gobanMove} / ${S.gobanTotal}</span></div>
      </div>`;

    // Highlight current game in table
    document.querySelectorAll('#game-tbody tr').forEach(tr => {
      tr.classList.toggle('current', parseInt(tr.dataset.id) === S.currentGameId);
    });

  } catch(e) { console.warn('status poll failed', e); }
}

// ── Generate ─────────────────────────────────────────────────────────────────
async function generate() {
  if (S.generating) return;
  S.generating = true;
  const btn = document.getElementById('gen-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Generating…';

  // Build payload from current UI state
  const panel = document.querySelector('.mode-btn.active')?.dataset.panel;
  let artType = S.artType;
  if (panel === 'dla')     artType = 'dla';
  if (panel === 'fractal') artType = 'fractal';
  if (panel === 'goban')   artType = 'goban';

  const payload = {
    image_source: 'generative',
    art_type: artType,
    // fractal options
    mb_fg: S.fracFg, mb_bg: S.fracBg,
    mb_mode: S.fracMode,
    // goban options
    goban_source: 'file',
    goban_mode: S.gobanMode,
    goban_bg: S.gobanBg, goban_board: S.gobanBoard,
    goban_white_color: S.gobanWhite, goban_black_color: S.gobanBlack,
    goban_grid_thickness: S.gobanGrid, goban_highlight: S.gobanHighlight,
  };

  try {
    const r = await fetch('/ui/generate', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (d.status === 'ok') {
      toast('✓ Image pushed to display', 'ok');
    } else {
      toast('✗ ' + (d.error || 'Unknown error'), 'err');
    }
  } catch(e) {
    toast('✗ ' + e.message, 'err');
  } finally {
    S.generating = false;
    btn.disabled = false;
    btn.textContent = '▶ Generate';
    pollStatus();
  }
}

function setSource(source, artType) {
  S.source = source;
  S.artType = artType;
}

// ── DLA ──────────────────────────────────────────────────────────────────────
async function dlaReset() {
  await fetch('/generate/dla/reset', { method: 'POST' });
  toast('DLA sequence reset to frame 1', 'ok');
  pollStatus();
}

// ── Fractal ───────────────────────────────────────────────────────────────────
function buildSwatches(containerId, hiddenId, colours, selected) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  colours.forEach(c => {
    const div = document.createElement('div');
    div.className = 'swatch ' + c + (c === selected ? ' selected' : '');
    div.title = c;
    div.onclick = () => {
      container.querySelectorAll('.swatch').forEach(s => s.classList.remove('selected'));
      div.classList.add('selected');
      document.getElementById(hiddenId).value = c;
      if (hiddenId === 'frac-fg') S.fracFg = c;
      if (hiddenId === 'frac-bg') S.fracBg = c;
    };
    container.appendChild(div);
  });
}

function saveFractalSettings() {
  S.fracMode = document.getElementById('frac-mode').value;
  const isZoom = S.fracMode === 'zoom_sequence';
  document.getElementById('zoom-status').style.display    = isZoom ? 'block' : 'none';
  document.getElementById('frac-reset-btn').style.display = isZoom ? 'inline-flex' : 'none';
}

async function fractalReset() {
  await fetch('/fractal/reset', { method: 'POST' });
  toast('Fractal zoom reset', 'ok');
  pollStatus();
}

// ── Goban ─────────────────────────────────────────────────────────────────────
async function setGobanMode(mode) {
  S.gobanMode = mode;
  await fetch('/goban/mode', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ mode }),
  });
  toast('Goban mode → ' + mode, 'ok');
  pollStatus();
}

async function gobanRestart() {
  await fetch('/goban/restart', { method: 'POST' });
  toast('Restarted from move 1', 'ok');
  pollStatus();
}

async function gobanSkip() {
  await fetch('/goban/skip', { method: 'POST' });
  toast('Skipped to next game', 'ok');
  pollStatus();
}

async function gobanJumpMove() {
  const move = parseInt(document.getElementById('goban-move-input').value) || 0;
  await fetch('/goban/move', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ move }),
  });
  toast('Jumped to move ' + move, 'ok');
  pollStatus();
}

async function pickGame(gameId) {
  await fetch('/goban/select', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ game_id: gameId }),
  });
  document.getElementById('goban-mode').value = 'manual';
  S.gobanMode = 'manual';
  toast('Game selected', 'ok');
  pollStatus();
}

function saveGobanStyle() {
  S.gobanBg        = document.getElementById('goban-bg').value;
  S.gobanBoard     = document.getElementById('goban-board').value;
  S.gobanWhite     = document.getElementById('goban-white').value;
  S.gobanBlack     = document.getElementById('goban-black').value;
  S.gobanGrid      = parseInt(document.getElementById('goban-grid').value);
  S.gobanHighlight = document.getElementById('goban-highlight').value;
}

// ── Game table ────────────────────────────────────────────────────────────────
async function loadGames() {
  try {
    const r = await fetch('/goban/games');
    S.games = await r.json();
    S.filteredGames = [...S.games];
    renderGameTable();
    document.getElementById('game-count').textContent =
      S.games.length + ' games in library';
  } catch(e) { console.warn('Failed to load games', e); }
}

function filterGames(query) {
  const q = query.toLowerCase();
  S.filteredGames = q
    ? S.games.filter(g =>
        g.filename.toLowerCase().includes(q) ||
        (g.original_path || '').toLowerCase().includes(q) ||
        (g.original_directory || '').toLowerCase().includes(q))
    : [...S.games];
  renderGameTable();
}

function renderGameTable() {
  const tbody = document.getElementById('game-tbody');
  tbody.innerHTML = '';
  S.filteredGames.slice(0, 200).forEach(g => {
    const tr = document.createElement('tr');
    tr.dataset.id = g.id;
    if (g.id === S.currentGameId) tr.classList.add('current');
    tr.innerHTML = `
      <td style="color:var(--muted)">${g.id}</td>
      <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${g.original_path || g.filename}">${g.filename}</td>
      <td style="color:var(--muted);font-size:11px;max-width:140px;overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap">${g.original_directory || '—'}</td>
      <td style="color:var(--muted);font-size:11px">${Math.round(g.size_bytes/1024)}KB</td>
      <td><button class="btn btn-secondary pick-btn" onclick="pickGame(${g.id})">▶ Play</button></td>`;
    tbody.appendChild(tr);
  });
  if (S.filteredGames.length > 200) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td colspan="5" style="color:var(--muted);text-align:center;padding:8px">
      …and ${S.filteredGames.length - 200} more — refine search to see them</td>`;
    tbody.appendChild(tr);
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────
const FRACTAL_COLOURS = {{ fractal_colours | tojson }};
buildSwatches('fg-swatches', 'frac-fg', FRACTAL_COLOURS, S.fracFg);
buildSwatches('bg-swatches', 'frac-bg', FRACTAL_COLOURS, S.fracBg);

checkHealth();
loadGames();
pollStatus();
setInterval(pollStatus, 8000);
setInterval(checkHealth, 30000);
</script>
</body>
</html>
"""


@ui.route("/ui")
@ui.route("/ui/")
def index():
    return render_template_string(
        _HTML,
        fractal_colours=FRACTAL_COLOURS,
    )


@ui.route("/ui/generate", methods=["POST"])
def ui_generate():
    """Generate an image and push it to the device.

    The Web UI JS posts here with { art_type, … }.  We call the same
    generate endpoints used by the HA integration (within the same process
    via direct HTTP to localhost) so both paths share identical behaviour
    with no circular imports or event-loop conflicts.
    """
    from flask import request as req, jsonify
    import requests as rq
    import os

    data     = req.get_json(force=True) or {}
    art_type = data.get("art_type", "dla")
    port     = int(os.environ.get("PORT", "8765"))
    base     = f"http://localhost:{port}"

    try:
        # Step 1: generate image bytes by calling the relevant endpoint
        if art_type == "dla":
            resp = rq.post(f"{base}/generate/dla",
                           json={"frame": data.get("frame", None) or "__next__"},
                           timeout=180)
        elif art_type == "fractal":
            resp = rq.post(f"{base}/generate/fractal", json={
                "fg":        data.get("mb_fg", "white"),
                "bg":        data.get("mb_bg", "black"),
                "single":    data.get("mb_mode", "single") == "single",
                "has_state": data.get("mb_mode", "single") == "zoom_sequence",
            }, timeout=180)
        elif art_type == "goban":
            resp = rq.post(f"{base}/generate/goban", json={
                "goban_source":    data.get("goban_source", "file"),
                "bg":              data.get("goban_bg", "white"),
                "board":           data.get("goban_board", "yellow"),
                "white_color":     data.get("goban_white_color", "green"),
                "black_color":     data.get("goban_black_color", "black"),
                "grid_thickness":  data.get("goban_grid_thickness", 1),
                "highlight":       data.get("goban_highlight", "ring"),
            }, timeout=180)
        else:
            return jsonify({"error": f"Unknown art_type: {art_type!r}"}), 400

        if resp.status_code != 200:
            try:    err = resp.json().get("error", f"HTTP {resp.status_code}")
            except: err = f"HTTP {resp.status_code}"
            return jsonify({"error": f"Generate failed: {err}"}), 502

        image_bytes = resp.content

        # Step 2: push the image bytes to the device
        push = rq.post(f"{base}/push",
                       data=image_bytes,
                       headers={"Content-Type": "image/bmp"},
                       timeout=60)
        if push.status_code == 200:
            return jsonify({"status": "ok"})
        try:    err = push.json().get("error", f"HTTP {push.status_code}")
        except: err = f"HTTP {push.status_code}"
        return jsonify({"error": f"Push failed: {err}"}), 502

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
