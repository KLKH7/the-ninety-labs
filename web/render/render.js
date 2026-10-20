// Broadcast renderer for The Ninety Labs.
//
// Python (ninety/render) owns the scene: it sends the camera and every body part in world
// metres for each frame. This page draws them, then renders an object-id pass to count, per
// player and ball, the pixels it covers alone (solo pass) and the pixels still visible in the
// full scene. Visibility and pixel boxes therefore come from exactly what was drawn.
//
// World axes are pitch metres: x along the pitch (0..105), y from the near touchline (0..68),
// z up. Pixel coordinates have their origin at the top-left corner of the image.

import * as THREE from 'three';

const PX_PER_M = 35; // pitch texture resolution
const GROUND = { x0: -6, x1: 111, y0: -6, y1: 74 }; // pitch plus apron covered by the texture
const POST_ID = 250; // goal frame: an occluder with no label
const SCENERY_ID = 251; // boards, stands, roofs and towers: occluders with no label

function rng(seed) { // mulberry32
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hsl(h, s, l) { return `hsl(${(h * 360).toFixed(1)},${(s * 100).toFixed(1)}%,${(l * 100).toFixed(1)}%)`; }

function canvasTexture(canvas, srgb = true) {
  const tex = new THREE.CanvasTexture(canvas);
  if (srgb) tex.colorSpace = THREE.SRGBColorSpace;
  tex.generateMipmaps = true;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.magFilter = THREE.LinearFilter;
  return tex;
}

// ---- static scene ---------------------------------------------------------------------------

function pitchTexture(p, rand) {
  const W = (GROUND.x1 - GROUND.x0) * PX_PER_M, H = (GROUND.y1 - GROUND.y0) * PX_PER_M;
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const g = c.getContext('2d');
  const X = (x) => (x - GROUND.x0) * PX_PER_M;
  const Y = (y) => (GROUND.y1 - y) * PX_PER_M;

  // Broadcast turf: darker, less electric. Adjacent stripes shift hue the way a real mower does.
  const hue = p.grass_hue;
  const night = p.lighting === 'night';
  for (let x = GROUND.x0, i = 0; x < GROUND.x1; x += p.stripe_width_m, i++) {
    const alt = i % 2;
    g.fillStyle = hsl(hue + (alt ? 0.018 : -0.006), 0.40, (alt ? 0.19 : 0.27) * (night ? 0.95 : 1));
    g.fillRect(X(x), 0, p.stripe_width_m * PX_PER_M + 1, H);
  }
  // grain
  const img = g.getImageData(0, 0, W, H);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (rand() - 0.5) * 18;
    d[i] += n; d[i + 1] += n * 1.2; d[i + 2] += n * 0.6;
  }
  g.putImageData(img, 0, 0);
  if (p.weather === 'rain') {
    g.fillStyle = 'rgba(6, 14, 10, 0.34)';
    g.fillRect(0, 0, W, H);
  }
  // Run-off around the playing surface, so the pitch reads as a pitch.
  g.fillStyle = hsl(0.08, 0.1, night ? 0.12 : 0.2);
  g.fillRect(0, 0, W, Y(68));
  g.fillRect(0, Y(0), W, H - Y(0));
  g.fillRect(0, 0, X(0), H);
  g.fillRect(X(105), 0, W - X(105), H);
  // wear: goalmouths and the centre circle, as thin, pale grass. The shader tints it (uWear); the
  // texture only breaks it up a little, a few pale tufts, never brown blotches across the area.
  const wearSpots = [[5, 34, 7], [100, 34, 7], [11, 34, 5], [94, 34, 5], [52.5, 34, 6]];
  for (const [wx, wy, wr] of wearSpots) {
    for (let k = 0; k < 120 * p.wear; k++) {
      const a = rand() * 6.283, r = Math.sqrt(rand()) * wr;
      g.fillStyle = `rgba(150,150,90,${0.06 + 0.08 * rand()})`;
      g.fillRect(X(wx + Math.cos(a) * r), Y(wy + Math.sin(a) * r), 3 + 4 * rand(), 2 + 3 * rand());
    }
  }
  // markings, 12 cm wide
  g.strokeStyle = 'rgba(245,245,240,0.93)';
  g.fillStyle = 'rgba(245,245,240,0.93)';
  g.lineWidth = 0.12 * PX_PER_M;
  const line = (pts) => { g.beginPath(); g.moveTo(X(pts[0][0]), Y(pts[0][1])); for (const q of pts.slice(1)) g.lineTo(X(q[0]), Y(q[1])); g.stroke(); };
  const arc = (cx, cy, r, a0, a1) => { g.beginPath(); g.arc(X(cx), Y(cy), r * PX_PER_M, -a1, -a0); g.stroke(); };
  const spot = (x, y) => { g.beginPath(); g.arc(X(x), Y(y), 0.15 * PX_PER_M, 0, 6.283); g.fill(); };
  line([[0, 0], [105, 0], [105, 68], [0, 68], [0, 0]]);
  line([[52.5, 0], [52.5, 68]]);
  arc(52.5, 34, 9.15, 0, 6.2832);
  spot(52.5, 34);
  for (const [gx, s] of [[0, 1], [105, -1]]) {
    line([[gx, 13.84], [gx + s * 16.5, 13.84], [gx + s * 16.5, 54.16], [gx, 54.16]]);
    line([[gx, 24.84], [gx + s * 5.5, 24.84], [gx + s * 5.5, 43.16], [gx, 43.16]]);
    spot(gx + s * 11, 34);
    const a = Math.acos(5.5 / 9.15);
    if (s > 0) arc(11, 34, 9.15, -a, a); else arc(94, 34, 9.15, Math.PI - a, Math.PI + a);
    for (const cy of [0, 68]) arc(gx, cy, 1, s > 0 ? (cy ? -Math.PI / 2 : 0) : (cy ? Math.PI : Math.PI / 2), s > 0 ? (cy ? 0 : Math.PI / 2) : (cy ? 1.5 * Math.PI : Math.PI));
  }
  return canvasTexture(c);
}

function loadTex(url, srgb) {
  return new Promise((resolve) => {
    new THREE.TextureLoader().load(url, (tex) => {
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.colorSpace = srgb ? THREE.SRGBColorSpace : THREE.NoColorSpace;
      tex.anisotropy = 8;
      resolve(tex);
    }, undefined, () => resolve(null));
  });
}

let grassPromise = null;
function loadGrass() {
  if (!grassPromise) {
    grassPromise = Promise.all([
      loadTex('./assets/grass.jpg', true),
      loadTex('./assets/grass-normal.jpg', false),
    ]).then(([color, normal]) => ({ color, normal }));
  }
  return grassPromise;
}

function decoratePitch(mat, wet, grass, normal, p) {
  const az = THREE.MathUtils.degToRad(p.sun_azimuth_deg);
  const el = THREE.MathUtils.degToRad(Math.max(p.sun_elevation_deg, 12));
  const sun = new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el)).normalize();
  const mow = { day: 1, dusk: 0.8, night: 0.12, overcast: 0.3 }[p.lighting] ?? 0.5;
  mat.customProgramCacheKey = () => (wet ? 'pitch-wet' : 'pitch-dry') + (grass ? '-photo' : '') + (normal ? '-n' : '');
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uWet = { value: wet ? 1 : 0 };
    const blank = () => {
      const t = new THREE.DataTexture(new Uint8Array([128, 128, 255, 255]), 1, 1);
      t.needsUpdate = true;
      return t;
    };
    shader.uniforms.uGrass = { value: grass || blank() };
    shader.uniforms.uHasGrass = { value: grass ? 1 : 0 };
    shader.uniforms.uGrassN = { value: normal || blank() };
    shader.uniforms.uHasN = { value: normal ? 1 : 0 };
    shader.uniforms.uSun = { value: sun };
    shader.uniforms.uStripe = { value: p.stripe_width_m };
    shader.uniforms.uX0 = { value: GROUND.x0 };
    shader.uniforms.uMow = { value: mow };
    shader.uniforms.uWear = { value: p.wear };
    shader.vertexShader = 'varying vec3 vGrassW;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace(
      '#include <project_vertex>',
      '#include <project_vertex>\n vGrassW = (modelMatrix * vec4(transformed, 1.0)).xyz;'
    );
    shader.fragmentShader = `
      varying vec3 vGrassW;
      uniform float uWet;
      uniform float uWear;
      uniform sampler2D uGrass;
      uniform sampler2D uGrassN;
      uniform float uHasGrass;
      uniform float uHasN;
      uniform vec3 uSun;
      uniform float uStripe;
      uniform float uX0;
      uniform float uMow;
      float stripeAlt(vec2 w){ return mod(floor((w.x - uX0) / max(uStripe, 0.5)), 2.0); }
      float ghash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float gnoise(vec2 p){
        vec2 i = floor(p); vec2 f = fract(p);
        float a = ghash(i), b = ghash(i + vec2(1.0, 0.0)), c = ghash(i + vec2(0.0, 1.0)), d = ghash(i + vec2(1.0, 1.0));
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
      }
    ` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <normal_fragment_maps>', `
      #include <normal_fragment_maps>
      float altN = stripeAlt(vGrassW.xy);
      vec3 nPert = vec3(0.0, altN > 0.5 ? 0.32 : -0.32, 0.0);
      if (uHasN > 0.5) {
        vec3 tn = texture2D(uGrassN, vGrassW.xy * 0.4).xyz;
        tn.y = 1.0 - tn.y;
        tn = tn * 2.0 - 1.0;
        nPert += tn * 0.40;
      }
      normal = normalize(normal + nPert);
    `);
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
      #include <map_fragment>
      float pale = smoothstep(0.62, 0.86, dot(diffuseColor.rgb, vec3(0.299, 0.587, 0.114)));
      // The markings (pale) are never worn.
      float worn = 0.0;
      worn = max(worn, 1.0 - smoothstep(3.2, 7.0, length(vGrassW.xy - vec2(5.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(3.2, 7.0, length(vGrassW.xy - vec2(100.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.2, 5.0, length(vGrassW.xy - vec2(11.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.2, 5.0, length(vGrassW.xy - vec2(94.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.6, 6.0, length(vGrassW.xy - vec2(52.5, 34.0))));
      worn *= 1.0 - pale;
      // Worn turf is thinner, paler, yellower grass, not bare earth, and it follows the mowing:
      // the stripe that lies toward the camera shows it a little more (design). A clip's wear
      // (0.1 to 0.9) sets how much, at most 45% of the way to that tint.
      worn *= uWear * 0.45 * (0.75 + 0.25 * stripeAlt(vGrassW.xy));
      diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(1.12, 1.04, 0.78), worn);
      float clump = gnoise(vGrassW.xy * 0.22);
      diffuseColor.rgb *= mix(0.9 + 0.12 * clump, 1.0, pale);
      if (uHasGrass > 0.5) {
        vec3 photo = texture2D(uGrass, vGrassW.xy * 0.035).rgb;
        float photoL = max(dot(photo, vec3(0.333)), 0.05);
        vec3 detail = photo / photoL;
        diffuseColor.rgb *= mix(vec3(1.0), detail * 0.55 + 0.45, (1.0 - pale) * (1.0 - worn) * 0.32);
      }
      vec3 view = normalize(cameraPosition - vGrassW);
      float sheen = pow(1.0 - clamp(view.z, 0.0, 1.0), 2.4) * (0.45 + 0.55 * gnoise(vGrassW.xy * vec2(0.15, 1.1)));
      diffuseColor.rgb += vec3(0.09, 0.12, 0.05) * sheen * (1.0 - pale) * (1.0 - worn) * (uWet > 0.5 ? 1.6 : 1.0);
      float altC = stripeAlt(vGrassW.xy);
      vec3 blade = normalize(vec3(0.0, altC > 0.5 ? 1.0 : -1.0, 0.28));
      vec3 halfV = normalize(normalize(uSun) + view);
      float mow = pow(clamp(dot(blade, halfV), 0.0, 1.0), 5.0);
      diffuseColor.rgb += vec3(0.16, 0.20, 0.08) * mow * (1.0 - pale) * (1.0 - worn) * uMow;
      if (uWet > 0.5) diffuseColor.rgb *= vec3(0.9, 0.95, 0.92);
    `);
  };
  return mat;
}

