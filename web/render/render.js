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
  // wear: goalmouths and the centre circle
  const wearSpots = [[5, 34, 7], [100, 34, 7], [11, 34, 5], [94, 34, 5], [52.5, 34, 6]];
  for (const [wx, wy, wr] of wearSpots) {
    const grad = g.createRadialGradient(X(wx), Y(wy), 0, X(wx), Y(wy), wr * PX_PER_M);
    grad.addColorStop(0, `rgba(120,100,60,${0.55 * p.wear})`);
    grad.addColorStop(1, 'rgba(120,100,60,0)');
    g.fillStyle = grad;
    g.fillRect(X(wx - wr), Y(wy + wr), 2 * wr * PX_PER_M, 2 * wr * PX_PER_M);
    for (let k = 0; k < 400 * p.wear; k++) {
      const a = rand() * 6.283, r = Math.sqrt(rand()) * wr;
      g.fillStyle = `rgba(110,90,55,${0.25 + 0.3 * rand()})`;
      g.fillRect(X(wx + Math.cos(a) * r), Y(wy + Math.sin(a) * r), 4 + 6 * rand(), 3 + 5 * rand());
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
    shader.vertexShader = 'varying vec3 vGrassW;\n' + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace(
      '#include <project_vertex>',
      '#include <project_vertex>\n vGrassW = (modelMatrix * vec4(transformed, 1.0)).xyz;'
    );
    shader.fragmentShader = `
      varying vec3 vGrassW;
      uniform float uWet;
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
      // The painted wear is a thin brown. Hold that brown. The stripe stays in the paint.
      float worn = 0.0;
      worn = max(worn, 1.0 - smoothstep(3.2, 7.0, length(vGrassW.xy - vec2(5.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(3.2, 7.0, length(vGrassW.xy - vec2(100.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.2, 5.0, length(vGrassW.xy - vec2(11.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.2, 5.0, length(vGrassW.xy - vec2(94.0, 34.0))));
      worn = max(worn, 1.0 - smoothstep(2.6, 6.0, length(vGrassW.xy - vec2(52.5, 34.0))));
      worn *= 1.0 - pale;
      diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(1.25, 0.78, 0.50), worn);
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

function quad(p0, p1, p2, p3, material, flipU) {
  const geo = new THREE.BufferGeometry();
  const uv = flipU ? [1, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 1] : [0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1];
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

function tier(decor, p, rand, corners, aniso) {
  const map = crowdTexture(p, rand, 2048, 384);
  map.anisotropy = aniso;
  const mat = new THREE.MeshStandardMaterial({
    map,
    roughness: 0.96,
    emissive: new THREE.Color(p.lighting === 'night' ? 0x2a2a2a : 0x121212),
    emissiveIntensity: p.lighting === 'night' ? 0.55 : 0.02,
    side: THREE.DoubleSide,
  });
  decor.push(quad(...corners, mat));
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

const ROUGHNESS = { shirt: 0.82, shorts: 0.84, socks: 0.78, skin: 0.55, hair: 0.7, boots: 0.6, ball: 0.38 };
const METALNESS = { boots: 0.04, ball: 0.05 };

class Body {
  // One labelled object: a player or the ball, built from capsules and spheres.
  constructor(id, spec, scene) {
    this.id = id;
    this.group = new THREE.Group();
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
    scene.add(this.group);
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

  set(parts, heading) {
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

  useId(on) {
    for (let i = 0; i < this.used; i++) {
      const m = this.pool[i];
      m.material = on ? this.idMat : this.materialFor(m.userData.slot);
    }
  }
}

class BroadcastRenderer {
  async init(cfg) {
    const surfaces = await loadGrass();
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

    // Two tiers and a solid back wall. The near stand's front lip stays at y=-46, past the furthest gantry.
    // Stands, roofs and towers are decor: the id pass ignores them.
    const shell = new THREE.MeshStandardMaterial({ color: 0x1c2026, roughness: 0.92, side: THREE.DoubleSide });
    this.decor.push(
      quad([-24, 78, 0.2], [134, 78, 0.2], [134, 114, 18], [-24, 114, 18], shell),
      quad([134, -48, 0.2], [-24, -48, 0.2], [-24, -80, 18], [134, -80, 18], shell),
      quad([-16, 72, 0.8], [-16, 2, 0.8], [-40, 2, 14], [-40, 72, 14], shell),
      quad([121, 2, 0.8], [121, 72, 0.8], [145, 72, 14], [145, 2, 14], shell),
    );
    tier(this.decor, p, rand, [[-4, 74.3, 2.0], [114, 74.3, 2.0], [114, 91, 9.2], [-4, 91, 9.2]], maxAniso);
    tier(this.decor, p, rand, [[-4, 95.5, 10.6], [114, 95.5, 10.6], [114, 112, 19.5], [-4, 112, 19.5]], maxAniso);
    tier(this.decor, p, rand, [[114, -46, 1.6], [-4, -46, 1.6], [-4, -60, 8.4], [114, -60, 8.4]], maxAniso);
    tier(this.decor, p, rand, [[114, -64, 9.6], [-4, -64, 9.6], [-4, -78, 17.5], [114, -78, 17.5]], maxAniso);
    tier(this.decor, p, rand, [[-11, 70, 1.4], [-11, 4, 1.4], [-34, 4, 12], [-34, 70, 12]], maxAniso);
    tier(this.decor, p, rand, [[116, 4, 1.4], [116, 70, 1.4], [139, 70, 12], [139, 4, 12]], maxAniso);
    const roofMat = new THREE.MeshStandardMaterial({ color: 0x16181d, roughness: 0.62, metalness: 0.28 });
    const farRoof = new THREE.Mesh(new THREE.BoxGeometry(140, 8, 0.35), roofMat);
    farRoof.position.set(52.5, 116, 20.2);
    const nearRoof = new THREE.Mesh(new THREE.BoxGeometry(150, 10, 0.45), roofMat);
    nearRoof.position.set(52.5, -68, 22);
    const boardTex = boardTexture(p, rand);
    boardTex.anisotropy = maxAniso;
    const boardsLit = p.lighting === 'night' || p.lighting === 'dusk';
    const boardMat = new THREE.MeshStandardMaterial({
      map: boardTex,
      roughness: 0.5,
      emissive: new THREE.Color(boardsLit ? 0xffffff : 0x444444),
      emissiveMap: boardTex,
      emissiveIntensity: boardsLit ? 0.85 : 0.45,
      side: THREE.DoubleSide,
    });
    const nearBoardMat = boardMat.clone();
    nearBoardMat.side = THREE.FrontSide;
    const boards = [
      quad([-2, 71.5, 0], [107, 71.5, 0], [107, 71.5, 1.8], [-2, 71.5, 1.8], boardMat),
      // Faces the pitch (+y), so the reverse camera reads the boards and the gantry does not see the back.
      quad([107, -1.6, 0], [-2, -1.6, 0], [-2, -1.6, 1.8], [107, -1.6, 1.8], nearBoardMat),
      quad([-4, 2, 0], [-4, 66, 0], [-4, 66, 0.9], [-4, 2, 0.9], boardMat, true),
      quad([109, 66, 0], [109, 2, 0], [109, 2, 0.9], [109, 66, 0.9], boardMat, true),
    ];
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
    this.decor.push(farRoof, nearRoof, ...boards, ...towers, this.shadows);

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

    this.setupLights(p);

    // players and ball, ids 1..n in the order Python sends them
    this.bodies = cfg.objects.map((o, i) => new Body(i + 1, o, this.scene));
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
        void main(){
          vec2 d = vec2(blur.x, -blur.y) / res;
          vec2 px = 1.0 / res;
          vec3 c = vec3(0.0);
          for (int k = 0; k < 9; k++) c += texture2D(tex, vUv + d * (float(k) / 8.0 - 0.5)).rgb;
          c /= 9.0;
          vec3 nbor = texture2D(tex, vUv + vec2(px.x, 0.0)).rgb + texture2D(tex, vUv - vec2(px.x, 0.0)).rgb
            + texture2D(tex, vUv + vec2(0.0, px.y)).rgb + texture2D(tex, vUv - vec2(0.0, px.y)).rgb;
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
    for (const m of this.posts) { m.material = on ? m.userData.idMat : m.userData.mat; m.visible = !on || only === null; }
    for (const b of this.bodies) { b.useId(on); b.group.visible = b.used > 0 && (only === null || b === only); }
    this.scene.background = on ? new THREE.Color(0, 0, 0) : this.skyColor;
  }

  frame(spec) {
    const T = [performance.now()];
    this.skyColor = this.skyColor ?? this.scene.background;
    this.setCamera(spec.camera);
    for (const o of spec.objects) this.bodyById[o.id].set(o.parts, o.heading);
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
      const x0 = Math.max(0, Math.floor(o.box[0]) - 3), x1 = Math.min(W, Math.ceil(o.box[2]) + 3);
      const y0 = Math.max(0, Math.floor(o.box[1]) - 3), y1 = Math.min(H, Math.ceil(o.box[3]) + 3);
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
    return { objects, keypoints, image, ms: { solo: ms[0], id: ms[1], beauty: ms[2], encode: ms[3] } };
  }
}

const instance = new BroadcastRenderer();
window.ninety = {
  init: (cfg) => instance.init(cfg),
  frame: (spec) => instance.frame(spec),
  ready: true,
};
