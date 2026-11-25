"""Writers: binary STL, the viewer's parts.json (Rev D format), the preview page and its screenshots."""
import base64
import json
import os
import subprocess
import numpy as np
import trimesh

REV_E = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# viewer colours (preview only; the record's viewer keeps its own LOOK table)
COLOURS = {
    "shell": "#272420", "mark": "#141210", "mark_period": "#e27b5b", "rear_plate": "#e27b5b",
    "backer": "#2b2d2f", "key_carrier": "#3a3d40", "key_shoes": "#3a3d40",
    "panel_face": "#3c3c3a", "panel_glass": "#8a9498", "panel_tail": "#c98a2b", "foam": "#5a5a5a",
    "hat_pcb": "#1f5fa8", "hat_header": "#111111", "hat_parts": "#e8e4da",
    "pi_pcb": "#2e7d32", "pi_metal": "#b9bcc0", "pi_black": "#1a1a1a", "pi_pins": "#d4af37", "heatsink": "#6d7378",
    "dupont": "#111111", "gh_lead": "#c62828", "j2_pins": "#d4af37", "j2_housing": "#111111", "j2_leads": "#f9a825",
    "usbc_adapter": "#202020", "usba_socket": "#9aa0a6", "usba_lead": "#202020", "screws_usba": "#8d9093",
    "key_switch": "#5d4037", "key_stem": "#8d6e63", "keycap": "#1b1b1b", "key_socket": "#e0e0e0",
    "screws_key": "#8d9093", "bars": "#78838c", "feet": "#d9d4c7", "inserts": "#c8a23a",
    "screws_rear": "#8d9093", "screws_pi": "#8d9093",
}
PRINTED = ["shell", "rear_plate", "backer", "key_carrier", "key_shoes"]


def write_stl(tm, path):
    tm.export(path, file_type="stl")


def b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def encode(mesh):
    V = np.asarray(mesh.V, "<f4")
    F = np.asarray(mesh.F)
    w = 2 if len(V) < 65536 else 4
    return {"p": b64(V.reshape(-1)), "i": b64(F.astype("<u2" if w == 2 else "<u4").reshape(-1)),
            "w": w, "nv": int(len(V)), "nt": int(len(F))}


def write_parts_json(meshes, meta, path):
    data = {"meta": meta, "parts": {k: encode(m) for k, m in meshes.items()}}
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return os.path.getsize(path)