// u runs from p0 to p1 and v from p0 to p3: a texture reads left to right for a viewer on the side
// the quad's corners go round anticlockwise. `repeat` tiles a repeating texture that many times.
function quad(p0, p1, p2, p3, material, repeat = [1, 1]) {
  const geo = new THREE.BufferGeometry();
  const [ru, rv] = repeat;
  const uv = [0, 0, ru, 0, ru, rv, 0, 0, ru, rv, 0, rv];
  geo.setAttribute('position', new THREE.Float32BufferAttribute([...p0, ...p1, ...p2, ...p0, ...p2, ...p3], 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  geo.computeVertexNormals();
  return new THREE.Mesh(geo, material);
}

function crowdTexture(p, rand, w, h) {
  // The gantry sees sections, aisles and rows. A face would be a speck, so a person is just a darker seat.
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  g.fillStyle = '#101216';
  g.fillRect(0, 0, w, h);
  const plastics = ['#1a3d72', '#16325c', '#6a2832', '#1a3d72', '#7a6844', '#16325c'];
  const start = Math.floor(rand() * plastics.length);
  const section = 220;
  const aisle = 22;
  const rowH = 12;
  for (let x = 0, n = 0; x < w; x += section, n++) {
    g.fillStyle = plastics[(start + n) % plastics.length];
    g.fillRect(x, 0, section - aisle, h);
  }
  for (let y = 0, i = 0; y < h; y += rowH, i++) {
    g.fillStyle = i % 2 ? 'rgba(0,0,0,0.22)' : 'rgba(255,255,255,0.06)';
    g.fillRect(0, y, w, rowH - 3);
    g.fillStyle = 'rgba(0,0,0,0.45)';
    g.fillRect(0, y + rowH - 3, w, 3);
  }
  // A gangway across the tier, wide enough to survive the gantry.
  const gang = Math.floor(h * 0.62);
  g.fillStyle = '#14171c';
  g.fillRect(0, gang, w, 20);
  const seatW = 8;
  for (let y = 0; y < h; y += rowH) {
    if (y >= gang && y < gang + 20) continue;
    for (let x = 0; x < w; x += seatW) {
      if ((x % section) >= section - aisle) continue;
      if (rand() > p.crowd_density) continue;
      g.fillStyle = 'rgba(8,6,5,0.5)';
      g.fillRect(x + 2, y + 4, seatW - 4, rowH - 7);
    }
  }
  return canvasTexture(c);
}

// A tier of seats. The seat texture spans 118 m (a side stand) unless `uSpan` says what share of it
// this tier shows, so a short or skewed tier has seats of the same size.
function tier(decor, p, rand, corners, aniso, uSpan = 1) {
  const map = crowdTexture(p, rand, 2048, 384);
  map.anisotropy = aniso;
  const mat = new THREE.MeshStandardMaterial({
    map,
    roughness: 0.96,
    emissive: new THREE.Color(p.lighting === 'night' ? 0x2a2a2a : 0x121212),
    emissiveIntensity: p.lighting === 'night' ? 0.55 : 0.02,
    side: THREE.DoubleSide,
  });
  decor.push(quad(...corners, mat, [uSpan, 1]));
}

// Cladding for the stands' structure: panels in the stand colour, each a little lighter or darker,
// with seams, a row of concourse openings and weathering toward the ground. One tile is 32 x 8 m.
function claddingTexture(p, rand) {
  const c = document.createElement('canvas');
  c.width = 1024; c.height = 256;
  const g = c.getContext('2d');
  const base = new THREE.Color(p.stand_color || '#3a3f4a');
  const tone = {};
  base.getHSL(tone);
  const panel = 64;
  for (let x = 0; x < c.width; x += panel) {
    for (let y = 0; y < c.height; y += panel) {
      g.fillStyle = hsl(tone.h, tone.s * 0.6, Math.min(0.62, tone.l + 0.16 + 0.05 * (rand() - 0.5)));
      g.fillRect(x, y, panel, panel);
    }
  }
  g.fillStyle = 'rgba(0,0,0,0.35)';
  for (let x = 0; x < c.width; x += panel) g.fillRect(x, 0, 2, c.height);
  for (let y = 0; y < c.height; y += panel) g.fillRect(0, y, c.width, 2);
  // Concourse openings, dark, in a band a third of the way up.
  g.fillStyle = 'rgba(12,14,18,0.85)';
  for (let x = 10; x < c.width; x += 128) g.fillRect(x, 150, 92, 34);
  // Weathering: darker toward the bottom of each tile.
  const grd = g.createLinearGradient(0, 0, 0, c.height);
  grd.addColorStop(0, 'rgba(0,0,0,0.0)');
  grd.addColorStop(1, 'rgba(0,0,0,0.28)');
  g.fillStyle = grd;
  g.fillRect(0, 0, c.width, c.height);
  const tex = canvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}

// The underside of a roof: steel trusses across a dark deck. One tile is 24 x 16 m.
function roofTexture() {
  const c = document.createElement('canvas');
  c.width = 512; c.height = 256;
  const g = c.getContext('2d');
  g.fillStyle = '#2a2e35';
  g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = '#4a505a';
  for (let x = 0; x < c.width; x += 64) g.fillRect(x, 0, 6, c.height);
  g.fillStyle = '#383d45';
  for (let y = 0; y < c.height; y += 32) g.fillRect(0, y, c.width, 3);
  const tex = canvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  return tex;
}


function boardTexture(p, rand) {
  const c = document.createElement('canvas');
  c.width = 4096; c.height = 64;
  const g = c.getContext('2d');
  let x = 0;
  while (x < c.width) {
    const brand = p.boards[Math.floor(rand() * p.boards.length)];
    const bg = hsl(rand(), 0.6, 0.25 + 0.3 * rand());
    g.fillStyle = bg; g.fillRect(x, 0, 512, 64);
    g.fillStyle = '#f8f8f8';
    g.font = 'bold 40px sans-serif';
    g.textBaseline = 'middle';
    g.fillText(brand, x + 24, 34, 470);
    x += 512;
  }
  return canvasTexture(c);
}

// Same curve as ninety.render.camera.net_push. Outward only, and it settles inside 2.6 s.
function netPush(age, speed, y, z, hitY, hitZ) {
  if (age < 0 || age > 2.6) return 0;
  const dy = y - hitY, dz = z - hitZ;
  const dist = Math.hypot(dy, dz);
  const delay = 0.035 * dist;
  if (age < delay) return 0;
  const amp = Math.min(0.85, 0.2 + Math.min(speed, 28) * 0.02);
  const fall = Math.exp(-(dist * dist) / 1.6);
  const env = Math.exp(-(age - delay) * 2.4);
  const ring = 0.7 + 0.3 * (0.5 + 0.5 * Math.cos(age * 15));
  return amp * fall * env * ring;
}

function buildNet(gx, sign, material) {
  const y0 = 30.34, y1 = 37.66, depth = 2.0, backZ = 2.0;
  const positions = [];
  const uvs = [];
  const indices = [];
  const weight = [];
  const addGrid = (nu, nv, at) => {
    const base = positions.length / 3;
    for (let iv = 0; iv < nv; iv++) {
      for (let iu = 0; iu < nu; iu++) {
        const u = iu / (nu - 1), v = iv / (nv - 1);
        const p = at(u, v);
        const sag = Math.sin(Math.PI * u) * Math.sin(Math.PI * v);
        positions.push(p.x + sign * 0.1 * sag * p.w, p.y, Math.max(0.02, p.z - 0.08 * sag * p.w));
        uvs.push(p.u / 0.16, p.v / 0.16);
        weight.push(p.w);
      }
    }
    for (let iv = 0; iv < nv - 1; iv++) {
      for (let iu = 0; iu < nu - 1; iu++) {
        const i = base + iv * nu + iu;
        indices.push(i, i + 1, i + nu, i + 1, i + nu + 1, i + nu);
      }
    }
  };
  addGrid(18, 10, (u, v) => ({
    x: gx + sign * depth, y: y0 + (y1 - y0) * u, z: backZ * v, w: 1,
    u: (y1 - y0) * u, v: backZ * v,
  }));
  addGrid(18, 7, (u, v) => ({
    x: gx + sign * depth * v,
    y: y0 + (y1 - y0) * u,
    z: 2.44 + (backZ - 2.44) * v,
    w: v,
    u: (y1 - y0) * u,
    v: depth * v,
  }));
  for (const y of [y0, y1]) {
    addGrid(7, 10, (u, v) => ({
      x: gx + sign * depth * u,
      y,
      z: (2.44 - 0.44 * u) * v,
      w: u,
      u: depth * u,
      v: (2.44 - 0.44 * u) * v,
    }));
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, material);
  mesh.userData.rest = new Float32Array(positions);
  mesh.userData.weight = new Float32Array(weight);
  mesh.frustumCulled = false;
  return mesh;
}

function poseNet(mesh, hit) {
  const pos = mesh.geometry.attributes.position;
  const rest = mesh.userData.rest;
  const weight = mesh.userData.weight;
  const sign = mesh.userData.sign;
  const live = hit && hit.side === mesh.userData.side;
  for (let i = 0; i < weight.length; i++) {
    let x = rest[i * 3], y = rest[i * 3 + 1], z = rest[i * 3 + 2];
    if (live && weight[i] > 0) {
      const push = weight[i] * netPush(hit.age, hit.speed, y, z, hit.y, hit.z);
      x += sign * push;
      z = Math.max(0.02, z - 0.18 * push);
    }
    pos.setXYZ(i, x, y, z);
  }
  pos.needsUpdate = true;
  mesh.geometry.computeVertexNormals();
}

function netTexture() {
  // One cell of cord. The knot sits on the corner so the repeat completes it.
  const s = 64;
  const c = document.createElement('canvas');
  c.width = s; c.height = s;
  const g = c.getContext('2d');
  g.clearRect(0, 0, s, s);
  g.strokeStyle = 'rgba(236,236,232,0.96)';
  g.lineWidth = 6;
  g.lineCap = 'butt';
  g.beginPath();
  g.moveTo(0, 3); g.lineTo(s, 3);
  g.moveTo(3, 0); g.lineTo(3, s);
  g.stroke();
  g.fillStyle = 'rgba(248,248,244,1)';
  g.beginPath();
  g.arc(0, 0, 11, 0, Math.PI * 2);
  g.fill();
  const t = canvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8;
  return t;
}

// Capsule UVs do not carry a shirt graphic (a sphere samples one texel of it). The pattern is
// computed from world position in the material, so every piece of the shirt agrees.
const PATTERN_ID = { solid: 0, stripes: 1, hoops: 2, sash: 3, halves: 4, bands: 5 };

function numberTexture(n) {
  const c = document.createElement('canvas');
  c.width = 64; c.height = 64;
  const g = c.getContext('2d');
  g.clearRect(0, 0, 64, 64);
  g.fillStyle = '#fff';
  g.font = 'bold 48px sans-serif';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(String(n), 32, 34);
  const tex = canvasTexture(c, false);
  tex.generateMipmaps = false;
  tex.minFilter = THREE.LinearFilter;
  return tex;
}

function kitMaterial(id, slot, primary, secondary, pattern, number) {
  const mat = new THREE.MeshStandardMaterial({ roughness: ROUGHNESS[slot] ?? 0.8, metalness: 0 });
  const l = new THREE.Color(primary);
  const luma = 0.2126 * l.r + 0.7152 * l.g + 0.0722 * l.b;
  const uniforms = {
    uPrimary: { value: new THREE.Color(primary) },
    uSecondary: { value: new THREE.Color(secondary) },
    uDigit: { value: new THREE.Color(luma > 0.45 ? 0x141414 : 0xf4f4f4) },
    uPattern: { value: PATTERN_ID[pattern] ?? 0 },
    uOrigin: { value: new THREE.Vector2() },
    uLeft: { value: new THREE.Vector2(1, 0) },
    uFwd: { value: new THREE.Vector2(0, 1) },
    uNumber: { value: number != null ? numberTexture(number) : numberTexture(0) },
    uHasNumber: { value: number != null ? 1 : 0 },
  };
  mat.userData.kit = uniforms;
  mat.customProgramCacheKey = () => `kit-${id}-${slot}`;
  mat.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = 'varying vec3 vWpos; varying vec3 vWnor;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader
      .replace('#include <beginnormal_vertex>', '#include <beginnormal_vertex>\n vWnor = normalize(mat3(modelMatrix) * objectNormal);')
      .replace('#include <project_vertex>', '#include <project_vertex>\n vWpos = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = `varying vec3 vWpos; varying vec3 vWnor;
      uniform vec3 uPrimary; uniform vec3 uSecondary; uniform vec3 uDigit;
      uniform float uPattern; uniform float uHasNumber;
      uniform vec2 uOrigin; uniform vec2 uLeft; uniform vec2 uFwd;
      uniform sampler2D uNumber;
    ` + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
      vec2 sideV = vWpos.xy - uOrigin;
      float side = dot(sideV, uLeft);
      vec3 kit = uPrimary;
      if (uPattern < 0.5) {
        kit = uPrimary;
      } else if (uPattern < 1.5) {
        kit = fract(side * 8.0) < 0.42 ? uSecondary : uPrimary;
      } else if (uPattern < 2.5) {
        kit = fract(vWpos.z * 5.2) < 0.46 ? uSecondary : uPrimary;
      } else if (uPattern < 3.5) {
        kit = abs(side * 1.7 + (vWpos.z - 1.22)) < 0.085 ? uSecondary : uPrimary;
      } else if (uPattern < 4.5) {
        kit = side > 0.0 ? uSecondary : uPrimary;
      } else {
        kit = (vWpos.z < 0.30 && fract(vWpos.z * 12.0) < 0.32) ? uSecondary : uPrimary;
      }
      if (uPattern < 4.5 && vWpos.z > 1.46) kit = mix(kit, uSecondary, 0.9);
      float torso = smoothstep(1.02, 1.12, vWpos.z) * (1.0 - smoothstep(1.40, 1.50, vWpos.z));
      kit *= mix(1.0, 0.78, smoothstep(0.09, 0.16, abs(side)) * torso);
      float facing = dot(normalize(vWnor.xy + vec2(0.0001)), uFwd);
      vec2 nuv = vec2(side / 0.14 * 0.5 + 0.5, (vWpos.z - 1.04) / 0.30);
      if (uHasNumber > 0.5 && facing < -0.2 && nuv.x > 0.05 && nuv.x < 0.95 && nuv.y > 0.05 && nuv.y < 0.95) {
        kit = mix(kit, uDigit, smoothstep(0.25, 0.6, texture2D(uNumber, nuv).r));
      }
      diffuseColor.rgb = kit;
    `);
  };
  return mat;
}

const BALL_PANELS = (() => {
  const t = (1 + Math.sqrt(5)) / 2;
  return [[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]]
    .map((v) => new THREE.Vector3(v[0], v[1], v[2]).normalize());
})();

function ballMaterial() {
  const mat = new THREE.MeshStandardMaterial({ roughness: ROUGHNESS.ball, metalness: METALNESS.ball, color: 0xffffff });
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uIco = { value: BALL_PANELS };
    shader.vertexShader = 'varying vec3 vObj;\n' + shader.vertexShader.replace(
      '#include <beginnormal_vertex>',
      '#include <beginnormal_vertex>\n vObj = normalize(objectNormal);'
    );
    shader.fragmentShader = 'varying vec3 vObj;\nuniform vec3 uIco[12];\n' + shader.fragmentShader.replace('#include <map_fragment>', `
      float pent = 0.0;
      for (int i = 0; i < 12; i++) pent = max(pent, smoothstep(0.80, 0.92, dot(normalize(vObj), uIco[i])));
      diffuseColor.rgb = mix(vec3(0.95, 0.95, 0.93), vec3(0.07, 0.07, 0.08), pent);
    `);
  };
  mat.customProgramCacheKey = () => 'ball-panels';
  return mat;
}

