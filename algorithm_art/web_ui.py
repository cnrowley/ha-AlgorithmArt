"""AlgorithmArt Web UI — Flask blueprint serving the management dashboard.

Structure
---------
Home page   — choose the *method* (DLA / Fractal / Go), the *update period*,
              and *frames per update*. This is the scheduler control surface.
Sub pages   — one per generator, reached via "Configure options →". Each
              sub page exposes exactly the flags that generator's executable
              accepts, plus a manual "Generate & push" action.

Everything lives in a single HTML document; navigation between the home
page and the sub pages is client-side (hash routing: #/home, #/dla,
#/fractal, #/goban) so the back button and direct links both work, without
needing extra Flask routes.
"""

from __future__ import annotations

from flask import Blueprint, render_template_string

ui = Blueprint("ui", __name__)

_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AlgorithmArt</title>
<style>
:root{
  --bg:#0f1117;--sur:#1a1d27;--sur2:#22263a;--brd:#2e3350;
  --acc:#6c8ef5;--acc2:#a78bfa;--grn:#34d399;--red:#f87171;
  --yel:#fbbf24;--txt:#e2e8f0;--mut:#64748b;
  --r:10px;--gap:16px;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:system-ui,sans-serif;font-size:14px}

/* -- Layout -- */
header{background:var(--sur);border-bottom:1px solid var(--brd);
  padding:14px 24px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:100}
header h1{font-size:18px;font-weight:700;cursor:pointer}
.dot{width:10px;height:10px;border-radius:50%;background:var(--mut);flex-shrink:0}
.dot.ok{background:var(--grn)}.dot.err{background:var(--red)}
.container{max-width:900px;margin:0 auto;padding:20px;display:flex;flex-direction:column;gap:var(--gap)}

/* -- Breadcrumb -- */
.crumb{font-size:12px;color:var(--mut)}
.crumb a{color:var(--acc);cursor:pointer;text-decoration:none;font-weight:600}
.crumb a:hover{text-decoration:underline}

/* -- Views -- */
.view{display:none;flex-direction:column;gap:var(--gap)}
.view.active{display:flex}

/* -- Home: method cards -- */
.home-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--gap)}
.method-card{background:var(--sur);border:2px solid var(--brd);border-radius:var(--r);
  padding:18px;cursor:pointer;transition:all .15s;display:flex;flex-direction:column;gap:6px}
