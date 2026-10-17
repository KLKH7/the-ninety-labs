// Momentum terrain viewer. Data comes from `python -m ninety.intel.terrain` (see README.md);
// every number on screen is read from that file, none is computed here beyond layout.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const source = new URLSearchParams(location.search).get('data') || 'seed7.json';
// Turning-point wording is written by ninety/agents/cues.py next to the data, one cue per
// persona; without that file the cards show only who took over and when.
const cueSource = source.replace(/\.json$/, '.cues.jsonl');
Promise.all([
  fetch(source).then(r => { if (!r.ok) throw new Error(`${source}: HTTP ${r.status}`); return r.json(); }),
  fetch(cueSource).then(r => r.ok ? r.text() : '').catch(() => ''),
])
  .then(([data, cueText]) => start(data, Object.fromEntries(cueText.split('\n').filter(Boolean)
    .map(line => JSON.parse(line)).map(cue => [cue.id, cue]))))
  .catch(err => {
    const f = document.getElementById('fallback');
    f.textContent = `Could not load ${source}: ${err.message}. Serve web/ over HTTP (see web/README.md).`;
    f.hidden = false;
  });

// Per-minute arrays are indexed from 0; index m is football minute m + 1, the minute every label
// and every turning point uses.
function start(D, cues) {
  const M = D.minutes, Z = D.zones;
  const W = 90, L = 42, H = 7;
  const maxCell = Math.max(...D.grid.flat().map(Math.abs));
  const name = id => (D.players.find(p => p.id === id) || {}).name || id;
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  let mode = 'casual', current = -1, playing = null;

  document.getElementById('score').textContent = `${D.score.home}–${D.score.away}`;
  document.getElementById('seed').textContent = D.seed == null ? source : `seed ${D.seed}`;
  document.getElementById('minutes').textContent = `${M}'`;

  const smoothGrid = D.grid.map((row, m) => row.map((_, z) => {
    const a = D.grid[Math.max(0, m - 1)][z], b = D.grid[m][z], c = D.grid[Math.min(M - 1, m + 1)][z];
    return (a + 2 * b + c) / 4;
  }));
  const heightAt = (m, z) => {
    const mi = Math.max(0, Math.min(M - 1, m)), zi = Math.max(0, Math.min(Z - 1, z));
    const m0 = Math.floor(mi), z0 = Math.floor(zi), m1 = Math.min(M - 1, m0 + 1), z1 = Math.min(Z - 1, z0 + 1);
    const fm = mi - m0, fz = zi - z0, g = smoothGrid;
    const v = (1 - fm) * ((1 - fz) * g[m0][z0] + fz * g[m0][z1]) + fm * ((1 - fz) * g[m1][z0] + fz * g[m1][z1]);
    return v / maxCell * H;
  };
  const toX = m => m / (M - 1) * W - W / 2;
  const toZ = z => L / 2 - z / (Z - 1) * L;
  const zoneOfX = x => x / 105 * Z - 0.5;

  const cueFor = t => cues[`cue-tp${t.minute}-${mode}`];
  function stopCopy(t) {
    const cue = cueFor(t);
    return cue ? cue.text : `${t.team === 'home' ? 'Home' : 'Away'} take over at ${t.minute}'.`;
  }
  function citation(t) {
    const ids = (cueFor(t) || {}).evidence || [];
    if (!ids.length) return 'no cue for this turning point';
    return mode === 'analyst' ? `cites ${ids.length} events, ${ids[0]}–${ids[ids.length - 1]}` : `${ids.length} events behind this`;
  }

  function renderStops() {
    const box = document.getElementById('stops');
    box.innerHTML = '';
    D.turning_points.forEach((t, i) => {
      const b = document.createElement('button');
      b.className = 'stop'; b.id = `stop-${i}`;
      b.setAttribute('aria-current', String(i === current));
      b.innerHTML = `<span class="min">${t.minute}'</span><span class="who ${t.team}-c">${t.team} take over</span>
        <p>${stopCopy(t)}</p><span class="cite">${citation(t)}</span>`;
      b.onclick = () => { stopPlay(); goTo(i); };
      box.appendChild(b);
    });
  }

  function renderStrip() {
    const svg = document.getElementById('strip'), mo = D.momentum;
    const lim = Math.max(...mo.map(Math.abs)) * 1.1, x = m => m / (M - 1) * 900, y = v => 55 - v / lim * 50;
    const pts = mo.map((v, m) => `${x(m)},${y(v)}`).join(' ');
    let s = `<defs><clipPath id="up"><rect x="0" y="0" width="900" height="55"/></clipPath><clipPath id="dn"><rect x="0" y="55" width="900" height="55"/></clipPath></defs>`;
    s += `<line x1="0" x2="900" y1="55" y2="55" stroke="var(--line)" stroke-width="1"/>`;
    [15, 30, 45, 60, 75].filter(m => m <= M).forEach(m => s += `<line x1="${x(m - 1)}" x2="${x(m - 1)}" y1="4" y2="106" stroke="var(--line)" stroke-dasharray="2 4"/>
      <text x="${x(m - 1) + 3}" y="106" font-size="10" font-family="IBM Plex Mono, monospace" fill="var(--muted)">${m}'</text>`);
    s += `<polygon points="0,55 ${pts} 900,55" fill="var(--home)" opacity=".35" clip-path="url(#up)"/>`;
    s += `<polygon points="0,55 ${pts} 900,55" fill="var(--away)" opacity=".35" clip-path="url(#dn)"/>`;
    s += `<polyline points="${pts}" fill="none" stroke="var(--ink)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>`;
    D.shots.forEach(sh => s += `<circle cx="${x(Math.max(0, sh.clock_min - 0.5))}" cy="${sh.team === 'home' ? 8 : 102}" r="3.5" fill="var(--${sh.team})"><title>${sh.team} shot, ${name(sh.player)}, ${sh.outcome.replace('_', ' ')}, ${sh.speed} km/h</title></circle>`);
    D.turning_points.forEach((t, i) => s += `<line x1="${x(t.minute - 1)}" x2="${x(t.minute - 1)}" y1="4" y2="106" stroke="var(--${t.team})" stroke-width="2" vector-effect="non-scaling-stroke" opacity="${i === current ? 1 : .55}"/>`);
    if (cursorMin >= 0) s += `<line x1="${x(cursorMin)}" x2="${x(cursorMin)}" y1="0" y2="110" stroke="var(--ink)" stroke-width="1" vector-effect="non-scaling-stroke"/>`;
    svg.innerHTML = s;
  }
  let cursorMin = -1;
  document.getElementById('strip').addEventListener('click', e => {
    const r = e.currentTarget.getBoundingClientRect();
    stopPlay(); flyToMinute(Math.round((e.clientX - r.left) / r.width * (M - 1)));
  });

  const sel = document.getElementById('player');
  const busiest = [...D.players].sort((a, b) => b.involvement.reduce((s, v) => s + v, 0) - a.involvement.reduce((s, v) => s + v, 0));
  D.players.forEach(p => {
    const o = document.createElement('option');
    o.value = p.id; o.textContent = `${p.name} · ${p.team} ${p.role}`;
    sel.appendChild(o);
  });
  sel.value = busiest[0].id;

  let scene, camera, renderer, controls, terrainMat, thread, beacons = [], target, wantCam, wantTarget;
  function init3D() {
    const stage = document.getElementById('stage');
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch (e) { document.getElementById('fallback').hidden = false; return; }
    renderer.setPixelRatio(Math.min(2, devicePixelRatio));
    stage.prepend(renderer.domElement);
    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(42, 1, 0.1, 500);
    camera.position.set(-58, 46, 62);
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49; controls.minDistance = 20; controls.maxDistance = 180;
    target = controls.target;

    const geo = new THREE.PlaneGeometry(W, L, (M - 1) * 2, (Z - 1) * 3);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position, colors = new Float32Array(pos.count * 3);
    for (let i = 0; i < pos.count; i++) {
      const m = (pos.getX(i) + W / 2) / W * (M - 1), z = (L / 2 - pos.getZ(i)) / L * (Z - 1);
      pos.setY(i, heightAt(m, z));
    }
    geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    terrainMat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .85, metalness: 0, side: THREE.DoubleSide, flatShading: false });
    const mesh = new THREE.Mesh(geo, terrainMat);
    mesh.name = 'terrain';
    scene.add(mesh);
    const wire = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ wireframe: true, transparent: true, opacity: .07, color: 0x000000 }));
    wire.name = 'wire';
    scene.add(wire);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x445544, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 2.4);
    sun.position.set(-30, 60, 40);
    scene.add(sun);

    const pitch = new THREE.Group();
    const lineMat = new THREE.LineBasicMaterial({ transparent: true, opacity: .35 });
    [0, 0.5, 1].forEach(f => {
      const z = L / 2 - f * L;
      pitch.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-W / 2, 0, z), new THREE.Vector3(W / 2, 0, z)]), lineMat));
    });
    [0, 15, 30, 45, 60, 75, M - 1].filter(m => m < M).forEach(m => pitch.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(
      [new THREE.Vector3(toX(m), 0, -L / 2), new THREE.Vector3(toX(m), 0, L / 2)]), lineMat)));
    pitch.name = 'pitch';
    scene.add(pitch);

    D.turning_points.forEach((t, i) => {
      const idx = t.minute - 1;
      const row = D.grid[idx];
      let zi = 0; row.forEach((v, z) => { if (Math.abs(v) > Math.abs(row[zi])) zi = z; });
      const h = heightAt(idx, zi);
      const g = new THREE.Group();
      const top = Math.max(h, 0) + 6;
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(.12, .12, top - Math.min(h, 0)), new THREE.MeshBasicMaterial());
      pole.position.y = (top + Math.min(h, 0)) / 2;
      const cap = new THREE.Mesh(new THREE.SphereGeometry(.7, 16, 12), new THREE.MeshBasicMaterial());
      cap.position.y = top;
      g.add(pole, cap);
      g.position.set(toX(idx), 0, toZ(zi));
      g.userData = { team: t.team, i, focus: new THREE.Vector3(toX(idx), h, toZ(zi)) };
      scene.add(g); beacons.push(g);
    });

    addAxisLabels(stage);
    applyTheme();
    buildThread();
    resize();
    new ResizeObserver(resize).observe(stage);
    hover(stage);
    renderer.setAnimationLoop(tick);
  }

  function addAxisLabels(stage) {
    const a = document.createElement('div');
    a.className = 'axis'; a.style.left = '14px'; a.style.bottom = '10px';
    a.textContent = `drag to orbit · scroll to zoom · time runs 1' → ${M}' · width is the pitch, home attacks away from you`;
    stage.appendChild(a);
  }

  function applyTheme() {
    if (!scene) return;
    const bg = new THREE.Color(css('--stage')), home = new THREE.Color(css('--home')), away = new THREE.Color(css('--away'));
    const flat = new THREE.Color(css('--line'));
    scene.background = bg;
    scene.fog = new THREE.Fog(bg, 110, 230);
    const mesh = scene.getObjectByName('terrain'), pos = mesh.geometry.attributes.position, col = mesh.geometry.attributes.color;
    const c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const h = pos.getY(i) / H;
      c.copy(flat).lerp(h >= 0 ? home : away, Math.min(1, Math.pow(Math.abs(h), .7) * 1.4));
      col.setXYZ(i, c.r, c.g, c.b);
    }
    col.needsUpdate = true;
    const dark = document.documentElement.dataset.theme === 'dark' || (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: dark)').matches);
    scene.getObjectByName('wire').material.color.set(dark ? 0xffffff : 0x000000);
    scene.getObjectByName('pitch').children.forEach(l => l.material.color.set(css('--muted')));
    beacons.forEach(b => b.children.forEach(o => o.material.color.set(css(`--${b.userData.team}`))));
    if (thread) thread.material.color.set(css('--ink'));
  }

  function buildThread() {
    if (!scene) return;
    if (thread) { scene.remove(thread); thread.geometry.dispose(); }
    const p = D.players.find(q => q.id === sel.value);
    const pts = [];
    p.x.forEach((x, m) => { if (x != null) { const z = zoneOfX(x); pts.push(new THREE.Vector3(toX(m), Math.max(0, heightAt(m, z)) + 1.2, toZ(z))); } });
    const curve = new THREE.CatmullRomCurve3(pts);
    const geo = new THREE.TubeGeometry(curve, pts.length * 4, .32, 8, false);
    thread = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: css('--ink') }));
    const dots = new THREE.Group();
    p.involvement.forEach((n, m) => {
      if (!n || p.x[m] == null) return;
      const z = zoneOfX(p.x[m]);
      const s = new THREE.Mesh(new THREE.SphereGeometry(.25 + Math.sqrt(n) * .28, 12, 10), new THREE.MeshBasicMaterial({ color: css(`--${p.team}`) }));
      s.position.set(toX(m), Math.max(0, heightAt(m, z)) + 1.2, toZ(z));
      dots.add(s);
    });
    thread.add(dots);
    scene.add(thread);
  }

  function resize() {
    const s = document.getElementById('stage'), w = s.clientWidth, h = s.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }

  function hover(stage) {
    const ray = new THREE.Raycaster(), v = new THREE.Vector2(), tip = document.getElementById('tip');
    renderer.domElement.addEventListener('pointermove', e => {
      const r = renderer.domElement.getBoundingClientRect();
      v.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
      ray.setFromCamera(v, camera);
      const hit = ray.intersectObject(scene.getObjectByName('terrain'))[0];
      if (!hit) { tip.hidden = true; return; }
      const m = Math.round((hit.point.x + W / 2) / W * (M - 1)), z = Math.round((L / 2 - hit.point.z) / L * (Z - 1));
      const val = D.grid[m][z], cvc = D.control_vs_chaos[m];
      tip.hidden = false;
      tip.innerHTML = `${m + 1}' · ${z * 5}–${z * 5 + 5} m from home goal<br>` +
        `threat <b class="${val >= 0 ? 'home' : 'away'}-c">${val >= 0 ? 'home' : 'away'} ${Math.abs(val).toFixed(2)}</b><br>` +
        (mode === 'analyst' ? `control−chaos (exp.) H ${cvc.home ?? '–'} · A ${cvc.away ?? '–'}` : `momentum ${D.momentum[m] >= 0 ? 'home' : 'away'}`);
    });
    renderer.domElement.addEventListener('pointerleave', () => tip.hidden = true);
  }

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function tick() {
    if (wantCam) {
      const k = reduce ? 1 : .06;
      camera.position.lerp(wantCam, k); target.lerp(wantTarget, k);
      if (camera.position.distanceTo(wantCam) < .2) wantCam = null;
    }
    controls.update();
    renderer.render(scene, camera);
  }

  function flyTo(focus) {
    if (!camera) return;
    wantTarget = focus.clone();
    wantCam = focus.clone().add(new THREE.Vector3(-24, 20, 26));
  }
  function flyToMinute(m) {
    cursorMin = m; current = D.turning_points.findIndex(t => t.minute - 1 === m);
    document.getElementById('cursor-label').textContent = `${m + 1}' · momentum ${D.momentum[m] >= 0 ? 'home' : 'away'} ${Math.abs(D.momentum[m]).toFixed(2)}`;
    renderStrip(); renderStops();
    const row = D.grid[m]; let zi = 0; row.forEach((v, z) => { if (Math.abs(v) > Math.abs(row[zi])) zi = z; });
    if (camera) flyTo(new THREE.Vector3(toX(m), heightAt(m, zi), toZ(zi)));
  }
  function goTo(i) {
    const t = D.turning_points[i];
    flyToMinute(t.minute - 1);
    current = i; renderStops(); renderStrip();
    if (beacons[i]) flyTo(beacons[i].userData.focus);
  }
  function stopPlay() { clearInterval(playing); playing = null; document.getElementById('play').textContent = '▶ Play the story'; }
  document.getElementById('play').onclick = () => {
    if (playing) return stopPlay();
    let i = 0; goTo(i);
    document.getElementById('play').textContent = '■ Stop';
    playing = setInterval(() => { i += 1; if (i >= D.turning_points.length) return stopPlay(); goTo(i); }, 3200);
  };
  ['casual', 'analyst', 'audio'].forEach(m => document.getElementById(`mode-${m}`).onclick = () => {
    mode = m;
    ['casual', 'analyst', 'audio'].forEach(k => document.getElementById(`mode-${k}`).setAttribute('aria-pressed', String(m === k)));
    renderStops();
  });
  sel.onchange = buildThread;
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  renderStrip(); renderStops();
  init3D();
}