function skyTexture(p) {
  const c = document.createElement('canvas');
  c.width = 4; c.height = 256;
  const g = c.getContext('2d');
  const stops = {
    day: ['#2f86d0', '#7eb6e6', '#d7e7f4'],
    dusk: ['#1a2344', '#c4623e', '#f0b07a'],
    night: ['#060910', '#121826', '#1b2230'],
    overcast: ['#8b9198', '#c3c7cb', '#d7dadc'],
  }[p.lighting];
  const grd = g.createLinearGradient(0, 0, 0, 256);
  grd.addColorStop(0, stops[0]);
  grd.addColorStop(0.45, stops[1]);
  grd.addColorStop(1, stops[2]);
  g.fillStyle = grd;
  g.fillRect(0, 0, 4, 256);
  if (p.lighting === 'night') {
    g.fillStyle = 'rgba(255,255,255,0.8)';
    for (const [x, y] of [[1, 18], [3, 44], [0, 70], [2, 96], [1, 130], [3, 150], [2, 188], [0, 210]]) {
      g.fillRect(x, y, 1, 1);
    }
  }
  const tex = canvasTexture(c, true);
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  return tex;
}

// ---- renderer -------------------------------------------------------------------------------

const UP = new THREE.Vector3(0, 1, 0);
const unitCylinder = new THREE.CylinderGeometry(1, 1, 1, 14, 1, false);
const unitSphere = new THREE.SphereGeometry(1, 24, 16);

function lathe(profile) {
  return new THREE.LatheGeometry(profile.map(([y, r]) => new THREE.Vector2(r, y)), 16);
}
// The shaft of a capsule: height 1, radius 1 at the joints, slimmer through the middle. Each part
// also gets a round cap at both joints (Body.set), so the drawn part is the capsule (a, b, r) that
// body_parts labels and parts_box bounds, and the trunk, neck and arms meet where they join.
const limbGeo = lathe([[-0.5, 0.04], [-0.40, 0.96], [-0.12, 1.0], [0.18, 0.70], [0.40, 0.96], [0.5, 0.04]]);
const calfGeo = lathe([[-0.5, 0.04], [-0.38, 0.78], [-0.05, 1.0], [0.22, 0.84], [0.40, 0.96], [0.5, 0.04]]);
const torsoGeo = lathe([[-0.5, 0.06], [-0.32, 0.74], [0.05, 0.88], [0.30, 1.0], [0.44, 0.90], [0.5, 0.08]]);

function idMaterial(id) {
  return new THREE.ShaderMaterial({
    uniforms: { idc: { value: new THREE.Vector3(id / 255, 0, 0) } },
    vertexShader: 'void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: 'uniform vec3 idc; void main(){ gl_FragColor = vec4(idc, 1.0); }',
    blending: THREE.NoBlending,
    side: THREE.DoubleSide,
  });
}

// The match body. Python sends the pose; these angles are the same ones meshpose.py builds.
// Object space is Y-up metres, +X his left, +Z the way he faces. Positive bone X swings a limb back.
// A third angle, Y, twists a bone about its length (Root: the hips; spine: the chest; thigh: the foot).
const MESH_CONTACT = new Set(['strike', 'foot', 'thigh', 'chest', 'head', 'hands', 'throw', 'dive', 'shield']);
// Touches taken in stride: the stored pose gives only the arms (meshpose._FEET).
const MESH_FEET = new Set(['strike', 'foot', 'thigh']);
const ARMS = ['upperarm_l', 'lowerarm_l', 'upperarm_r', 'lowerarm_r'];
// Holding the ball (meshpose.HOLD_*): the bend split down the spine, a hand either side of it.
const HOLD_BEND = [['spine_01', 0.45], ['spine_02', 0.4], ['spine_03', 0.15], ['neck_01', -0.3]];
const HOLD_SIDE = 0.14;
// Arm search (meshpose.ARM_*): upper arm X and Z, lower arm X and Z, Z for the left arm.
const ARM_UX = [-2.2, -1.4, -0.7, 0.0];
const ARM_UZ = [-0.4, 0.2, 0.6, 1.0];
const ARM_LX = [-1.0, -0.4, 0.2];
const ARM_LZ = [-0.3, 0.2, 0.6];
const ARM_STEP = [0.3, 0.2, 0.25, 0.2];
const ARM_LIMIT = [[-2.8, 1.0], [-0.8, 1.3], [-1.6, 0.6], [-0.6, 1.0]];
const ARM_PULL = 0.004;
const MOVES4 = [];
for (const a of [-1, 0, 1]) for (const b of [-1, 0, 1]) for (const c of [-1, 0, 1]) for (const d of [-1, 0, 1]) if (a || b || c || d) MOVES4.push([a, b, c, d]);
const THIGH_CAND = [-0.9, -0.55, -0.25, 0.05, 0.35, 0.6];
const THIGH_Z = [-0.6, -0.4, -0.15, 0.0, 0.15, 0.4, 0.6];
const CALF_CAND = [0.05, 0.35, 0.7, 1.1, 1.5];
const LEG_STEP = [0.15, 0.1, 0.17, 0.15];
const HEEL_CAND = [0.0, 0.35, 0.7];
const LEG_LIMIT = [[-1.8, 1.0], [-0.8, 0.8], [0.0, 2.2], [0.0, 0.9]];
const REFINE = 6;
// Every neighbour of the best so far, diagonals included (meshpose._MOVES3, _MOVES2).
const MOVES3 = [];
for (const a of [-1, 0, 1]) for (const b of [-1, 0, 1]) for (const c of [-1, 0, 1]) if (a || b || c) MOVES3.push([a, b, c]);
const MOVES2 = [];
for (const a of [-1, 0, 1]) for (const b of [-1, 0, 1]) if (a || b) MOVES2.push([a, b]);
const PLANT_FOOT = 0.12;
const STRIKE_FOOT = 0.4;
const PLANT_GIVE_UP = 0.45;
const FLOOR_SLACK = 0.02;
const STAND_BLEND = [0.25, 0.9]; // m/s: stand pose blended into the stride (meshpose.STAND_BLEND)
const STRIDE_GROW = [1.6, 2.8]; // m/s: the walk's stride grows to the full stride (meshpose.STRIDE_GROW)
const LEAN_X = [-0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6];
const LEAN_Z = [-0.4, -0.2, 0.0, 0.2, 0.4];
const LEAN_STEP = [0.1, 0.1];
const LEAN_LIMIT = [[-0.9, 0.9], [-0.6, 0.6]];
const LEAN_SHARE = [['spine_01', 0.35], ['spine_02', 0.35], ['neck_01', 0.3]];
const TWIST_SIGN = -1.0;
// The asset's stature (meshpose.ASSET_STATURE_M): a player height_m tall is the asset scaled by
// height_m / ASSET_STATURE_M. And the forehead a header meets the ball with (meshpose.BROW_Y).
const ASSET_STATURE_M = 1.684;
const BROW_Y = 1.63;
const EXTRA = {
  brow: ['head', [0.0, BROW_Y, 0.13]],
  chest: ['spine_03', [0.0, 1.28, 0.14]],
  thigh_top_l: ['thigh_l', [0.14, 0.64, 0.10]],
  thigh_top_r: ['thigh_r', [-0.14, 0.64, 0.10]],
};

let playerPromise = null;
function loadPlayer() {
  if (!playerPromise) {
    playerPromise = fetch('./assets/player.json').then((r) => (r.ok ? r.json() : null)).catch(() => null).then((p) => {
      if (!p) return p;
      // The touch surfaces, skinned wholly to one bone, beside the asset's own markers.
      const index = {};
      p.bones.forEach((b, i) => { index[b.name] = i; });
      for (const [name, [bone, pos]] of Object.entries(EXTRA)) {
        p.markers[name] = { pos, skin: [index[bone], 1.0, -1, 0.0, -1, 0.0, -1, 0.0] };
      }
      p.boneIndex = index;
      return p;
    });
  }
  return playerPromise;
}

function xzy(spec) {
  return Array.isArray(spec) ? [spec[0], spec[1], spec.length > 2 ? spec[2] : 0] : [spec, 0, 0];
}

function rotX(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [1, 0, 0, 0, c, s, 0, -s, c];
}

function rotY(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [c, 0, -s, 0, 1, 0, s, 0, c];
}

function rotZ(a) {
  const c = Math.cos(a), s = Math.sin(a);
  return [c, s, 0, -s, c, 0, 0, 0, 1];
}

function matvec(R, x, y, z) {
  return [
    R[0] * x + R[3] * y + R[6] * z,
    R[1] * x + R[4] * y + R[7] * z,
    R[2] * x + R[5] * y + R[8] * z,
  ];
}

function matmul(a, b) {
  const c0 = matvec(a, b[0], b[1], b[2]);
  const c1 = matvec(a, b[3], b[4], b[5]);
  const c2 = matvec(a, b[6], b[7], b[8]);
  return [c0[0], c0[1], c0[2], c1[0], c1[1], c1[2], c2[0], c2[1], c2[2]];
}

function transpose9(R) {
  return [R[0], R[3], R[6], R[1], R[4], R[7], R[2], R[5], R[8]];
}

function localRot(spec) {
  const [x, z, y] = xzy(spec);
  const rot = matmul(rotZ(z), rotX(x));
  return y ? matmul(rot, rotY(y)) : rot;
}

function mirrorPose(angles) {
  const out = {};
  for (const [key, spec] of Object.entries(angles)) {
    let name = key;
    if (key.endsWith('_l')) name = key.slice(0, -2) + '_r';
    else if (key.endsWith('_r')) name = key.slice(0, -2) + '_l';
    const [x, z, y] = xzy(spec);
    out[name] = Array.isArray(spec) ? (spec.length > 2 ? [x, -z, -y] : [x, -z]) : x;
  }
  return out;
}

function scalePose(angles, factor, keepZ) {
  const out = {};
  for (const [key, spec] of Object.entries(angles)) {
    const [x, z] = xzy(spec);
    out[key] = Array.isArray(spec) ? [x * factor, keepZ ? z : z * factor] : x * factor;
  }
  return out;
}

function copyPose(raw) {
  const out = {};
  for (const [key, spec] of Object.entries(raw)) out[key] = Array.isArray(spec) ? spec.slice() : spec;
  return out;
}

// The arms swing opposite the legs: from the stored walk (elbows nearly straight) to the stored
// run (elbows near a right angle) as armT goes from 0 to 1 (meshpose.gait).
function gaitPose(s, run, walk, armT) {
  const left = (s + 1) / 2, right = (1 - s) / 2;
  const out = {};
  for (const base of ['thigh', 'calf', 'foot']) {
    const lv = run[base + '_l'], rv = run[base + '_r'];
    out[base + '_l'] = lv * left + rv * right;
    out[base + '_r'] = rv * left + lv * right;
  }
  const arms = walk ? blendXZ(walk, run, armT) : run;
  for (const base of ['upperarm', 'lowerarm']) {
    const [lx, lz] = xzy(arms[base + '_l']);
    const [rx, rz] = xzy(arms[base + '_r']);
    out[base + '_l'] = [lx * left + rx * right, lz * left - rz * right];
    out[base + '_r'] = [rx * left + lx * right, rz * left - lz * right];
  }
  if (run.spine_01 != null) out.spine_01 = run.spine_01;
  if (run.spine_02 != null) out.spine_02 = run.spine_02;
  return out;
}