.method-card:hover{border-color:var(--acc2)}
.method-card.sel{border-color:var(--acc);background:var(--sur2)}
.mc-top{display:flex;align-items:center;gap:10px}
.mc-icon{font-size:22px}
.mc-title{font-size:15px;font-weight:700}
.mc-sub{font-size:12px;color:var(--mut)}
.mc-stat{font-size:12px;color:var(--acc);margin-top:4px}
.mc-cfg{margin-top:8px;align-self:flex-start}
.mc-badge{margin-left:auto;font-size:10px;padding:2px 8px;border-radius:20px;
  background:var(--acc);color:#fff;opacity:0}
.method-card.sel .mc-badge{opacity:1}

/* -- Cards -- */
.card{background:var(--sur);border:1px solid var(--brd);border-radius:var(--r);padding:20px}
.card h2{font-size:15px;font-weight:600;margin-bottom:16px;
  padding-bottom:10px;border-bottom:1px solid var(--brd);display:flex;align-items:center;gap:8px}
.hint{color:var(--mut);font-size:12px;margin-bottom:16px;line-height:1.5}

/* -- Status rows -- */
.st{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--brd)}
.st:last-child{border:none}
.sk{color:var(--mut);font-size:12px}.sv{font-weight:600;font-size:12px;text-align:right;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

/* -- Scheduler -- */
.sch-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.toggle{position:relative;display:inline-flex;cursor:pointer}
.toggle input{opacity:0;width:0;height:0}
.slider{position:relative;display:inline-block;width:40px;height:22px;
  background:var(--brd);border-radius:22px;transition:.3s}
.slider:before{content:'';position:absolute;width:16px;height:16px;
  background:#fff;border-radius:50%;top:3px;left:3px;transition:.3s}
input:checked+.slider{background:var(--acc)}
input:checked+.slider:before{transform:translateX(18px)}
.countdown{font-size:20px;font-weight:700;color:var(--acc);letter-spacing:1px}
.countdown.inactive{color:var(--mut);font-size:14px}

/* -- Generate bar -- */
.gen-bar{background:var(--sur2);border:1px solid var(--brd);border-radius:var(--r);
  padding:14px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.gen-info strong{display:block;font-size:14px;margin-bottom:2px}
.gen-info span{font-size:12px;color:var(--mut)}

/* -- Forms -- */
.row{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.field{display:flex;flex-direction:column;gap:5px}
label{font-size:11px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
select,input[type=number],input[type=text]{
  background:var(--sur2);border:1px solid var(--brd);border-radius:6px;
  padding:8px 10px;color:var(--txt);font-size:13px;width:100%}
select:focus,input:focus{outline:none;border-color:var(--acc)}
.interval-row{display:flex;gap:8px}
.interval-row input[type=number]{flex:1}
.interval-row select{flex:1}

/* -- Colour swatches -- */
.swatches{display:flex;gap:6px;flex-wrap:wrap;margin-top:4px}
.sw{width:30px;height:30px;border-radius:6px;cursor:pointer;
  border:2px solid transparent;transition:all .15s;flex-shrink:0}
.sw:hover{transform:scale(1.1)}
.sw.sel{border-color:var(--acc);box-shadow:0 0 0 2px var(--acc)}
.sw.black{background:#111}.sw.white{background:#f0f0f0}.sw.green{background:#22c55e}
.sw.blue{background:#3b82f6}.sw.red{background:#ef4444}.sw.yellow{background:#eab308}
.sw.orange{background:#f97316}

/* -- Buttons -- */
.btn{padding:8px 16px;border-radius:7px;border:none;cursor:pointer;
  font-size:13px;font-weight:600;transition:all .15s;display:inline-flex;
  align-items:center;gap:6px}
.bp{background:var(--acc);color:#fff}.bp:hover{filter:brightness(1.15)}
.bp:disabled{opacity:.4;cursor:not-allowed}
.bs{background:var(--sur2);color:var(--txt);border:1px solid var(--brd)}
.bs:hover{border-color:var(--acc)}
.bd{background:var(--red);color:#fff}.bd:hover{filter:brightness(1.15)}
.btn-row{display:flex;gap:8px;flex-wrap:wrap}

/* -- Progress -- */
.prog-wrap{background:var(--sur2);border-radius:20px;height:7px;overflow:hidden;margin-top:4px}
.prog-bar{height:100%;border-radius:20px;
  background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .4s}

/* -- Game table -- */
.tsearch{width:100%;margin-bottom:10px}
.twrap{max-height:320px;overflow-y:auto;border:1px solid var(--brd);border-radius:6px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--mut);padding:6px 8px;
  border-bottom:1px solid var(--brd);position:sticky;top:0;background:var(--sur);font-size:11px}
td{padding:5px 8px;border-bottom:1px solid var(--brd)}
tr:hover td{background:var(--sur2)}
tr.curr td{background:color-mix(in srgb,var(--acc) 15%,transparent)}
.play-btn{padding:2px 9px;font-size:11px}

/* -- Toast -- */
#toast{position:fixed;bottom:20px;right:20px;background:var(--sur2);
  border:1px solid var(--brd);border-radius:var(--r);padding:10px 16px;
  font-size:13px;opacity:0;pointer-events:none;transition:opacity .3s;z-index:999}
#toast.show{opacity:1}
#toast.ok{border-color:var(--grn)}#toast.err{border-color:var(--red)}
</style>
</head>
<body>

<header>
  <div class="dot" id="hdot"></div>
  <h1 onclick="openPage('home')">AlgorithmArt</h1>
  <span id="htxt" style="font-size:12px;color:var(--mut)">checking...</span>
  <span style="flex:1"></span>
  <span id="gen-active-badge" style="font-size:11px;background:var(--sur2);
    border:1px solid var(--brd);padding:3px 10px;border-radius:20px;color:var(--acc)">-</span>
</header>

<div class="container">

<!-- ============================ HOME ============================ -->
<section class="view active" id="view-home">
  <div class="crumb">Home</div>

  <div class="home-grid">
    <div class="method-card" id="mc-dla" onclick="selectMethod('dla')">
      <div class="mc-top"><span class="mc-icon">*</span><span class="mc-title">DLA</span>
        <span class="mc-badge">ACTIVE</span></div>
      <div class="mc-sub">Diffusion-limited aggregation</div>
      <div class="mc-stat" id="mc-dla-stat">frame - / 120</div>
      <button class="btn bs mc-cfg" onclick="event.stopPropagation();openPage('dla')">Configure options &rarr;</button>
    </div>
    <div class="method-card" id="mc-fractal" onclick="selectMethod('fractal')">
      <div class="mc-top"><span class="mc-icon">&infin;</span><span class="mc-title">Fractal</span>
        <span class="mc-badge">ACTIVE</span></div>
      <div class="mc-sub">Escape-time fractal renderer</div>
      <div class="mc-stat" id="mc-fractal-stat">step -</div>
      <button class="btn bs mc-cfg" onclick="event.stopPropagation();openPage('fractal')">Configure options &rarr;</button>
    </div>
    <div class="method-card" id="mc-goban" onclick="selectMethod('goban')">
      <div class="mc-top"><span class="mc-icon">#</span><span class="mc-title">Go / Goban</span>
        <span class="mc-badge">ACTIVE</span></div>
      <div class="mc-sub">Replays SGF game records</div>
      <div class="mc-stat" id="mc-goban-stat">- / -</div>
      <button class="btn bs mc-cfg" onclick="event.stopPropagation();openPage('goban')">Configure options &rarr;</button>
    </div>
    <div class="method-card" id="mc-moire" onclick="selectMethod('moire')">
      <div class="mc-top"><span class="mc-icon">&asymp;</span><span class="mc-title">Moire</span>
        <span class="mc-badge">ACTIVE</span></div>
      <div class="mc-sub">Evolving geometric interference pattern</div>
      <div class="mc-stat" id="mc-moire-stat">iteration -</div>
      <button class="btn bs mc-cfg" onclick="event.stopPropagation();openPage('moire')">Configure options &rarr;</button>
    </div>
  </div>

  <div class="card">
    <div class="sch-header">
      <h2 style="margin:0;padding:0;border:none">Update schedule</h2>
      <label class="toggle">
        <input type="checkbox" id="sch-toggle" onchange="toggleScheduler(this.checked)">
        <span class="slider"></span>
      </label>
    </div>
    <p class="hint">Chooses how often the currently selected method (above) generates
      a new image and pushes it to the PhotoFrame.</p>
    <div class="row" style="margin-bottom:6px">
      <div class="field">
        <label>Update period</label>
        <div class="interval-row">
          <input type="number" id="sch-interval" min="10" value="300"
            placeholder="seconds" onchange="schedSave()">
          <select id="sch-preset" onchange="applyPreset(this.value)">
            <option value="">Pick...</option>
            <!-- filled by JS from /status -->
          </select>
        </div>
      </div>
      <div class="field">
        <label>Frames per update</label>
        <input type="number" id="sch-fpu" min="1" max="50" value="1" onchange="schedSave()">
      </div>
      <div class="field">
        <label>Next update</label>
        <div class="countdown inactive" id="countdown">Stopped</div>
      </div>
    </div>
    <div style="display:flex;align-items:center;gap:10px;margin-top:10px">
      <button class="btn bp" onclick="triggerNow()">Fire now</button>
      <span id="last-fire-lbl" style="font-size:11px;color:var(--mut)"></span>
    </div>
  </div>

  <div class="card">
    <h2>Live status</h2>
    <div class="st"><span class="sk">Active method</span><span class="sv" id="ss-gen">-</span></div>
    <div class="st"><span class="sk">DLA frame</span><span class="sv" id="ss-dlaframe">-</span></div>
    <div class="st"><span class="sk">Fractal zoom</span><span class="sv" id="ss-fzoom">-</span></div>
    <div class="st"><span class="sk">Moire iteration</span><span class="sv" id="ss-moireiter">-</span></div>
    <div class="st"><span class="sk">Go game</span><span class="sv" id="ss-game">-</span></div>
    <div class="st"><span class="sk">Go move</span><span class="sv" id="ss-move">-</span></div>
    <div class="st"><span class="sk">Last push</span><span class="sv" id="ss-last">-</span></div>
  </div>

  <div class="gen-bar">
    <div class="gen-info">
      <strong id="gen-label">Generate &amp; push</strong>
      <span id="gen-sub">Uses the active method's current settings</span>
    </div>
    <button class="btn bp" id="gen-btn" style="font-size:15px;padding:12px 28px"
            onclick="generateNow()">Generate</button>
  </div>
</section>

<!-- ============================ DLA ============================ -->
<section class="view" id="view-dla">
  <div class="crumb"><a onclick="openPage('home')">&larr; Home</a> / DLA</div>
  <div class="card">
    <h2>DLA - Diffusion-Limited Aggregation</h2>
    <p class="hint">
      Particles random-walk until they stick to the growing cluster.
      <code>dla.x</code> takes no tunable parameters, just a working directory
      and a frame number: <code>dla out --init</code> seeds frame 1, then
      <code>dla out --to N</code> renders each subsequent frame into
      <code>out/current.bmp</code>, reusing the same directory so the
      cluster keeps growing. The directory is wiped automatically once the
      120-frame sequence finishes, so the next cycle starts from a fresh seed.
    </p>
    <div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <label>Sequence progress</label>
        <span id="dla-frame-lbl" style="font-size:12px;color:var(--mut)">frame 1 / 120</span>
      </div>
      <div class="prog-wrap"><div class="prog-bar" id="dla-prog" style="width:0%"></div></div>
    </div>
    <div class="btn-row">
      <button class="btn bs" onclick="dlaReset()">Reset sequence</button>
      <button class="btn bp" onclick="generateNow('dla')">Generate DLA frame</button>
    </div>
  </div>
</section>

<!-- ============================ FRACTAL ============================ -->
<section class="view" id="view-fractal">
  <div class="crumb"><a onclick="openPage('home')">&larr; Home</a> / Fractal</div>
  <div class="card">
    <h2>Fractal</h2>
    <p class="hint">Options passed straight through to <code>fractal.x</code>
      (<code>-fg</code>, <code>-bg</code>, <code>-single</code> /
      <code>-frames</code>, <code>-state</code>).</p>
    <div class="row" style="margin-bottom:16px">
      <div class="field">
        <label>Mode</label>
        <select id="frac-mode" onchange="fracSave()">
          <option value="single">Single frame (-single)</option>
          <option value="zoom_sequence">Zoom sequence (-state, advances each call)</option>
        </select>
      </div>
    </div>
    <div class="field" style="margin-bottom:14px">
      <label>Foreground colour (-fg)</label>
      <div class="swatches" id="fg-sw"></div>
      <input type="hidden" id="frac-fg" value="white">
    </div>
    <div class="field" style="margin-bottom:14px">
      <label>Background colour (-bg)</label>
      <div class="swatches" id="bg-sw"></div>
      <input type="hidden" id="frac-bg" value="black">
    </div>
    <div id="zoom-info" style="margin-bottom:14px;display:none">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <label>Zoom step</label>
        <span id="frac-zoom-lbl" style="font-size:12px;color:var(--mut)">step 0</span>
      </div>
      <div class="prog-wrap"><div class="prog-bar" id="frac-prog" style="width:5%"></div></div>
    </div>
    <div class="btn-row">
      <button class="btn bs" id="frac-reset-btn" onclick="fractalReset()" style="display:none">Reset zoom (-state)</button>
      <button class="btn bp" onclick="generateNow('fractal')">Generate fractal</button>
    </div>
  </div>
</section>

<!-- ============================ GOBAN ============================ -->
<section class="view" id="view-goban">
  <div class="crumb"><a onclick="openPage('home')">&larr; Home</a> / Go / Goban</div>
  <div class="card">
    <h2>Go / Goban</h2>

    <!-- Current game -->
    <div style="background:var(--sur2);border-radius:8px;padding:14px;margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
        <div>
          <div style="font-weight:600;margin-bottom:2px" id="cg-name">No game selected</div>
          <div style="font-size:11px;color:var(--mut)" id="cg-path">-</div>
        </div>
        <span id="cg-badge" style="font-size:10px;padding:3px 8px;border-radius:20px;
          background:var(--acc);color:#fff">RANDOM</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <label>Progress (-move)</label>
        <span id="cg-move-lbl" style="font-size:12px;color:var(--mut)">- / -</span>
      </div>
      <div class="prog-wrap"><div class="prog-bar" id="cg-prog" style="width:0%"></div></div>
    </div>

    <!-- Controls -->
    <div class="row" style="margin-bottom:14px">
      <div class="field">
        <label>Game selection</label>
        <select id="goban-mode" onchange="setGobanMode(this.value)">
          <option value="random">Random</option>
          <option value="sequential">Sequential</option>
          <option value="manual">Manual (pick below)</option>
        </select>
      </div>
      <div class="field">
        <label>Jump to move (-move, 0=final)</label>
        <input type="number" id="goban-move-inp" min="0" value="1">
      </div>
    </div>

    <!-- Board style -->
    <details style="margin-bottom:14px" open>
      <summary style="cursor:pointer;font-size:12px;color:var(--mut);padding:6px 0">
        Board colours &amp; style
      </summary>
      <div style="padding-top:12px">
        <div class="row">
          <div class="field">
            <label>Background (-bg)</label>
            <select id="goban-bg" onchange="gobanStyleSave()">
              <option value="white">White</option><option value="black">Black</option>
            </select>
          </div>
          <div class="field">
            <label>Board colour (-board)</label>
            <select id="goban-board" onchange="gobanStyleSave()">
              <option value="yellow">Yellow</option><option value="white">White</option>
            </select>
          </div>
          <div class="field">
            <label>White stones (-white-color)</label>
            <select id="goban-white" onchange="gobanStyleSave()">
              <option value="green">Green</option><option value="white">White</option>
              <option value="blue">Blue</option><option value="red">Red</option>
            </select>
          </div>
          <div class="field">
            <label>Black stones (-black-color)</label>
            <select id="goban-black" onchange="gobanStyleSave()">
              <option value="black">Black</option><option value="red">Red</option>
            </select>
          </div>
          <div class="field">
            <label>Grid thickness (-grid-thickness)</label>
            <select id="goban-grid" onchange="gobanStyleSave()">
              <option value="1">1</option><option value="2">2</option>
            </select>
          </div>
          <div class="field">
            <label>Last-move marker (-highlight)</label>
            <select id="goban-highlight" onchange="gobanStyleSave()">
              <option value="ring">Ring</option><option value="dot">Dot</option>
              <option value="none">None</option>
            </select>
          </div>
        </div>
      </div>
    </details>

    <div class="btn-row" style="margin-bottom:16px">
      <button class="btn bs" onclick="gobanRestart()">Restart game</button>
      <button class="btn bs" onclick="gobanSkip()">Skip game</button>
      <button class="btn bs" onclick="gobanJumpMove()">Jump to move</button>
      <button class="btn bp" onclick="generateNow('goban')">Generate frame</button>
    </div>

    <!-- Game library -->
    <input class="tsearch" type="text" placeholder="Search games..."
      oninput="filterGames(this.value)">
    <div class="twrap">
      <table>
        <thead><tr>
          <th>#</th><th>Filename</th><th>Collection</th><th>Size</th><th></th>
        </tr></thead>
        <tbody id="gtbody"></tbody>
      </table>
    </div>
    <div id="gcnt" style="font-size:11px;color:var(--mut);margin-top:6px"></div>
  </div>
</section>

<!-- ============================ MOIRE ============================ -->
<section class="view" id="view-moire">
  <div class="crumb"><a onclick="openPage('home')">&larr; Home</a> / Moire</div>
  <div class="card">
    <h2>Moire</h2>
    <p class="hint">Options passed straight through to <code>moire</code>
      (<code>-pattern</code>, <code>-background</code>, <code>-linecolor</code>).
      Always invoked as <code>-animate -iteration N</code>; rotation, translation,
      and scale are derived by the binary itself from the iteration number, which
      Home Assistant advances by one on every generate.</p>
    <div class="row" style="margin-bottom:16px">
      <div class="field">
        <label>Pattern (-pattern)</label>
        <select id="moire-pattern" onchange="moireSave()">
          <option value="honeycomb">Honeycomb</option>
          <option value="hexdots">Hex dots</option>
          <option value="lines">Lines</option>
          <option value="square">Square</option>
          <option value="triangular">Triangular</option>
          <option value="kagome">Kagome</option>
          <option value="circles">Circles</option>
          <option value="spokes">Spokes</option>
          <option value="checkerboard">Checkerboard</option>
        </select>
      </div>
    </div>
    <div class="field" style="margin-bottom:14px">
      <label>Background colour (-background)</label>
      <div class="swatches" id="moire-bg-sw"></div>
      <input type="hidden" id="moire-background" value="white">
    </div>
    <div class="field" style="margin-bottom:14px">
      <label>Line colour (-linecolor)</label>
      <div class="swatches" id="moire-line-sw"></div>
      <input type="hidden" id="moire-linecolor" value="black">
    </div>
    <div style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center">
      <label style="margin:0">Next iteration</label>
      <span id="moire-iter-lbl" style="font-size:12px;color:var(--mut)">0</span>
    </div>
    <div class="btn-row">
      <button class="btn bs" onclick="moireReset()">Reset sequence</button>
      <button class="btn bp" onclick="generateNow('moire')">Generate moire frame</button>
    </div>
  </div>
</section>

</div>

<div id="toast"></div>

<script>
// -- State --
const COLOURS = ['black','white','green','blue','red','yellow','orange'];
const MOIRE_COLOURS = ['white','black','red','green','blue','yellow'];
const PAGES = ['home','dla','fractal','goban','moire'];
const S = {
  activeTab:   'dla',      // the currently selected *method* (scheduler target)
  fracFg:      'white',
  fracBg:      'black',
  fracMode:    'single',
  fracZoom:    0,
  gobanMode:   'random',
  gobanBg:     'white',
  gobanBoard:  'yellow',
  gobanWhite:  'green',
  gobanBlack:  'black',
  gobanGrid:   1,
  gobanHighlight: 'ring',
  moirePattern: 'honeycomb',
  moireBg:      'white',
  moireLine:    'black',
  moireIter:    0,
  games:       [],
  filtered:    [],
  currentId:   null,
  schEnabled:  false,
  schInterval: 300,
  nextFireTs:  null,
  lastFireTs:  null,
};
let countdownTimer = null;

// -- Toast --
let tTimer;
function toast(msg, type='ok'){
  const el=document.getElementById('toast');
  el.textContent=msg; el.className='show '+type;
  clearTimeout(tTimer); tTimer=setTimeout(()=>el.className='',2800);
}

// -- Page navigation (hash routing: #/home #/dla #/fractal #/goban) --
function openPage(name){
  if(!PAGES.includes(name)) name='home';
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.getElementById('view-'+name).classList.add('active');
  if(location.hash!=='#/'+name) location.hash='#/'+name;
  window.scrollTo(0,0);
}
window.addEventListener('hashchange', ()=>{
  const name=(location.hash||'#/home').replace('#/','');
  openPage(name);
});

// -- Method selection (home page cards) --
function selectMethod(name){
  S.activeTab=name;
  document.querySelectorAll('.method-card').forEach(c=>c.classList.remove('sel'));
  document.getElementById('mc-'+name).classList.add('sel');
  updateGenBar();
  schedSave();   // persist active_generator
}

function updateGenBar(){
  const labels={
    dla:    ['Generate DLA frame',    'Advances the DLA sequence one frame'],
    fractal:['Generate fractal',      'Renders fractal with current settings'],
    goban:  ['Generate Go frame',     'Advances the game one move'],
    moire:  ['Generate moire frame',  'Advances the moire iteration by one'],
  };
  const [main,sub]=labels[S.activeTab]||['Generate',''];
  const lbl=document.getElementById('gen-label');
  const sb=document.getElementById('gen-sub');
  if(lbl) lbl.textContent=main;
  if(sb) sb.textContent=sub;
  document.getElementById('gen-active-badge').textContent=
    S.activeTab.charAt(0).toUpperCase()+S.activeTab.slice(1);
}

// -- Health check --
async function checkHealth(){
  try{
    const d=await(await fetch('/health')).json();
    const ok=Object.values(d.generators||{}).every(Boolean);
    document.getElementById('hdot').className='dot '+(ok?'ok':'err');
    document.getElementById('htxt').textContent=
      Object.entries(d.generators||{}).map(([k,v])=>k+':'+(v?'OK':'X')).join('  ');
  }catch{document.getElementById('hdot').className='dot err';}
}

// -- Countdown timer --
function startCountdown(){
  clearInterval(countdownTimer);
  const el=document.getElementById('countdown');
  const tick=()=>{
    if(!S.schEnabled||!S.nextFireTs){
      el.textContent='Stopped'; el.className='countdown inactive'; return;
    }
    const secs=Math.max(0,Math.round((new Date(S.nextFireTs)-Date.now())/1000));
    const m=Math.floor(secs/60), s=secs%60;
    el.textContent=(m?m+'m ':'')+s+'s';
    el.className='countdown';
  };
  tick();
  countdownTimer=setInterval(tick,1000);
}

// -- Status polling --
async function poll(){
  try{
    const d=await(await fetch('/status')).json();

    // DLA
    const dlaf=d.dla?.next_frame||1;
    document.getElementById('dla-prog').style.width=((dlaf-1)/120*100)+'%';
    document.getElementById('dla-frame-lbl').textContent=`frame ${dlaf} / 120`;
    document.getElementById('mc-dla-stat').textContent=`frame ${dlaf} / 120`;

    // Fractal
    const fz=d.fractal?.zoom_step||0;
    S.fracZoom=fz;
    document.getElementById('frac-zoom-lbl').textContent='step '+fz;
    document.getElementById('frac-prog').style.width=Math.min(fz*5,95)+'%';
    document.getElementById('mc-fractal-stat').textContent='step '+fz;

    // Moire
    const mi=d.moire?.iteration||0;
    S.moireIter=mi;
    document.getElementById('mc-moire-stat').textContent='iteration '+mi;
    document.getElementById('moire-iter-lbl').textContent=mi;

    // Goban
    const gs=d.goban||{};
    S.currentId=gs.current_game_id;
    document.getElementById('goban-mode').value=gs.selection_mode||'random';
    document.getElementById('cg-name').textContent=gs.game_name||'No game selected';
    document.getElementById('cg-path').textContent=gs.game_path||'-';
    document.getElementById('cg-badge').textContent=(gs.selection_mode||'random').toUpperCase();
    const pct=gs.total_moves>0?Math.round(gs.current_move/gs.total_moves*100):0;
    document.getElementById('cg-prog').style.width=pct+'%';
    document.getElementById('cg-move-lbl').textContent=
      `move ${gs.current_move||0} / ${gs.total_moves||0}`;
    document.getElementById('mc-goban-stat').textContent=
      `move ${gs.current_move||0} / ${gs.total_moves||0}`;
    // Highlight current game in table
    document.querySelectorAll('#gtbody tr').forEach(tr=>
      tr.classList.toggle('curr',parseInt(tr.dataset.id)===S.currentId));

    // Scheduler
    const sch=d.scheduler||{};
    S.schEnabled=sch.enabled||false;
    S.schInterval=sch.interval_seconds||300;
    S.nextFireTs=sch.next_fire||null;
    S.lastFireTs=sch.last_fire||null;
    S.activeTab=sch.active_generator||S.activeTab;
    document.getElementById('sch-toggle').checked=S.schEnabled;
    document.getElementById('sch-interval').value=S.schInterval;
    document.getElementById('sch-fpu').value=sch.frames_per_update||1;
    document.getElementById('last-fire-lbl').textContent=
      S.lastFireTs ? 'Last: '+new Date(S.lastFireTs).toLocaleTimeString() : '';

    document.querySelectorAll('.method-card').forEach(c=>c.classList.remove('sel'));
    const mc=document.getElementById('mc-'+S.activeTab);
    if(mc) mc.classList.add('sel');
    updateGenBar();

    // Restore fractal/goban settings
    setSwatchSel('fg-sw','frac-fg', sch.fractal_fg||'white');
    setSwatchSel('bg-sw','frac-bg', sch.fractal_bg||'black');
    document.getElementById('frac-mode').value=sch.fractal_mode||'single';
    updateFracVisibility();
    document.getElementById('goban-bg').value=sch.goban_bg||'white';
    document.getElementById('goban-board').value=sch.goban_board||'yellow';
    document.getElementById('goban-white').value=sch.goban_white_color||'green';
    document.getElementById('goban-black').value=sch.goban_black_color||'black';
    document.getElementById('goban-grid').value=sch.goban_grid_thickness||1;
    document.getElementById('goban-highlight').value=sch.goban_highlight||'ring';
    document.getElementById('moire-pattern').value=sch.moire_pattern||'honeycomb';
    setSwatchSel('moire-bg-sw','moire-background', sch.moire_background||'white');
    setSwatchSel('moire-line-sw','moire-linecolor', sch.moire_linecolor||'black');

    // Interval presets dropdown
    const sel=document.getElementById('sch-preset');
    if(sel.options.length<=1 && d.interval_presets){
      d.interval_presets.forEach(p=>{
        const o=document.createElement('option');
        o.value=p.seconds; o.textContent=p.label;
        sel.appendChild(o);
      });
    }

    // Live status card
    document.getElementById('ss-gen').textContent=S.activeTab||'-';
    document.getElementById('ss-dlaframe').textContent=`${dlaf} / 120`;
    document.getElementById('ss-fzoom').textContent='step '+fz;
    document.getElementById('ss-moireiter').textContent=mi;
    document.getElementById('ss-game').textContent=gs.game_name||'-';
    document.getElementById('ss-move').textContent=
      `${gs.current_move||0} / ${gs.total_moves||0}`;
    document.getElementById('ss-last').textContent=
      S.lastFireTs?new Date(S.lastFireTs).toLocaleTimeString():'-';

    startCountdown();

  }catch(e){console.warn('poll error',e);}
}

// -- Generate --
async function generateNow(methodOverride){
  const method = methodOverride || S.activeTab;
  const btn = (event && event.currentTarget) ? event.currentTarget
              : document.getElementById('gen-btn');
  const prevText = btn.textContent;
  btn.disabled=true; btn.textContent='...';

  const payload={art_type:method};
  if(method==='fractal'){
    payload.fractal_fg=document.getElementById('frac-fg').value;
    payload.fractal_bg=document.getElementById('frac-bg').value;
    payload.fractal_mode=document.getElementById('frac-mode').value;
  } else if(method==='goban'){
    payload.goban_source='file';
    payload.goban_bg=document.getElementById('goban-bg').value;
    payload.goban_board=document.getElementById('goban-board').value;
    payload.goban_white_color=document.getElementById('goban-white').value;
    payload.goban_black_color=document.getElementById('goban-black').value;
    payload.goban_grid_thickness=parseInt(document.getElementById('goban-grid').value)||1;
    payload.goban_highlight=document.getElementById('goban-highlight').value;
  } else if(method==='moire'){
    payload.moire_pattern=document.getElementById('moire-pattern').value;
    payload.moire_background=document.getElementById('moire-background').value;
    payload.moire_linecolor=document.getElementById('moire-linecolor').value;
  }

  try{
    const r=await fetch('/ui/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.status==='ok') toast('Pushed to display','ok');
    else toast('Error: '+(d.error||'Failed'),'err');
  }catch(e){toast('Error: '+e.message,'err');}
  finally{
    btn.disabled=false; btn.textContent=prevText;
    poll();
  }
}

// -- DLA --
async function dlaReset(){
  await fetch('/generate/dla/reset',{method:'POST'});
  toast('DLA sequence reset','ok'); poll();
}

// -- Fractal / Moire --
function buildSwatches(cid, hid, selected, palette){
  const c=document.getElementById(cid);
  c.innerHTML='';
  (palette||COLOURS).forEach(col=>{
    const d=document.createElement('div');
    d.className='sw '+col+(col===selected?' sel':'');
    d.title=col;
    d.onclick=()=>{
      c.querySelectorAll('.sw').forEach(s=>s.classList.remove('sel'));
      d.classList.add('sel');
      document.getElementById(hid).value=col;
      if(hid==='frac-fg') S.fracFg=col;
      if(hid==='frac-bg') S.fracBg=col;
      if(hid==='moire-background'){ S.moireBg=col; moireSave(); return; }
      if(hid==='moire-linecolor'){ S.moireLine=col; moireSave(); return; }
      schedSave();
    };
    c.appendChild(d);
  });
}

function setSwatchSel(cid, hid, val){
  document.getElementById(hid).value=val;
  document.querySelectorAll(`#${cid} .sw`).forEach(s=>{
    s.classList.toggle('sel', s.title===val);
  });
}

function updateFracVisibility(){
  const isZoom=document.getElementById('frac-mode').value==='zoom_sequence';
  document.getElementById('zoom-info').style.display=isZoom?'block':'none';
  document.getElementById('frac-reset-btn').style.display=isZoom?'':'none';
}

function fracSave(){
  updateFracVisibility();
  schedSave();
}

async function fractalReset(){
  await fetch('/fractal/reset',{method:'POST'});
  toast('Fractal zoom reset','ok'); poll();
}

// -- Goban --
async function setGobanMode(mode){
  await fetch('/goban/mode',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
  toast('Goban mode -> '+mode,'ok'); schedSave(); poll();
}
async function gobanRestart(){
  await fetch('/goban/restart',{method:'POST'});
  toast('Restarted from move 1','ok'); poll();
}
async function gobanSkip(){
  await fetch('/goban/skip',{method:'POST'});
  toast('Skipped to next game','ok'); poll();
}
async function gobanJumpMove(){
  const move=parseInt(document.getElementById('goban-move-inp').value)||0;
  await fetch('/goban/move',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({move})});
  toast('Jumped to move '+move,'ok'); poll();
}
async function pickGame(id){
  await fetch('/goban/select',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({game_id:id})});
  document.getElementById('goban-mode').value='manual';
  toast('Game selected','ok'); schedSave(); poll();
}
function gobanStyleSave(){ schedSave(); }

// -- Moire --
function moireSave(){
  S.moirePattern=document.getElementById('moire-pattern').value;
  schedSave();
}
async function moireReset(){
  await fetch('/generate/moire/reset',{method:'POST'});
  S.moireIter=0;
  document.getElementById('moire-iter-lbl').textContent='0';
  toast('Moire sequence reset','ok'); poll();
}

// -- Scheduler --
function applyPreset(v){
  if(!v) return;
  document.getElementById('sch-interval').value=v;
  schedSave();
}

async function toggleScheduler(enabled){
  await schedSave({enabled});
  toast(enabled?'Scheduler started':'Scheduler stopped', enabled?'ok':'ok');
}

async function triggerNow(){
  await fetch('/scheduler/trigger',{method:'POST'});
  toast('Fired!','ok'); setTimeout(poll,500);
}

async function schedSave(extra={}){
  const payload={
    active_generator:   S.activeTab,
    interval_seconds:   parseInt(document.getElementById('sch-interval').value)||300,
    frames_per_update:  parseInt(document.getElementById('sch-fpu').value)||1,
    fractal_fg:         document.getElementById('frac-fg').value,
    fractal_bg:         document.getElementById('frac-bg').value,
    fractal_mode:       document.getElementById('frac-mode').value,
    goban_bg:           document.getElementById('goban-bg').value,
    goban_board:        document.getElementById('goban-board').value,
    goban_white_color:  document.getElementById('goban-white').value,
    goban_black_color:  document.getElementById('goban-black').value,
    goban_grid_thickness: parseInt(document.getElementById('goban-grid').value)||1,
    goban_highlight:    document.getElementById('goban-highlight').value,
    goban_mode:         document.getElementById('goban-mode').value,
    moire_pattern:      document.getElementById('moire-pattern').value,
    moire_background:   document.getElementById('moire-background').value,
    moire_linecolor:    document.getElementById('moire-linecolor').value,
    ...extra,
  };
  const r=await fetch('/scheduler/settings',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const d=await r.json();
  if(d.state){
    S.schEnabled=d.state.enabled;
    S.schInterval=d.state.interval_seconds;
    document.getElementById('sch-toggle').checked=S.schEnabled;
    startCountdown();
  }
}

// -- Game table --
async function loadGames(){
  try{
    const r=await fetch('/goban/games');
    S.games=await r.json();
    S.filtered=[...S.games];
    renderGames();
    document.getElementById('gcnt').textContent=S.games.length+' games in library';
  }catch(e){console.warn('games load failed',e);}
}

function filterGames(q){
  q=q.toLowerCase();
  S.filtered=q?S.games.filter(g=>
    (g.filename||'').toLowerCase().includes(q)||
    (g.original_path||'').toLowerCase().includes(q)||
    (g.original_directory||'').toLowerCase().includes(q)
  ):[...S.games];
  renderGames();
}

function renderGames(){
  const tb=document.getElementById('gtbody');
  tb.innerHTML='';
  S.filtered.slice(0,200).forEach(g=>{
    const tr=document.createElement('tr');
    tr.dataset.id=g.id;
    if(g.id===S.currentId) tr.classList.add('curr');
    tr.innerHTML=`
      <td style="color:var(--mut)">${g.id}</td>
      <td title="${g.original_path||g.filename}"
          style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        ${g.filename}</td>
      <td style="color:var(--mut);font-size:11px;max-width:130px;overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap">${g.original_directory||'-'}</td>
      <td style="color:var(--mut);font-size:11px">${Math.round(g.size_bytes/1024)}KB</td>
      <td><button class="btn bs play-btn" onclick="pickGame(${g.id})">Play</button></td>`;
    tb.appendChild(tr);
  });
  if(S.filtered.length>200){
    const tr=document.createElement('tr');
    tr.innerHTML=`<td colspan="5" style="color:var(--mut);text-align:center;padding:8px">
      ...${S.filtered.length-200} more - refine search</td>`;
    tb.appendChild(tr);
  }
}

// -- Init --
buildSwatches('fg-sw','frac-fg', S.fracFg);
buildSwatches('bg-sw','frac-bg', S.fracBg);
buildSwatches('moire-bg-sw','moire-background', S.moireBg, MOIRE_COLOURS);
buildSwatches('moire-line-sw','moire-linecolor', S.moireLine, MOIRE_COLOURS);
openPage((location.hash||'#/home').replace('#/',''));
updateGenBar();
checkHealth();
loadGames();
poll();
setInterval(poll,5000);
setInterval(checkHealth,30000);
</script>
</body>
</html>
"""


@ui.route("/ui")
@ui.route("/ui/")
def index():
    return render_template_string(_HTML)


@ui.route("/ui/generate", methods=["POST"])
def ui_generate():
    """Generate an image and push it to the device from the Web UI."""
    from flask import request as req, jsonify
    import requests as rq
    import os

    data     = req.get_json(force=True) or {}
    art_type = data.get("art_type", "dla")
    port     = int(os.environ.get("PORT", "8765"))
    base     = f"http://localhost:{port}"

    try:
        if art_type == "dla":
            gen_resp = rq.post(f"{base}/generate/dla", json={}, timeout=180)
        elif art_type == "fractal":
            gen_resp = rq.post(f"{base}/generate/fractal", json={
                "fg":        data.get("fractal_fg", "white"),
                "bg":        data.get("fractal_bg", "black"),
                "single":    data.get("fractal_mode", "single") == "single",
                "has_state": data.get("fractal_mode", "single") == "zoom_sequence",
            }, timeout=180)
        elif art_type == "goban":
            gen_resp = rq.post(f"{base}/generate/goban", json={
                "goban_source":   data.get("goban_source", "file"),
                "bg":             data.get("goban_bg",           "white"),
                "board":          data.get("goban_board",         "yellow"),
                "white_color":    data.get("goban_white_color",   "green"),
                "black_color":    data.get("goban_black_color",   "black"),
                "grid_thickness": data.get("goban_grid_thickness", 1),
                "highlight":      data.get("goban_highlight",     "ring"),
            }, timeout=180)
        elif art_type == "moire":
            gen_resp = rq.post(f"{base}/generate/moire", json={
                "pattern":    data.get("moire_pattern",    "honeycomb"),
                "background": data.get("moire_background", "white"),
                "linecolor":  data.get("moire_linecolor",  "black"),
                # No explicit "iteration" — let the sidecar auto-advance its
                # own counter by one, same as a manual DLA generate does.
            }, timeout=180)
        else:
            return jsonify({"error": f"Unknown art_type: {art_type!r}"}), 400

        if gen_resp.status_code != 200:
            try:    err = gen_resp.json().get("error", f"HTTP {gen_resp.status_code}")
            except: err = f"HTTP {gen_resp.status_code}"
            return jsonify({"error": f"Generate failed: {err}"}), 502

        push_resp = rq.post(f"{base}/push",
                            data=gen_resp.content,
                            headers={"Content-Type": "image/bmp"},
                            timeout=60)
        if push_resp.status_code == 200:
            return jsonify({"status": "ok"})
        try:    err = push_resp.json().get("error", f"HTTP {push_resp.status_code}")
        except: err = f"HTTP {push_resp.status_code}"
        return jsonify({"error": f"Push failed: {err}"}), 502

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