PREVIEW = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Smylte desk unit G2 · Rev E · short wedge · preview</title>
<style>
 html,body{margin:0;height:100%;background:#f4f1e8;font:14px/1.4 -apple-system,Helvetica,Arial,sans-serif;color:#0e0e0c}
 #bar{position:absolute;top:12px;left:12px;display:flex;gap:8px;align-items:center;z-index:2}
 button,label{background:#fff;border:1px solid rgba(14,14,12,.2);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit}
 button[aria-pressed=true]{background:#0e0e0c;color:#fff}
 #note{position:absolute;bottom:10px;left:12px;color:rgba(14,14,12,.6);font-size:12px}
 canvas{display:block}
</style></head><body>
<div id="bar"><button id="b-asm" aria-pressed="true">Assembled</button><button id="b-exp" aria-pressed="false">Exploded</button>
<label><input type="checkbox" id="c-shell"> Shell off</label></div>
<div id="note">Rev E short wedge. Drag to orbit, wheel to zoom. Printed parts outlined; the rest are proxies.</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(function(){
const COL = __COLOURS__;
const PRINTED = __PRINTED__;
const GROUPS = [
 {parts:["shell","mark","mark_period","inserts"], ex:{n:200}},
 {parts:["bars"], ex:{n:200,y:35}},
 {parts:["feet"], ex:{n:200,y:-30}},
 {parts:["key_switch","key_stem","keycap"], ex:{n:200,x:45}},
 {parts:["key_carrier","key_socket","key_shoes","screws_key"], ex:{n:200,x:-40}},
 {parts:["panel_face","panel_glass","panel_tail"], ex:{n:140}},
 {parts:["foam"], ex:{n:110}},
 {parts:["backer","hat_pcb","hat_header","hat_parts"], ex:{n:70}},
 {parts:["rear_plate","usbc_adapter","usba_socket","usba_lead","screws_usba"], ex:{z:-120}},
 {parts:["pi_pcb","pi_metal","pi_black","pi_pins","heatsink","dupont","j2_pins","j2_housing","screws_pi"], ex:{z:-60}},
 {parts:["screws_rear"], ex:{z:-165}},
];
const LEADS = ["gh_lead","j2_leads"];
fetch("../viewer/parts.json").then(r=>r.json()).then(D=>{
 const M = D.meta, NO = new THREE.Vector3().fromArray(M.n_out);
 const W = innerWidth, H = innerHeight;
 const renderer = new THREE.WebGLRenderer({antialias:true, preserveDrawingBuffer:true});
 renderer.setPixelRatio(1); renderer.setSize(W,H); renderer.outputEncoding = THREE.sRGBEncoding;
 document.body.appendChild(renderer.domElement);
 const scene = new THREE.Scene(); scene.background = new THREE.Color(0xf4f1e8);
 scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8478, 0.75));
 const d1 = new THREE.DirectionalLight(0xffffff, 0.75); d1.position.set(250,400,500); scene.add(d1);
 const d2 = new THREE.DirectionalLight(0xffffff, 0.35); d2.position.set(-400,150,-300); scene.add(d2);
 const d3 = new THREE.DirectionalLight(0xffffff, 0.25); d3.position.set(0,-400,100); scene.add(d3);
 function geo(p){
  const pos = new Float32Array(Uint8Array.from(atob(p.p),c=>c.charCodeAt(0)).buffer);
  const ib = Uint8Array.from(atob(p.i),c=>c.charCodeAt(0)).buffer;
  const idx = p.w===2 ? new Uint16Array(ib) : new Uint32Array(ib);
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos,3));
  g.setIndex(new THREE.BufferAttribute(idx,1)); g.computeVertexNormals(); return g; }
 const nodes = {}, groupOf = {};
 const root = new THREE.Group(); scene.add(root);
 function addPart(name, parent){
  const p = D.parts[name]; if(!p) return;
  const g = geo(p);
  const mat = new THREE.MeshStandardMaterial({color:new THREE.Color(COL[name]||"#999").convertSRGBToLinear(),
     roughness: name.match(/metal|screw|insert|bars|pins/)?0.45:0.8, metalness: name.match(/metal|screw|insert|bars|heatsink/)?0.5:0.0,
     transparent:true, opacity:1, side:THREE.DoubleSide, polygonOffset:true, polygonOffsetFactor:1, polygonOffsetUnits:1});
  const mesh = new THREE.Mesh(g, mat); parent.add(mesh); nodes[name]=mesh;
  if(PRINTED.includes(name)){ const e = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28),
     new THREE.LineBasicMaterial({color:0x000000, transparent:true, opacity:0.22})); mesh.add(e); }
 }
 const groups = GROUPS.map(G=>{ const grp = new THREE.Group(); root.add(grp); G.parts.forEach(n=>{addPart(n,grp); groupOf[n]=grp;});
   const v = new THREE.Vector3(G.ex.x||0, G.ex.y||0, G.ex.z||0).addScaledVector(NO, G.ex.n||0); return {grp, v}; });
 const leadGrp = new THREE.Group(); root.add(leadGrp); LEADS.forEach(n=>addPart(n, leadGrp));
 // screen and panel white
 function quad(c, color, off){ const g = new THREE.BufferGeometry(); const a=[]; [0,1,2,0,2,3].forEach(i=>a.push(...c[i]));
   g.setAttribute("position", new THREE.Float32BufferAttribute(a,3)); g.computeVertexNormals();
   const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({color:new THREE.Color(color).convertSRGBToLinear(), roughness:0.95, side:THREE.DoubleSide,
     polygonOffset:true, polygonOffsetFactor:0, polygonOffsetUnits:-4*off})); return m; }
 const pg = groups[5].grp; pg.add(quad(M.panel_front, "#5b5b58", 1)); pg.add(quad(M.screen, "#d4d1c6", 2));
 // camera
 const cam = new THREE.PerspectiveCamera(26, W/H, 5, 5000);
 const target = new THREE.Vector3(0, 60, 33);
 let th = 0.65, ph = 1.25, dist = 560, t = 0, tt = 0;
 function place(){ cam.position.set(target.x + dist*Math.sin(ph)*Math.sin(th), target.y + dist*Math.cos(ph), target.z + dist*Math.sin(ph)*Math.cos(th)); cam.lookAt(target); }
 function draw(){ groups.forEach(G=>G.grp.position.copy(G.v).multiplyScalar(t)); leadGrp.visible = t < 0.2; place(); renderer.render(scene, cam); }
 function anim(){ if(Math.abs(tt-t)>1e-3){ t += (tt-t)*0.2; if(Math.abs(tt-t)<1e-3) t=tt; draw(); } requestAnimationFrame(anim); }
 function setShell(off){ ["shell","mark","mark_period","inserts"].forEach(n=>{ if(nodes[n]) nodes[n].visible=!off; }); draw(); }
 function explode(on){ tt = on?1:0; document.getElementById("b-asm").setAttribute("aria-pressed", String(!on));
   document.getElementById("b-exp").setAttribute("aria-pressed", String(on)); }
 document.getElementById("b-asm").onclick=()=>explode(false); document.getElementById("b-exp").onclick=()=>explode(true);
 document.getElementById("c-shell").onchange=e=>setShell(e.target.checked);
 let drag=null; renderer.domElement.addEventListener("pointerdown",e=>drag=[e.clientX,e.clientY,th,ph]);
 addEventListener("pointerup",()=>drag=null);
 addEventListener("pointermove",e=>{ if(!drag) return; th = drag[2]-(e.clientX-drag[0])*0.006; ph = Math.min(3.1,Math.max(0.05, drag[3]-(e.clientY-drag[1])*0.006)); draw(); });
 renderer.domElement.addEventListener("wheel",e=>{ e.preventDefault(); dist *= Math.exp(e.deltaY*0.001); draw(); },{passive:false});
 window.__view = { set(a,b,d,tgt){ th=a; ph=b; if(d) dist=d; if(tgt) target.set(...tgt); draw(); },
   explodeNow(on){ tt = t = on?1:0; explode(on); draw(); }, shell(off){ document.getElementById("c-shell").checked=off; setShell(off); } };
 draw(); anim(); window.__ready = true;
}).catch(e=>{ document.body.textContent = "Failed: " + e; window.__ready = "error"; });
})();
</script></body></html>
"""

SHOOT = r"""// Screenshots of preview.html with Playwright (headless Chromium), 1400 × 900.
// The page and parts.json are served from disk by request interception (origin http://rev-e.local);
// three.js r128 comes from cdnjs through the session's HTTPS proxy, if one is set.
const path = require('path'); const fs = require('fs');
const { chromium } = require('/home/user/smylte/frontend/node_modules/playwright');
const ROOT = path.resolve(__dirname, '..');
const TYPES = {'.html':'text/html', '.json':'application/json', '.js':'text/javascript'};
const SHOTS = [
  ['front-three-quarter', v => v.set(0.62, 1.25, 430)],
  ['side', v => v.set(Math.PI / 2, 1.5708, 400)],
  ['rear-three-quarter', v => v.set(Math.PI - 0.7, 1.18, 430)],
  ['exploded', v => { v.explodeNow(true); v.set(1.3, 1.25, 1000, [0, 95, 70]); }],
  ['shell-off', v => { v.explodeNow(false); v.set(1.62, 1.3, 440, [0, 60, 33]); v.shell(true); }],
  ['bottom', v => { v.shell(false); v.set(0.35, 2.75, 430); }],
];
(async () => {
  const proxy = process.env.HTTPS_PROXY || process.env.https_proxy;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
    proxy: proxy ? { server: proxy } : undefined });
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await page.route('http://rev-e.local/**', route => {
    const p = path.join(ROOT, decodeURIComponent(new URL(route.request().url()).pathname));
    if (!p.startsWith(ROOT) || !fs.existsSync(p)) return route.fulfill({ status: 404, body: '' });
    route.fulfill({ status: 200, contentType: TYPES[path.extname(p)] || 'application/octet-stream', body: fs.readFileSync(p) });
  });
  page.on('console', m => { if (m.type() === 'error') console.log('console:', m.text()); });
  await page.goto('http://rev-e.local/preview/preview.html');
  await page.waitForFunction(() => window.__ready !== undefined, null, { timeout: 120000 });
  if (await page.evaluate(() => window.__ready) !== true) throw new Error('preview failed to load');
  for (const [name, fn] of SHOTS) {
    await page.evaluate(`(${fn.toString()})(window.__view)`);
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(__dirname, `${name}.png`) });
    console.log('wrote', name + '.png');
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
"""


def write_preview():
    d = os.path.join(REV_E, "preview")
    html = PREVIEW.replace("__COLOURS__", json.dumps(COLOURS)).replace("__PRINTED__", json.dumps(PRINTED))
    open(os.path.join(d, "preview.html"), "w").write(html)
    open(os.path.join(d, "shoot.cjs"), "w").write(SHOOT)


def shoot():
    d = os.path.join(REV_E, "preview")
    r = subprocess.run(["node", os.path.join(d, "shoot.cjs")], capture_output=True, text=True, timeout=600)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr.strip())
        raise SystemExit("screenshots failed")