function blendXZ(a, b, t) {
  const out = {};
  for (const key of ARMS) {
    const [ax, az] = xzy(a[key]);
    const [bx, bz] = xzy(b[key]);
    out[key] = [ax + (bx - ax) * t, az + (bz - az) * t];
  }
  return out;
}

function addAngle(angles, bone, dx, dz, dy) {
  const [x, z, y] = xzy(angles[bone] ?? 0);
  angles[bone] = [x + dx, z + dz, y + dy];
}

function poseBones(angles, bones, upto) {
  const n = upto == null ? bones.length : upto + 1;
  const heads = new Array(n);
  const rots = new Array(n);
  for (let i = 0; i < n; i++) {
    const bone = bones[i];
    const local = localRot(angles[bone.name] ?? 0);
    if (bone.parent < 0) {
      rots[i] = matmul(bone.R, local);
      heads[i] = bone.head;
      continue;
    }
    const swing = matmul(rots[bone.parent], transpose9(bones[bone.parent].R));
    const ph = bones[bone.parent].head;
    const swung = matvec(swing, bone.head[0] - ph[0], bone.head[1] - ph[1], bone.head[2] - ph[2]);
    const parent = heads[bone.parent];
    heads[i] = [parent[0] + swung[0], parent[1] + swung[1], parent[2] + swung[2]];
    rots[i] = matmul(swing, matmul(bone.R, local));
  }
  return { heads, rots };
}

function skinOne(pos, skin, posed, bones) {
  let x = 0, y = 0, z = 0, wsum = 0;
  for (let i = 0; i < 8; i += 2) {
    const b = skin[i], w = skin[i + 1];
    if (b < 0 || !w) continue;
    const rh = bones[b].head, R = bones[b].R;
    const lx = pos[0] - rh[0], ly = pos[1] - rh[1], lz = pos[2] - rh[2];
    const l0 = R[0] * lx + R[1] * ly + R[2] * lz;
    const l1 = R[3] * lx + R[4] * ly + R[5] * lz;
    const l2 = R[6] * lx + R[7] * ly + R[8] * lz;
    const P = posed.rots[b], h = posed.heads[b];
    x += w * (P[0] * l0 + P[3] * l1 + P[6] * l2 + h[0]);
    y += w * (P[1] * l0 + P[4] * l1 + P[7] * l2 + h[1]);
    z += w * (P[2] * l0 + P[5] * l1 + P[8] * l2 + h[2]);
    wsum += w;
  }
  return wsum ? [x, y, z] : pos;
}

function pointOf(angles, name, player) {
  const m = player.markers[name];
  let upto = -1;
  for (let i = 0; i < 8; i += 2) if (m.skin[i] > upto) upto = m.skin[i];
  return skinOne(m.pos, m.skin, poseBones(angles, player.bones, upto), player.bones);
}

function toObject(x, y, heading, height, wx, wy, wz = 0, lift = 0) {
  const k = height / ASSET_STATURE_M;
  const hx = Math.cos(heading), hy = Math.sin(heading);
  const dx = (wx - x) / k, dy = (wy - y) / k;
  return [-hy * dx + hx * dy, (wz - lift) / k, hx * dx + hy * dy];
}

function toWorld(x, y, heading, height, p, lift = 0) {
  const k = height / ASSET_STATURE_M;
  const hx = Math.cos(heading), hy = Math.sin(heading);
  return [
    x + k * (-hy * p[0] + hx * p[2]),
    y + k * (hx * p[0] + hy * p[2]),
    k * p[1] + lift,
  ];
}

function clampTo(v, lim) { return v < lim[0] ? lim[0] : v > lim[1] ? lim[1] : v; }

// Thigh and calf angles that put `point` on `target`: a grid finds the basin, halving steps close in.
// On the grass the sole stays level, or rolls onto its toes when left behind (meshpose._leg).
function searchLeg(angles, side, target, foot, twist, point, ground, player, calfFixed, floor) {
  const trial = (params) => {
    const t = Object.assign({}, angles);
    t['thigh_' + side] = [params[0], params[1], twist];
    t['calf_' + side] = params[2];
    t['foot_' + side] = ground ? foot - (params[0] + params[2]) + params[3] : foot;
    const p = pointOf(t, point, player);
    let err = Math.hypot(p[0] - target[0], p[1] - target[1], p[2] - target[2]);
    if (ground) err += 3 * Math.max(0, p[1] - (target[1] + 0.04));
    if (floor != null) err += 3 * Math.max(0, floor - p[1]); // a reaching foot stays above the grass
    return [err, t];
  };
  let best = null;
  const calves = calfFixed != null ? [calfFixed] : CALF_CAND;
  const heels = ground ? HEEL_CAND : [0.0];
  for (const thigh of THIGH_CAND) {
    for (const tz of THIGH_Z) {
      for (const calf of calves) {
        for (const heel of heels) {
          const [err, t] = trial([thigh, tz, calf, heel]);
          if (!best || err < best[0]) best = [err, t, [thigh, tz, calf, heel]];
        }
      }
    }
  }
  const steps = LEG_STEP.slice();
  const moves = (calfFixed != null ? MOVES2 : MOVES3).slice();
  if (ground) moves.push([0, 0, 0, 1], [0, 0, 0, -1]);
  for (let it = 0; it < REFINE; it++) {
    const centre = best[2];
    for (const move of moves) {
      const params = centre.slice();
      for (let i = 0; i < move.length; i++) params[i] = clampTo(centre[i] + move[i] * steps[i], LEG_LIMIT[i]);
      const [err, t] = trial(params);
      if (err < best[0]) best = [err, t, params];
    }
    for (let i = 0; i < 4; i++) steps[i] /= 2;
  }
  return [best[1], best[0]];
}

// Lean the spine and neck so `point` (the chest or the brow) meets `target`.
function searchLean(angles, target, point, player) {
  const trial = (bx, bz) => {
    const t = Object.assign({}, angles);
    for (const [bone, share] of LEAN_SHARE) addAngle(t, bone, bx * share, bz * share, 0);
    const p = pointOf(t, point, player);
    return [Math.hypot(p[0] - target[0], p[1] - target[1], p[2] - target[2]), t];
  };
  let best = null;
  for (const bx of LEAN_X) {
    for (const bz of LEAN_Z) {
      const [err, t] = trial(bx, bz);
      if (!best || err < best[0]) best = [err, t, [bx, bz]];
    }
  }
  const steps = LEAN_STEP.slice();
  for (let it = 0; it < REFINE; it++) {
    const centre = best[2];
    for (const move of MOVES2) {
      const params = [clampTo(centre[0] + move[0] * steps[0], LEAN_LIMIT[0]), clampTo(centre[1] + move[1] * steps[1], LEAN_LIMIT[1])];
      const [err, t] = trial(params[0], params[1]);
      if (err < best[0]) best = [err, t, params];
    }
    steps[0] /= 2; steps[1] /= 2;
  }
  return best[1];
}

function blendPose(base, touch, w) {
  if (w >= 1) return touch;
  const out = Object.assign({}, base);
  const keys = new Set([...Object.keys(base), ...Object.keys(touch)]);
  for (const key of keys) {
    const a = xzy(base[key] ?? 0), b = xzy(touch[key] ?? 0);
    if (a[0] === b[0] && a[1] === b[1] && a[2] === b[2]) continue;
    out[key] = [a[0] + (b[0] - a[0]) * w, a[1] + (b[1] - a[1]) * w, a[2] + (b[2] - a[2]) * w];
  }
  return out;
}

function wrapAngle(a) {
  const t = (a + Math.PI) % (2 * Math.PI);
  return (t < 0 ? t + 2 * Math.PI : t) - Math.PI;
}

// The angles before the feet are placed: the action, the turn, the arms and a held ball (meshpose._upper).
function upperAngles(player, pose, heading, height) {
  const poses = player.poses;
  const action = pose.action || 'stand';
  const speed = pose.speed || 0;
  const lead = pose.lead || 0;
  let angles;
  if (poses[action] && MESH_CONTACT.has(action) && !MESH_FEET.has(action)) {
    angles = copyPose(poses[action]);
    if (action === 'dive') {
      const mag = Math.min(1, Math.abs(pose.dive || 0));
      if ((pose.dive || 0) < 0) angles = mirrorPose(angles);
      angles = scalePose(angles, mag > 0.35 ? mag : 0.35, false);
    }
  } else if (speed < STAND_BLEND[0] || (action === 'stand' && speed < player.standSpeed)) {
    angles = copyPose(poses.stand);
  } else {
    // A strike or a touch with the foot or thigh is taken in stride.
    const full = player.fullStrideSpeed;
    const armT = action === 'run' ? 1 : Math.min(Math.max((speed - full) / (player.armRunSpeed - full), 0), 1);
    angles = gaitPose(Math.sin(pose.phase || 0), poses.run, poses.walk, armT);
    if (action !== 'run' && speed < STRIDE_GROW[1]) {
      // A walk's short stride grows into the full one through a jog (meshpose.STRIDE_GROW).
      const t = Math.min(Math.max((speed - STRIDE_GROW[0]) / (STRIDE_GROW[1] - STRIDE_GROW[0]), 0), 1);
      const legs = {};
      for (const [key, v] of Object.entries(angles)) if (!ARMS.includes(key)) legs[key] = v;
      Object.assign(angles, scalePose(legs, player.walkScale + (1 - player.walkScale) * t, true));
    }
    // Setting off and pulling up, the stride grows out of the stance and back into it.
    if (action !== 'run' && speed < STAND_BLEND[1]) {
      angles = blendPose(copyPose(poses.stand), angles, (speed - STAND_BLEND[0]) / (STAND_BLEND[1] - STAND_BLEND[0]));
    }
  }
  if (lead) {
    // The hips lead a turn and the chest follows: Root turns the hips and legs, the lower spine
    // turns the chest back to where the engine has it face.
    addAngle(angles, 'Root', 0, lead, 0);
    addAngle(angles, 'spine_01', 0, 0, -lead * 0.5);
    addAngle(angles, 'spine_02', 0, 0, -lead * 0.5);
  }
  const touch = pose.touch;
  if (touch && touch.w > 0 && MESH_FEET.has(touch.part)) {
    // The arms balance the kick or the touch (stored for a right-footed touch).
    let arms = copyPose(poses[touch.part]);
    if ((touch.side || 'r') === 'l') arms = mirrorPose(arms);
    const target = Object.assign({}, angles);
    for (const key of ARMS) target[key] = arms[key];
    angles = blendPose(angles, target, touch.w);
  }
  const hold = pose.hold;
  if (hold && hold.w > 0) angles = blendPose(angles, holdPose(player, angles, pose, hold, heading, height), hold.w);
  return angles;
}

function anglesFor(player, pose, heading, height) {
  const x = pose.x, y = pose.y;
  const lead = pose.lead || 0;
  const lift = pose.lift || 0;
  let angles = upperAngles(player, pose, heading, height);
  // scene.py plants a foot only when the pose stands on it.
  for (const side of ['l', 'r']) {
    const plant = pose['plant_' + side];
    if (!plant) continue;
    const twist = plant.length > 2 && plant[2] != null ? TWIST_SIGN * wrapAngle(plant[2] - heading - lead) : 0;
    const pz = plant.length > 3 ? plant[3] : 0;
    const target = toObject(x, y, heading, height, plant[0], plant[1], pz, lift);
    let [planted, err] = searchLeg(angles, side, target, PLANT_FOOT, twist, 'foot_' + side, true, player);
    if (err > PLANT_GIVE_UP && lift < 0) {
      // Lowered, an unreachable foot reaches toward its plant above the grass (meshpose.pose_angles).
      planted = searchLeg(angles, side, target, PLANT_FOOT, twist, 'foot_' + side, false, player, null, -lift / (height / ASSET_STATURE_M))[0];
      err = 0;
    }
    // A stride's plant comes and goes with a weight (scene.PLANT_EASE_FRAMES).
    if (err <= PLANT_GIVE_UP) angles = blendPose(angles, planted, plant.length > 4 && plant[4] != null ? plant[4] : 1);
  }
  const touch = pose.touch;
  if (touch && touch.w > 0) {
    const side = touch.side || 'r';
    const target = toObject(x, y, heading, height, touch.at[0], touch.at[1], touch.at[2], lift);
    let reached;
    if (touch.part === 'foot' || touch.part === 'strike') {
      const foot = touch.part === 'strike' ? STRIKE_FOOT : PLANT_FOOT;
      const floor = -lift / (height / ASSET_STATURE_M);
      reached = searchLeg(angles, side, target, foot, 0, 'foot_' + side, false, player, null, floor)[0];
      angles = blendPose(angles, reached, touch.w);
      // A blend that dips the foot under the grass puts it back on it (meshpose.pose_angles).
      const p = pointOf(angles, 'foot_' + side, player);
      if (p[1] < floor - FLOOR_SLACK) angles = searchLeg(angles, side, [p[0], floor, p[2]], foot, 0, 'foot_' + side, false, player, null, floor)[0];
      return angles;
    } else if (touch.part === 'thigh') {
      reached = searchLeg(angles, side, target, 0.25, 0, 'thigh_top_' + side, false, player, 1.5)[0];
    } else {
      reached = searchLean(angles, target, touch.part === 'head' ? 'brow' : 'chest', player);
    }
    angles = blendPose(angles, reached, touch.w);
  }
  return angles;
}

// Bend over a held ball and put a hand either side of it (meshpose._hold).
function holdPose(player, angles, pose, hold, heading, height) {
  let out = Object.assign({}, angles);
  const bend = hold.bend || 0;
  for (const [bone, share] of HOLD_BEND) addAngle(out, bone, bend * share, 0, 0);
  const centre = toObject(pose.x, pose.y, heading, height, hold.at[0], hold.at[1], hold.at[2], pose.lift || 0);
  const k = height / ASSET_STATURE_M;
  const idx = player.boneIndex;
  const girdle = poseBones(out, player.bones, Math.max(idx.clavicle_l, idx.clavicle_r));
  for (const [side, sign] of [['l', 1], ['r', -1]]) {
    out = searchArm(player, out, side, sign, [centre[0] + sign * HOLD_SIDE / k, centre[1], centre[2]], girdle);
  }
  return out;
}

// The hand marker for these arm angles, from the posed shoulder girdle (meshpose._arm_hand).
function armHand(player, angles, side, girdle) {
  const bones = player.bones, idx = player.boneIndex;
  const heads = girdle.heads.slice(), rots = girdle.rots.slice();
  for (const name of ['upperarm_' + side, 'lowerarm_' + side, 'hand_' + side]) {
    const b = idx[name], bone = bones[b], parent = bone.parent;
    const swing = matmul(rots[parent], transpose9(bones[parent].R));
    const ph = bones[parent].head;
    const swung = matvec(swing, bone.head[0] - ph[0], bone.head[1] - ph[1], bone.head[2] - ph[2]);
    heads[b] = [heads[parent][0] + swung[0], heads[parent][1] + swung[1], heads[parent][2] + swung[2]];
    rots[b] = matmul(swing, matmul(bone.R, localRot(angles[name] ?? 0)));
  }
  const m = player.markers['hand_' + side];
  return skinOne(m.pos, m.skin, { heads, rots }, bones);
}

// Upper and lower arm angles that put the hand on `target` (meshpose._arm).
function searchArm(player, angles, side, sign, target, girdle) {
  const stand = player.poses.stand;
  const rest = [...xzy(stand.upperarm_l).slice(0, 2), ...xzy(stand.lowerarm_l).slice(0, 2)];
  const trial = (params) => {
    const t = Object.assign({}, angles);
    t['upperarm_' + side] = [params[0], params[1] * sign];
    t['lowerarm_' + side] = [params[2], params[3] * sign];
    const p = armHand(player, t, side, girdle);
    let err = Math.hypot(p[0] - target[0], p[1] - target[1], p[2] - target[2]);
    let pull = 0;
    for (let j = 0; j < 4; j++) pull += Math.abs(params[j] - rest[j]);
    err += ARM_PULL * pull;
    return [err, t];
  };
  let best = null;
  for (const ux of ARM_UX) for (const uz of ARM_UZ) for (const lx of ARM_LX) for (const lz of ARM_LZ) {
    const [err, t] = trial([ux, uz, lx, lz]);
    if (!best || err < best[0]) best = [err, t, [ux, uz, lx, lz]];
  }
  const steps = ARM_STEP.slice();
  for (let it = 0; it < REFINE; it++) {
    const centre = best[2];
    for (const move of MOVES4) {
      const params = centre.map((c, j) => clampTo(c + move[j] * steps[j], ARM_LIMIT[j]));
      const [err, t] = trial(params);
      if (err < best[0]) best = [err, t, params];
    }
    for (let j = 0; j < 4; j++) steps[j] /= 2;
  }
  return best[1];
}

function bindPart(part, bones) {
  const n = part.pos.length / 3;
  const bi = new Int16Array(n * 4);
  const bw = new Float32Array(n * 4);
  const locals = new Float32Array(n * 12);
  for (let i = 0; i < n; i++) {
    const x = part.pos[i * 3], y = part.pos[i * 3 + 1], z = part.pos[i * 3 + 2];
    for (let k = 0; k < 4; k++) {
      const b = part.skin[i * 8 + k * 2];
      const w = part.skin[i * 8 + k * 2 + 1];
      bi[i * 4 + k] = b;
      bw[i * 4 + k] = w;
      if (b < 0 || !w) continue;
      const rh = bones[b].head, R = bones[b].R;
      const lx = x - rh[0], ly = y - rh[1], lz = z - rh[2];
      const o = (i * 4 + k) * 3;
      locals[o] = R[0] * lx + R[1] * ly + R[2] * lz;
      locals[o + 1] = R[3] * lx + R[4] * ly + R[5] * lz;
      locals[o + 2] = R[6] * lx + R[7] * ly + R[8] * lz;
    }
  }
  return { bi, bw, locals, n };
}

// Eight pixels of head. The cap sits inside the scalp, so it grows out by a few
// centimetres. A scale would turn that shell into a fin. Build widens the
// shoulders. Feet stay put so the boot capsules still cover them.
const HAIR_GROW = { short: 0.035, crown: 0.07 };

function shapeOutline(array, part, build, style) {
  const grow = part === 'hair' ? (HAIR_GROW[style] || 0) : 0;
  const b = build || 1;
  for (let i = 0; i < array.length; i += 3) {
    let x = array[i];
    let y = array[i + 1];
    let z = array[i + 2];
    if (b !== 1) {
      const t = y <= 0.55 ? 0 : y >= 1.3 ? 1 : (y - 0.55) / 0.75;
      x *= 1 + (b - 1) * t;
    }
    if (grow) {
      const dx = x, dy = y - 1.58, dz = z - 0.05;
      const len = Math.hypot(dx, dy, dz) || 1;
      x += dx / len * grow;
      y += dy / len * grow;
      z += dz / len * grow;
    }
    array[i] = x;
    array[i + 1] = y;
    array[i + 2] = z;
  }
}

function skinPositions(bind, posed, out) {
  const { bi, bw, locals, n } = bind;
  for (let i = 0; i < n; i++) {
    let x = 0, y = 0, z = 0;
    for (let k = 0; k < 4; k++) {
      const w = bw[i * 4 + k];
      if (!w) continue;
      const R = posed.rots[bi[i * 4 + k]];
      const h = posed.heads[bi[i * 4 + k]];
      const o = (i * 4 + k) * 3;
      const lx = locals[o], ly = locals[o + 1], lz = locals[o + 2];
      x += w * (R[0] * lx + R[3] * ly + R[6] * lz + h[0]);
      y += w * (R[1] * lx + R[4] * ly + R[7] * lz + h[1]);
      z += w * (R[2] * lx + R[5] * ly + R[8] * lz + h[2]);
    }
    out[i * 3] = x; out[i * 3 + 1] = y; out[i * 3 + 2] = z;
  }
}

const ROUGHNESS = { shirt: 0.82, shorts: 0.84, socks: 0.78, skin: 0.55, hair: 0.7, boots: 0.6, ball: 0.38, eyes: 0.35 };
const METALNESS = { boots: 0.04, ball: 0.05 };

class Body {
  // One labelled object: a player or the ball, built from capsules and spheres.
  constructor(id, spec, scene, player) {
    this.id = id;
    this.group = new THREE.Group();
    this.heightM = spec.height_m || 1.84;
    this.build = spec.build ?? 1;
    this.hairStyle = spec.hair_style || 'short';
    this.player = player;
    const colors = spec.colors;
    this.number = spec.number ?? null;
    this.pattern = spec.pattern || 'solid';
    this.materials = {};
    this.kit = null;
    const trim = colors.shorts && colors.shirt && colors.shorts.toLowerCase() !== colors.shirt.toLowerCase()
      ? colors.shorts : '#f2f2f2';
    for (const [slot, hex] of Object.entries(colors)) {
      if (slot === 'shirt') {
        this.materials.shirt = kitMaterial(id, 'shirt', hex, trim, this.pattern, this.number);
        this.kit = this.materials.shirt.userData.kit;
      } else if (slot === 'socks') {
        this.materials.socks = kitMaterial(id, 'socks', hex, '#f4f4f4', 'bands', null);
      } else if (slot === 'ball') {
        this.materials.ball = ballMaterial();
      } else {
        this.materials[slot] = new THREE.MeshStandardMaterial({
          color: hex, roughness: ROUGHNESS[slot] ?? 0.75, metalness: METALNESS[slot] ?? 0,
        });
      }
    }
    for (const [slot, mat] of Object.entries(this.materials)) {
      const bias = { shorts: 2, shirt: 1, socks: -1, skin: -2, boots: -3, hair: -4 }[slot] ?? 0;
      mat.polygonOffset = true;
      mat.polygonOffsetFactor = bias;
      mat.polygonOffsetUnits = bias;
    }
    this.idMat = idMaterial(id);
    this.pool = [];
    this.used = 0;
    this.skin = null;
    if (player && colors.shirt) this.buildSkin(colors);
    scene.add(this.group);
  }

  buildSkin(colors) {
    const slotMat = {
      body: this.materials.skin,
      jersey: this.materials.shirt,
      shorts: this.materials.shorts,
      socks: this.materials.socks,
      shoes: this.materials.boots,
      hair: this.materials.hair,
      brows: this.materials.hair,
    };
    this.eyeMat = new THREE.MeshStandardMaterial({ color: 0xf3f1ec, roughness: 0.35 });
    slotMat.eyes = this.eyeMat;
    this.skin = [];
    for (const name of this.player.partOrder) {
      const part = this.player.parts[name];
      const mat = slotMat[name];
      if (!part || !mat) continue;
      mat.side = THREE.DoubleSide;
      if (name !== 'body' && name !== 'eyes') {
        mat.polygonOffset = true;
        mat.polygonOffsetFactor = -2;
        mat.polygonOffsetUnits = -2;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(part.pos), 3));
      geo.setIndex(part.idx);
      geo.computeVertexNormals();
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      mesh.receiveShadow = false;
      mesh.frustumCulled = false;
      mesh.userData.mat = mat;
      mesh.userData.part = name;
      mesh.userData.bind = bindPart(part, this.player.bones);
      this.group.add(mesh);
      this.skin.push(mesh);
    }
    this.used = this.skin.length;
  }

  materialFor(slot) {
    return this.materials[slot];
  }

  mesh(geo, slot, name) {
    let m = this.pool[this.used];
    if (!m || m.geometry !== geo) {
      m = new THREE.Mesh(geo, this.materialFor(slot, name));
      m.castShadow = true;
      m.matrixAutoUpdate = false;
      if (this.pool[this.used]) this.group.remove(this.pool[this.used]);
      this.pool[this.used] = m;
      this.group.add(m);
    }
    m.material = this.materialFor(slot);
    m.userData.slot = slot;
    m.userData.part = name;
    m.visible = true;
    this.used++;
    return m;
  }

  set(parts, heading, pose) {
    if (this.skin) {
      this.poseMesh(parts, heading, pose || { action: 'stand', phase: 0, speed: 0, reach: 0, dive: 0 });
      return;
    }
    this.used = 0;
    const face = heading || 0;
    const fx = Math.cos(face), fy = Math.sin(face);
    const left = new THREE.Vector3(-fy, fx, 0);
    if (this.kit && heading != null && parts.length) {
      const torso = parts.find((p) => p.n === 'torso') || parts[0];
      this.kit.uOrigin.value.set(torso.a[0], torso.a[1]);
      this.kit.uFwd.value.set(fx, fy);
      this.kit.uLeft.value.set(-fy, fx);
      if (this.materials.socks) {
        const sock = this.materials.socks.userData.kit;
        sock.uOrigin.value.copy(this.kit.uOrigin.value);
        sock.uFwd.value.copy(this.kit.uFwd.value);
        sock.uLeft.value.copy(this.kit.uLeft.value);
      }
    }
    const a = new THREE.Vector3(), b = new THREE.Vector3(), dir = new THREE.Vector3(), q = new THREE.Quaternion();
    const axis = new THREE.Vector3(), xAxis = new THREE.Vector3(), zAxis = new THREE.Vector3();
    const basis = new THREE.Matrix4();
    // Cross-section scale. The wide axis stays at 1 so the mesh does not leave the labelled radius.
    const chest = { torso: [1.0, 0.72], hips: [1.0, 0.82], shoulders: [1.0, 0.82] };
    for (const p of parts) {
      a.fromArray(p.a);
      if (!p.b) {
        q.identity();
        if (p.spin) {
          axis.set(p.spin[0], p.spin[1], 0);
          if (axis.lengthSq() > 1e-8) q.setFromAxisAngle(axis.normalize(), p.spin[2]);
        }
        const s = this.mesh(unitSphere, p.c, p.n);
        const cap = p.n === 'hair' ? [p.r * 1.08, p.r * 1.08, p.r * 0.55] : [p.r, p.r, p.r];
        s.matrix.compose(a, q, new THREE.Vector3(cap[0], cap[1], cap[2]));
        continue;
      }
      b.fromArray(p.b);
      dir.subVectors(b, a);
      const len = dir.length();
      if (len < 1e-6) continue;
      const yAxis = dir.multiplyScalar(1 / len);
      xAxis.copy(left).addScaledVector(yAxis, -left.dot(yAxis));
      if (xAxis.lengthSq() < 1e-6) {
        const ref = Math.abs(yAxis.z) > 0.85 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1);
        xAxis.crossVectors(ref, yAxis);
      }
      xAxis.normalize();
      zAxis.crossVectors(xAxis, yAxis).normalize();
      basis.makeBasis(xAxis, yAxis, zAxis);
      q.setFromRotationMatrix(basis);
      const [wx, dz] = chest[p.n] || (p.n.startsWith('boot') ? [1, 0.62] : [1, 1]);
      const geo = p.n === 'shoulders' ? unitCylinder : p.n === 'torso' || p.n === 'hips' ? torsoGeo : p.n.startsWith('shin') ? calfGeo : limbGeo;
      const limb = this.mesh(geo, p.c, p.n);
      limb.matrix.compose(a.clone().addScaledVector(yAxis, len * 0.5), q, new THREE.Vector3(p.r * wx, len, p.r * dz));
      const cap = new THREE.Vector3(p.r * wx, p.r, p.r * dz);
      this.mesh(unitSphere, p.c, p.n).matrix.compose(a, q, cap);
      this.mesh(unitSphere, p.c, p.n).matrix.compose(b, q, cap);
    }
    for (let i = this.used; i < this.pool.length; i++) this.pool[i].visible = false;
    this.group.visible = this.used > 0;
  }

  poseMesh(parts, heading, pose) {
    const face = heading || 0;
    const fx = Math.cos(face), fy = Math.sin(face);
    const hl = parts.find((p) => p.n === 'thigh_l');
    const hr = parts.find((p) => p.n === 'thigh_r');
    const x = pose.x != null ? pose.x : (hl && hr ? (hl.a[0] + hr.a[0]) / 2 : parts[0].a[0]);
    const y = pose.y != null ? pose.y : (hl && hr ? (hl.a[1] + hr.a[1]) / 2 : parts[0].a[1]);
    if (this.kit) {
      this.kit.uOrigin.value.set(x, y);
      this.kit.uFwd.value.set(fx, fy);
      this.kit.uLeft.value.set(-fy, fx);
      if (this.materials.socks) {
        const sock = this.materials.socks.userData.kit;
        sock.uOrigin.value.copy(this.kit.uOrigin.value);
        sock.uFwd.value.copy(this.kit.uFwd.value);
        sock.uLeft.value.copy(this.kit.uLeft.value);
      }
    }
    const k = this.heightM / ASSET_STATURE_M;
    this.group.position.set(x, y, pose.lift || 0);
    this.group.scale.set(k, k, k);
    this.group.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(-fy, fx, 0), new THREE.Vector3(0, 0, 1), new THREE.Vector3(fx, fy, 0),
    ));
    const placed = Object.assign({}, pose, { x, y });
    const angles = anglesFor(this.player, placed, face, this.heightM);
    const posed = poseBones(angles, this.player.bones);
    const build = pose.build != null ? pose.build : this.build;
    const style = pose.hair_style || this.hairStyle;
    for (const mesh of this.skin) {
      const attr = mesh.geometry.attributes.position;
      skinPositions(mesh.userData.bind, posed, attr.array);
      const part = mesh.userData.part;
      const bald = style === 'bald' && part === 'hair';
      mesh.visible = !bald;
      if (!bald) shapeOutline(attr.array, part, build, style);
      attr.needsUpdate = true;
      mesh.geometry.computeVertexNormals();
    }
    this.used = this.skin.length;
    this.group.visible = true;
    this._markers = { angles, x, y, face };
  }

  markerWorld(pose, heading) {
    if (!this.skin) return null;
    const face = heading || 0;
    const x = pose && pose.x != null ? pose.x : 0;
    const y = pose && pose.y != null ? pose.y : 0;
    const angles = anglesFor(this.player, Object.assign({ action: 'stand' }, pose, { x, y }), face, this.heightM);
    const posed = poseBones(angles, this.player.bones);
    const out = {};
    for (const [name, marker] of Object.entries(this.player.markers)) {
      out[name] = toWorld(x, y, face, this.heightM, skinOne(marker.pos, marker.skin, posed, this.player.bones), (pose && pose.lift) || 0);
    }
    return out;
  }

  useId(on) {
    if (this.skin) {
      for (const m of this.skin) m.material = on ? this.idMat : m.userData.mat;
      return;
    }
    for (let i = 0; i < this.used; i++) {
      const m = this.pool[i];
      m.material = on ? this.idMat : this.materialFor(m.userData.slot);
    }
  }
}

class BroadcastRenderer {
  async init(cfg) {
    const surfaces = await loadGrass();
    const player = await loadPlayer();
    const grass = surfaces.color;
    const grassN = surfaces.normal;
    const p = cfg.params;
    this.cfg = cfg;
    this.p = p;
    this.W = p.width; this.H = p.height;
    const rand = rng(cfg.seed);

    const canvas = document.createElement('canvas');
    canvas.width = this.W; canvas.height = this.H;
    document.body.appendChild(canvas);
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, preserveDrawingBuffer: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(this.W, this.H, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, this.W / this.H, 0.5, 2000);

    // ground: textured pitch over a darker surround. Rain lowers roughness so the sun sheens, and the albedo is darkened in the texture.
    const wet = p.weather === 'rain';
    // Asphalt around the pitch. A warm mid grey reads as a blank wall from the far stand.
    const surround = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshStandardMaterial({
      color: new THREE.Color().setHSL(0.0, 0.0, wet ? 0.02 : 0.025),
      roughness: 0.96,
    }));
    surround.position.set(52.5, 34, -0.02);
    surround.receiveShadow = true;
    const pitchTex = pitchTexture(p, rand);
    pitchTex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const maxAniso = this.renderer.capabilities.getMaxAnisotropy();
    if (grass) grass.anisotropy = maxAniso;
    if (grassN) grassN.anisotropy = maxAniso;
    const pitch = new THREE.Mesh(new THREE.PlaneGeometry(GROUND.x1 - GROUND.x0, GROUND.y1 - GROUND.y0), decoratePitch(new THREE.MeshStandardMaterial({
      map: pitchTex,
      roughness: wet ? 0.36 : 0.72,
      metalness: wet ? 0.06 : 0.0,
    }), wet, grass, grassN, p));
    pitch.position.set((GROUND.x0 + GROUND.x1) / 2, (GROUND.y0 + GROUND.y1) / 2, 0);
    pitch.receiveShadow = true;
    const sky = new THREE.Mesh(new THREE.SphereGeometry(480, 28, 18), new THREE.MeshBasicMaterial({
      map: skyTexture(p), side: THREE.BackSide, depthWrite: false,
    }));
    sky.position.set(52.5, 34, 0);
    sky.renderOrder = -1;
    sky.frustumCulled = false;
    this.decor = [sky, surround, pitch];

    // Two tiers on every side, on clad structure, inside a clad back wall under a roof ring, so the
    // bowl is closed: no flat black wall and no sky between the stands. The near stand's front lip
    // stays at y=-46, past the furthest gantry. Stands, roofs and towers are decor: the id pass
    // ignores them.
    const cladding = claddingTexture(p, rand);
    cladding.anisotropy = maxAniso;
    const shell = new THREE.MeshStandardMaterial({ map: cladding, roughness: 0.9, side: THREE.DoubleSide });
    const span = (a, b) => Math.max(1, Math.round(Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]) / 32));
    const clad = (p0, p1, p2, p3) => quad(p0, p1, p2, p3, shell, [span(p0, p1), Math.max(1, Math.round(Math.hypot(p3[0] - p0[0], p3[1] - p0[1], p3[2] - p0[2]) / 8))]);
    this.decor.push(
      clad([-36, 78, 0.2], [141, 78, 0.2], [141, 114, 18], [-36, 114, 18]),
      clad([141, -48, 0.2], [-36, -48, 0.2], [-36, -80, 18], [141, -80, 18]),
      clad([-16, 112, 0.8], [-16, -60, 0.8], [-40, -60, 14], [-40, 112, 14]),
      clad([121, -60, 0.8], [121, 112, 0.8], [145, 112, 14], [145, -60, 14]),
    );
    tier(this.decor, p, rand, [[-4, 74.3, 2.0], [114, 74.3, 2.0], [114, 91, 9.2], [-4, 91, 9.2]], maxAniso);
    tier(this.decor, p, rand, [[-4, 95.5, 10.6], [114, 95.5, 10.6], [114, 112, 19.5], [-4, 112, 19.5]], maxAniso);
    tier(this.decor, p, rand, [[114, -46, 1.6], [-4, -46, 1.6], [-4, -60, 8.4], [114, -60, 8.4]], maxAniso);
    tier(this.decor, p, rand, [[114, -64, 9.6], [-4, -64, 9.6], [-4, -78, 17.5], [114, -78, 17.5]], maxAniso);
    tier(this.decor, p, rand, [[-11, 70, 1.4], [-11, 4, 1.4], [-34, 4, 12], [-34, 70, 12]], maxAniso);
    tier(this.decor, p, rand, [[116, 4, 1.4], [116, 70, 1.4], [139, 70, 12], [139, 4, 12]], maxAniso);
    const boardTex = boardTexture(p, rand);
    boardTex.anisotropy = maxAniso;
    const boardsLit = p.lighting === 'night' || p.lighting === 'dusk';
    const boardMat = new THREE.MeshStandardMaterial({
      map: boardTex,
      roughness: 0.5,
      emissive: new THREE.Color(boardsLit ? 0xffffff : 0x444444),
      emissiveMap: boardTex,
      emissiveIntensity: boardsLit ? 0.85 : 0.45,
      side: THREE.FrontSide,
    });
    // Every board is printed on the side that faces the pitch, so it reads left to right from
    // anywhere on it, from the gantry and from the reverse angle. Seen from behind, a board is its
    // plain back, never its print mirrored.
    const boards = [
      quad([-2, 71.5, 0], [107, 71.5, 0], [107, 71.5, 1.8], [-2, 71.5, 1.8], boardMat),
      // The gantry is behind the near boards: they have no back, so it sees through to the pitch.
      quad([107, -1.6, 0], [-2, -1.6, 0], [-2, -1.6, 1.8], [107, -1.6, 1.8], boardMat),
      quad([-4, 2, 0], [-4, 66, 0], [-4, 66, 0.9], [-4, 2, 0.9], boardMat),
      quad([109, 66, 0], [109, 2, 0], [109, 2, 0.9], [109, 66, 0.9], boardMat),
    ];
    const backMat = new THREE.MeshStandardMaterial({ color: 0x24272d, roughness: 0.8 });
    const backs = [0, 2, 3].map((i) => {
      const a = boards[i].geometry.attributes.position.array;
      const c = (j) => [a[3 * j], a[3 * j + 1], a[3 * j + 2]];
      // The same corners the other way round: the face turned away from the pitch.
      return quad(c(1), c(0), c(5), c(2), backMat);
    });
    // Towers sit with the far stand, behind the play. Like the stands they are decor: the id pass ignores them.
    const towerMat = new THREE.MeshStandardMaterial({ color: 0x2c3138, roughness: 0.62, metalness: 0.35 });
    const lampMat = new THREE.MeshStandardMaterial({
      color: 0xf4f1ea,
      emissive: new THREE.Color(p.lighting === 'night' ? 0xfff3d2 : p.lighting === 'dusk' ? 0xffe0b0 : 0x000000),
      emissiveIntensity: p.lighting === 'night' ? 2.4 : 0.6,
      roughness: 0.35,
    });
    const towers = [];
    for (const [x, y] of [[-6, 82], [111, 82], [28, 92], [77, 92], [12, -58], [93, -58]]) {
      const pole = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.42, 30), towerMat);
      pole.position.set(x, y, 15);
      const gantry = new THREE.Mesh(new THREE.BoxGeometry(7.2, 0.9, 0.28), towerMat);
      gantry.position.set(x, y, 29.6);
      towers.push(pole, gantry);
      for (const dx of [-2.4, -0.8, 0.8, 2.4]) {
        const lamp = new THREE.Mesh(new THREE.BoxGeometry(1.2, 0.55, 0.22), lampMat);
        lamp.position.set(x + dx, y, 29.85);
        towers.push(lamp);
      }
    }
    this.shadows = new THREE.InstancedMesh(
      new THREE.CircleGeometry(1, 16),
      new THREE.MeshBasicMaterial({
        color: 0x071008, transparent: true, opacity: 0.16, depthWrite: false,
        polygonOffset: true, polygonOffsetFactor: -4, polygonOffsetUnits: -4,
      }),
      22,
    );
    this.shadows.renderOrder = 2;
    this.shadows.frustumCulled = false;
    this.boards = boards;
    this.decor.push(...boards, ...backs, ...towers, this.shadows);
    // Built after the boards and the towers, so their seeded draws (and look) are what they were.
    // The ends get an upper tier like the sides, and each corner a wedge of seats from the end
    // stand round to the side stand, lower and upper.
    tier(this.decor, p, rand, [[-36.5, 70, 13.5], [-36.5, 4, 13.5], [-52, 4, 22], [-52, 70, 22]], maxAniso);
    tier(this.decor, p, rand, [[141.5, 4, 13.5], [141.5, 70, 13.5], [157, 70, 22], [157, 4, 22]], maxAniso);
    for (const [ex, sx, dir] of [[-11, -4, -1], [116, 114, 1]]) {
      for (const [ey, sy, out] of [[70, 74.3, 1], [4, -46, -1]]) {
        const lo = out > 0 ? [[ex, ey, 1.4], [sx, sy, 2.0], [sx, sy + out * 16.7, 9.2], [ex + dir * 23, ey, 12]]
          : [[ex, ey, 1.4], [sx, sy, 1.6], [sx, sy + out * 14, 8.4], [ex + dir * 23, ey, 12]];
        const hi = out > 0 ? [[ex + dir * 25.5, ey, 13.5], [sx, sy + out * 21.2, 10.6], [sx, sy + out * 37.7, 19.5], [ex + dir * 41, ey, 22]]
          : [[ex + dir * 25.5, ey, 13.5], [sx, sy + out * 18, 9.6], [sx, sy + out * 32, 17.5], [ex + dir * 41, ey, 22]];
        // Corners go round anticlockwise seen from the pitch, so the seats face it.
        const flip = dir * out > 0;
        for (const c of [lo, hi]) {
          const edge = Math.max(Math.hypot(c[1][0] - c[0][0], c[1][1] - c[0][1]), Math.hypot(c[2][0] - c[3][0], c[2][1] - c[3][1]));
          tier(this.decor, p, rand, flip ? [c[1], c[0], c[3], c[2]] : c, maxAniso, edge / 118);
        }
      }
    }
    // The back wall all round, then the roof ring over the upper tiers, sloping down to its front edge.
    const W = { x0: -60, x1: 165, y0: -86, y1: 120, z: 26, eave: 24, depth: 16 };
    this.decor.push(
      clad([W.x0, W.y1, 0], [W.x1, W.y1, 0], [W.x1, W.y1, W.z], [W.x0, W.y1, W.z]),
      clad([W.x1, W.y0, 0], [W.x0, W.y0, 0], [W.x0, W.y0, W.z], [W.x1, W.y0, W.z]),
      clad([W.x0, W.y0, 0], [W.x0, W.y1, 0], [W.x0, W.y1, W.z], [W.x0, W.y0, W.z]),
      clad([W.x1, W.y1, 0], [W.x1, W.y0, 0], [W.x1, W.y0, W.z], [W.x1, W.y1, W.z]),
    );
    const roofTex = roofTexture();
    roofTex.anisotropy = maxAniso;
    const roofMat = new THREE.MeshStandardMaterial({ map: roofTex, roughness: 0.7, metalness: 0.2, side: THREE.DoubleSide });
    const roof = (p0, p1, p2, p3) => quad(p0, p1, p2, p3, roofMat, [span(p0, p1) * 32 / 24, 1]);
    const d = W.depth;
    this.decor.push(
      roof([W.x0, W.y1 - d, W.eave], [W.x1, W.y1 - d, W.eave], [W.x1, W.y1, W.z], [W.x0, W.y1, W.z]),
      roof([W.x1, W.y0 + d, W.eave], [W.x0, W.y0 + d, W.eave], [W.x0, W.y0, W.z], [W.x1, W.y0, W.z]),
      roof([W.x0 + d, W.y0, W.eave], [W.x0 + d, W.y1, W.eave], [W.x0, W.y1, W.z], [W.x0, W.y0, W.z]),
      roof([W.x1 - d, W.y1, W.eave], [W.x1 - d, W.y0, W.eave], [W.x1, W.y0, W.z], [W.x1, W.y1, W.z]),
    );
    // A fascia along each roof's front edge.
    const fascia = new THREE.MeshStandardMaterial({ color: 0xd9dde2, roughness: 0.5, metalness: 0.3, side: THREE.DoubleSide });
    this.decor.push(
      quad([W.x0, W.y1 - d, W.eave - 1.2], [W.x1, W.y1 - d, W.eave - 1.2], [W.x1, W.y1 - d, W.eave], [W.x0, W.y1 - d, W.eave], fascia),
      quad([W.x1, W.y0 + d, W.eave - 1.2], [W.x0, W.y0 + d, W.eave - 1.2], [W.x0, W.y0 + d, W.eave], [W.x1, W.y0 + d, W.eave], fascia),
      quad([W.x0 + d, W.y0, W.eave - 1.2], [W.x0 + d, W.y1, W.eave - 1.2], [W.x0 + d, W.y1, W.eave], [W.x0 + d, W.y0, W.eave], fascia),
      quad([W.x1 - d, W.y1, W.eave - 1.2], [W.x1 - d, W.y0, W.eave - 1.2], [W.x1 - d, W.y0, W.eave], [W.x1 - d, W.y1, W.eave], fascia),
    );

    // goals: posts and crossbar are occluders in the id pass; the net is decor
    this.posts = [];
    const white = new THREE.MeshStandardMaterial({ color: 0xf4f4f4, roughness: 0.4, metalness: 0.08 });
    const postId = idMaterial(POST_ID);
    const bar = (a, b, r) => {
      const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b), dir = B.clone().sub(A);
      const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, dir.length(), 12), white);
      m.position.copy(A).addScaledVector(dir, 0.5);
      m.quaternion.setFromUnitVectors(UP, dir.normalize());
      m.castShadow = true;
      m.userData.idMat = postId;
      m.userData.mat = white;
      return m;
    };
    const netMat = new THREE.MeshStandardMaterial({ map: netTexture(), transparent: true, opacity: 0.72, roughness: 0.85, side: THREE.DoubleSide, depthWrite: true, alphaTest: 0.15 });
    this.nets = [];
    for (const [gx, s, side] of [[0, -1, 0], [105, 1, 1]]) {
      this.posts.push(bar([gx, 30.34, 0], [gx, 30.34, 2.44], 0.06), bar([gx, 37.66, 0], [gx, 37.66, 2.44], 0.06), bar([gx, 30.34, 2.44], [gx, 37.66, 2.44], 0.06));
      const net = buildNet(gx, s, netMat.clone());
      net.userData.side = side;
      net.userData.sign = s;
      this.nets.push(net);
      this.decor.push(net);
    }
    for (const m of [...this.decor, ...this.posts]) this.scene.add(m);
    // Every opaque piece of scenery hides what is behind it in the full id pass, as it does in the
    // picture: a ball resting behind the boards is not visible. Left out: the sky (always behind),
    // the ground (nothing labelled is under it), the see-through nets and the shadow decals.
    const notOccluders = new Set([sky, surround, pitch, this.shadows, ...this.nets]);
    this.scenery = this.decor.filter((m) => m.isMesh && !notOccluders.has(m));
    for (const m of this.scenery) {
      m.userData.mat = m.material;
      m.userData.idMat = idMaterial(SCENERY_ID);
      m.userData.idMat.side = m.material.side; // the near boards face the pitch: no back face for the gantry
    }

    this.setupLights(p);

    // players and ball, ids 1..n in the order Python sends them
    this.bodies = cfg.objects.map((o, i) => new Body(i + 1, o, this.scene, player));
    this.bodyById = Object.fromEntries(cfg.objects.map((o, i) => [o.id, this.bodies[i]]));

    // offscreen targets: multisampled beauty pass, and a plain id pass
    this.beautyRT = new THREE.WebGLRenderTarget(this.W, this.H, { samples: 4, type: THREE.HalfFloatType });
    this.idRT = new THREE.WebGLRenderTarget(this.W, this.H, { samples: 0, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
    this.idBuf = new Uint8Array(this.W * this.H * 4);

    // post: motion blur along the pan, sensor noise
    this.post = new THREE.ShaderMaterial({
      uniforms: { tex: { value: this.beautyRT.texture }, blur: { value: new THREE.Vector2() }, res: { value: new THREE.Vector2(this.W, this.H) }, noise: { value: p.noise }, frame: { value: 0 }, rain: { value: p.weather === 'rain' ? 1 : 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: `
        uniform sampler2D tex; uniform vec2 blur; uniform vec2 res; uniform float noise; uniform float frame; uniform float rain;
        varying vec2 vUv;
        float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423)); p += dot(p, p.yx + 19.19 + fract(frame * 0.6180339)); return fract((p.x + p.y) * p.x); }
        // The exposure: the picture smeared along the pan over the shutter.
        vec3 smear(vec2 uv, vec2 d){
          vec3 s = vec3(0.0);
          for (int k = 0; k < 9; k++) s += texture2D(tex, uv + d * (float(k) / 8.0 - 0.5)).rgb;
          return s / 9.0;
        }
        void main(){
          vec2 d = vec2(blur.x, -blur.y) / res;
          vec2 px = 1.0 / res;
          vec3 c = smear(vUv, d);
          // The camera sharpens what the sensor recorded, the smear included. Sharpened against the
          // unsmeared picture, a pan split every edge in two: a dark copy where it is, bright ones at
          // either end of its smear (the critic of 0.5.1's first clips: "two ghost copies").
          vec3 nbor = smear(vUv + vec2(px.x, 0.0), d) + smear(vUv - vec2(px.x, 0.0), d)
            + smear(vUv + vec2(0.0, px.y), d) + smear(vUv - vec2(0.0, px.y), d);
          c += (c - nbor * 0.25) * 0.4;
          if (rain > 0.0) {
            c *= 0.9;
            float col = floor(vUv.x * 150.0);
            float h = hash(vec2(col, 1.7));
            float along = fract(vUv.y * 0.45 + vUv.x * 0.08 + h - frame * 0.11);
            float line = smoothstep(0.0, 0.015, along) * smoothstep(0.28, 0.02, along);
            float thin = smoothstep(0.045, 0.0, abs(fract(vUv.x * 150.0) - 0.5));
            float gate = step(0.78, hash(vec2(col, 4.2)));
            c += vec3(0.72, 0.76, 0.8) * line * thin * gate * 0.55;
          }
          c = clamp((c - vec3(0.04)) * 1.22, 0.0, 1.0);
          float luma = dot(c, vec3(0.2126, 0.7152, 0.0722));
          c = mix(vec3(luma), c, 1.1);
          vec2 vig = vUv - 0.5;
          c *= 1.0 - dot(vig, vig) * 0.16;
          c += (hash(gl_FragCoord.xy) - 0.5) * 2.0 * noise;
          gl_FragColor = vec4(max(c, 0.0), 1.0);
          #include <colorspace_fragment>
        }`,
      depthTest: false, depthWrite: false,
    });
    this.postScene = new THREE.Scene();
    this.postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.post));
    this.postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    // scorebug: a generic graphic in the top-left corner, an occluder for the labels.
    // The canvas is the widest the bug gets. Only the painted part occludes.
    this.bugScale = Math.round(this.H / 720 * 100) / 100;
    this.bugCanvas = document.createElement('canvas');
    this.bugCanvas.width = 400; this.bugCanvas.height = 40;
    this.bugTex = canvasTexture(this.bugCanvas);
    this.bugTex.generateMipmaps = false;
    this.bugTex.minFilter = THREE.LinearFilter;
    const s = this.bugScale;
    const maxW = Math.round(400 * s), maxH = Math.round(40 * s);
    const x0 = Math.round(28 * s), y0 = Math.round(24 * s);
    this.bugRect = [x0, y0, x0 + Math.round(270 * s), y0 + maxH];
    this.overlayCam = new THREE.OrthographicCamera(0, this.W, 0, -this.H, -1, 1);
    this.overlayScene = new THREE.Scene();
    this.bug = new THREE.Mesh(new THREE.PlaneGeometry(maxW, maxH), new THREE.MeshBasicMaterial({ map: this.bugTex, transparent: true }));
    this.bug.position.set(x0 + maxW / 2, -(y0 + maxH / 2), 0);
    this.overlayScene.add(this.bug);
    return { bugRect: this.bugRect, maxAnisotropy: this.renderer.capabilities.getMaxAnisotropy(), gl: this.renderer.getContext().getParameter(this.renderer.getContext().VERSION) };
  }

  setupLights(p) {
    const sky = { day: 0xa9c4e6, dusk: 0xd39468, night: 0x0a0d16, overcast: 0xb8bcc2 }[p.lighting];
    this.scene.background = new THREE.Color(sky);
    // MeshStandard is energy-conserving, so these are higher than the old Lambert levels.
    const hemi = {
      day: [0xc5d8f2, 0x1a2810, 0.62], dusk: [0xe0b090, 0x2a301c, 1.05],
      night: [0x9aa8c8, 0x1c2618, 0.85], overcast: [0xd5dbe2, 0x3a5030, 2.4],
    }[p.lighting];
    const hemiLight = new THREE.HemisphereLight(hemi[0], hemi[1], hemi[2]);
    hemiLight.position.set(0, 0, 1); // sky is +z in pitch coordinates
    this.scene.add(hemiLight);
    const centre = new THREE.Object3D();
    centre.position.set(52.5, 34, 0);
    this.scene.add(centre);
    const addSun = (az, el, color, intensity, mapSize, radius) => {
      const L = new THREE.DirectionalLight(color, intensity);
      const a = THREE.MathUtils.degToRad(az), e = THREE.MathUtils.degToRad(el);
      L.position.set(52.5 + 150 * Math.cos(e) * Math.cos(a), 34 + 150 * Math.cos(e) * Math.sin(a), 150 * Math.sin(e));
      L.target = centre;
      L.castShadow = true;
      L.shadow.mapSize.set(mapSize, mapSize);
      L.shadow.radius = radius;
      L.shadow.bias = -0.0005;
      const c = L.shadow.camera;
      c.left = -80; c.right = 80; c.top = 80; c.bottom = -80; c.near = 10; c.far = 400;
      this.scene.add(L);
    };
    if (p.lighting === 'day') addSun(p.sun_azimuth_deg, p.sun_elevation_deg, 0xfff4e2, 5.4, 2048, 3.6);
    if (p.lighting === 'dusk') addSun(p.sun_azimuth_deg, p.sun_elevation_deg, 0xffb27a, 4.2, 2048, 4.0);
    // Overcast has no disc. A high soft key keeps the bowl from falling to black.
    if (p.lighting === 'overcast') addSun(p.sun_azimuth_deg, 62, 0xe7edf2, 3.2, 1024, 8);
    if (p.lighting === 'night') {
      for (const az of [45, 135, 225, 315]) addSun(az + p.sun_azimuth_deg * 0.05, 38, 0xeef2ff, 2.3, 1024, 4);
    }
  }

  goalOpen(age) {
    if (age == null || age < 0) return 0;
    const ease = (t) => 1 - (1 - Math.min(1, Math.max(0, t))) ** 3;
    const inn = 0.42, hold = 1.5, out = 0.5;
    if (age < inn) return ease(age / inn);
    if (age < inn + hold) return 1;
    if (age < inn + hold + out) return 1 - ease((age - inn - hold) / out);
    return 0;
  }

  layoutBug(spec) {
    const open = this.goalOpen(spec.goal_age);
    const s = this.bugScale;
    const canvasW = Math.round(96 * open) + 270;
    const x0 = Math.round(28 * s), y0 = Math.round(24 * s);
    const w = Math.round(canvasW * s), h = Math.round(40 * s);
    this.bugRect = [x0, y0, x0 + w, y0 + h];
    this._bugOpen = open;
    this._bugCanvasW = canvasW;
  }

  drawBug(spec) {
    const open = this._bugOpen ?? 0;
    const canvasW = this._bugCanvasW ?? 270;
    const g = this.bugCanvas.getContext('2d');
    g.clearRect(0, 0, 400, 40);
    const goalW = Math.round(96 * open);
    const plateW = 196;
    const clockW = 74;
    if (goalW > 1) {
      g.fillStyle = '#f4f4f2';
      g.fillRect(0, 0, goalW, 40);
      g.save();
      g.beginPath();
      g.rect(0, 0, goalW, 40);
      g.clip();
      g.globalAlpha = Math.min(1, open * 1.4);
      g.fillStyle = '#161616';
      g.font = '700 15px sans-serif';
      g.textBaseline = 'middle';
      g.fillText('GOAL', 16 + (1 - open) * 18, 20);
      g.restore();
    }
    const plateX = goalW;
    g.fillStyle = 'rgba(12,14,20,0.94)';
    g.fillRect(plateX, 0, plateW, 40);
    g.fillStyle = '#ffffff';
    g.fillRect(plateX, 38, plateW, 2);
    g.font = '600 16px sans-serif';
    g.textBaseline = 'middle';
    g.fillStyle = '#f5f5f3';
    const pop = spec.goal_age != null && spec.goal_age < 0.5 ? 1 - spec.goal_age / 0.5 : 0;
    const home = String(spec.score[0]), away = String(spec.score[1]);
    const drawNum = (text, x, hot) => {
      g.save();
      const lift = hot ? -5 * pop : 0;
      g.translate(x, 20 + lift);
      g.scale(1 + (hot ? 0.18 * pop : 0), 1 + (hot ? 0.18 * pop : 0));
      g.fillText(text, 0, 0);
      g.restore();
    };
    g.fillText(this.p.home_code, plateX + 12, 20);
    drawNum(home, plateX + 62, spec.goal_side === 0);
    g.fillText('-', plateX + 86, 20);
    drawNum(away, plateX + 104, spec.goal_side === 1);
    g.fillText(this.p.away_code, plateX + 128, 20);
    const clockX = plateX + plateW;
    g.fillStyle = '#ececea';
    g.fillRect(clockX, 0, clockW, 40);
    g.fillStyle = '#141414';
    g.font = '600 15px sans-serif';
    g.fillText(spec.clock, clockX + 12, 20);
    // The painted bar is canvasW wide. The mesh shows the whole 400px canvas, left aligned.
    if (canvasW < 400) g.clearRect(canvasW, 0, 400 - canvasW, 40);
    this.bugTex.needsUpdate = true;
  }

  setCamera(c) {
    const cam = this.camera;
    cam.fov = c.fov_v_deg;
    cam.aspect = this.W / this.H;
    cam.updateProjectionMatrix();
    // rows of R are the camera's right, down and forward axes; three.js cameras look down -z, y up
    const [r, d, f] = c.R;
    const m = new THREE.Matrix4().makeBasis(new THREE.Vector3(...r), new THREE.Vector3(-d[0], -d[1], -d[2]), new THREE.Vector3(-f[0], -f[1], -f[2]));
    cam.position.set(...c.position);
    cam.quaternion.setFromRotationMatrix(m);
    cam.updateMatrixWorld(true);
  }

  idMode(on, only = null) {
    for (const m of this.decor) m.visible = !on;
    for (const m of this.scenery) { m.material = on ? m.userData.idMat : m.userData.mat; m.visible = !on || only === null; }
    for (const m of this.posts) { m.material = on ? m.userData.idMat : m.userData.mat; m.visible = !on || only === null; }
    for (const b of this.bodies) { b.useId(on); b.group.visible = b.used > 0 && (only === null || b === only); }
    this.scene.background = on ? new THREE.Color(0, 0, 0) : this.skyColor;
  }

  frame(spec) {
    const T = [performance.now()];
    this.skyColor = this.skyColor ?? this.scene.background;
    this.setCamera(spec.camera);
    for (const o of spec.objects) this.bodyById[o.id].set(o.parts, o.heading, o.pose);
    const dummy = this._shadow || (this._shadow = new THREE.Object3D());
    let si = 0;
    for (const o of spec.objects) {
      if (o.id === 'ball' || si >= 22) continue;
      const hip = o.parts.find((pt) => pt.n === 'hips') || o.parts[0];
      const bootL = o.parts.find((pt) => pt.n === 'boot_l');
      const bootR = o.parts.find((pt) => pt.n === 'boot_r');
      const fx = bootL && bootR ? (bootL.b[0] + bootR.b[0]) / 2 : hip.a[0];
      const fy = bootL && bootR ? (bootL.b[1] + bootR.b[1]) / 2 : hip.a[1];
      dummy.position.set(fx, fy, 0.03);
      dummy.rotation.set(0, 0, o.heading || 0);
      dummy.scale.set(0.32, 0.2, 1);
      dummy.updateMatrix();
      this.shadows.setMatrixAt(si++, dummy.matrix);
    }
    for (; si < 22; si++) {
      dummy.scale.set(0, 0, 0);
      dummy.updateMatrix();
      this.shadows.setMatrixAt(si, dummy.matrix);
    }
    this.shadows.instanceMatrix.needsUpdate = true;
    for (const net of this.nets) poseNet(net, spec.net);
    this.layoutBug(spec);
    const R = this.renderer;
    const W = this.W, H = this.H;
    const [bx0, by0, bx1, by1] = this.bugRect;
    const underBug = (i, j) => i >= bx0 && i < bx1 && j >= by0 && j < by1;

    // 1. solo passes: the full in-image silhouette of each labelled object
    const objects = {};
    R.setRenderTarget(this.idRT);
    R.setClearColor(0x000000, 1);
    for (const o of spec.objects) {
      const body = this.bodyById[o.id];
      const out = { full: 0, visible: 0, bbox: null, centroid: null };
      objects[o.id] = out;
      if (!o.box || body.used === 0) continue;
      // The capsule box is the label. Hair, a boot, or a dive can sit outside
      // it, and the sideline camera makes that about 80px. The solo count has
      // to include the silhouette or visible/full goes over 1.
      const pad = 80;
      const x0 = Math.max(0, Math.floor(o.box[0]) - pad), x1 = Math.min(W, Math.ceil(o.box[2]) + pad);
      const y0 = Math.max(0, Math.floor(o.box[1]) - pad), y1 = Math.min(H, Math.ceil(o.box[3]) + pad);
      if (x1 <= x0 || y1 <= y0) continue;
      this.idMode(true, body);
      R.setScissorTest(true);
      R.setScissor(x0, H - y1, x1 - x0, y1 - y0);
      R.clear();
      R.render(this.scene, this.camera);
      R.setScissorTest(false);
      const w = x1 - x0, h = y1 - y0, buf = new Uint8Array(w * h * 4);
      R.readRenderTargetPixels(this.idRT, x0, H - y1, w, h, buf);
      let n = 0, sx = 0, sy = 0, mi = W, mj = H, Mi = -1, Mj = -1;
      for (let r = 0; r < h; r++) {
        const j = y1 - 1 - r;
        for (let c = 0; c < w; c++) {
          if (buf[(r * w + c) * 4] !== body.id) continue;
          const i = x0 + c;
          n++; sx += i + 0.5; sy += j + 0.5;
          if (i < mi) mi = i; if (i > Mi) Mi = i; if (j < mj) mj = j; if (j > Mj) Mj = j;
        }
      }
      out.full = n;
      if (n) { out.bbox = [mi, mj, Mi + 1, Mj + 1]; out.centroid = [sx / n, sy / n]; }
    }

    T.push(performance.now());
    // 2. full id pass: what is still visible, with the scorebug as an occluder
    this.idMode(true, null);
    R.setRenderTarget(this.idRT);
    R.clear();
    R.render(this.scene, this.camera);
    R.readRenderTargetPixels(this.idRT, 0, 0, W, H, this.idBuf);
    const counts = new Uint32Array(256);
    for (let r = 0; r < H; r++) {
      const j = H - 1 - r;
      for (let i = 0; i < W; i++) {
        const v = this.idBuf[(r * W + i) * 4];
        if (v && !underBug(i, j)) counts[v]++;
      }
    }
    for (const o of spec.objects) objects[o.id].visible = counts[this.bodyById[o.id].id];
    const keypoints = spec.keypoints.map(([px, py]) => {
      const i = Math.floor(px), j = Math.floor(py);
      if (i < 0 || j < 0 || i >= W || j >= H || underBug(i, j)) return false;
      return this.idBuf[((H - 1 - j) * W + i) * 4] === 0;
    });

    T.push(performance.now());
    // 3. beauty pass, post-processing and the scorebug
    this.idMode(false);
    this.renderer.shadowMap.needsUpdate = true;
    R.setRenderTarget(this.beautyRT);
    R.render(this.scene, this.camera);
    this.post.uniforms.blur.value.set(spec.blur[0], spec.blur[1]);
    this.post.uniforms.frame.value = spec.index;
    R.setRenderTarget(null);
    R.render(this.postScene, this.postCam);
    this.drawBug(spec);
    R.autoClear = false;
    R.render(this.overlayScene, this.overlayCam);
    R.autoClear = true;

    this.renderer.getContext().finish();
    T.push(performance.now());
    const image = spec.want_image ? this.renderer.domElement.toDataURL('image/jpeg', this.p.jpeg_quality) : null;
    T.push(performance.now());
    const ms = T.slice(1).map((t, i) => Math.round(t - T[i]));
    let markers = null;
    if (spec.want_markers) {
      markers = {};
      for (const o of spec.objects) {
        const body = this.bodyById[o.id];
        if (body.skin) markers[o.id] = body.markerWorld(o.pose, o.heading);
      }
    }
    return { objects, keypoints, image, markers, ms: { solo: ms[0], id: ms[1], beauty: ms[2], encode: ms[3] } };
  }
}

const instance = new BroadcastRenderer();
window.ninety = {
  init: (cfg) => instance.init(cfg),
  frame: (spec) => instance.frame(spec),
  // The advertising boards' corners and texture coordinates, for the test that they read the right way round.
  boards: () => instance.boards.map((m) => ({
    position: Array.from(m.geometry.attributes.position.array),
    uv: Array.from(m.geometry.attributes.uv.array),
    doubleSided: m.material.side === THREE.DoubleSide,
  })),
  ready: true,
};
