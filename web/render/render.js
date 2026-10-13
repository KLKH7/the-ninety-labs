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

  // mowing stripes across the pitch
  const hue = p.grass_hue;
  const night = p.lighting === 'night';
  for (let x = GROUND.x0, i = 0; x < GROUND.x1; x += p.stripe_width_m, i++) {
    g.fillStyle = hsl(hue, 0.55, (i % 2 ? 0.30 : 0.34) * (night ? 0.95 : 1));
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

function quad(p0, p1, p2, p3, material) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute([...p0, ...p1, ...p2, ...p0, ...p2, ...p3], 3));
  geo.setAttribute('uv', new THREE.Float32BufferAttribute([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], 2));
  geo.computeVertexNormals();
  return new THREE.Mesh(geo, material);
}

function crowdTexture(p, rand, w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d');
  g.fillStyle = p.stand_color;
  g.fillRect(0, 0, w, h);
  const rows = Math.floor(h / 9);
  for (let r = 0; r < rows; r++) {
    for (let x = 0; x < w; x += 7) {
      if (rand() > p.crowd_density) continue;
      g.fillStyle = hsl(rand(), 0.2 + 0.6 * rand(), 0.2 + 0.6 * rand());
      g.fillRect(x + rand() * 2, r * 9 + 3, 5, 5);
      g.fillStyle = hsl(0.06, 0.4, 0.25 + 0.5 * rand());
      g.fillRect(x + 1 + rand() * 2, r * 9, 3, 3);
    }
  }
  const tex = canvasTexture(c);
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

function netTexture() {
  const c = document.createElement('canvas');
  c.width = 256; c.height = 256;
  const g = c.getContext('2d');
  g.strokeStyle = 'rgba(255,255,255,0.8)';
  g.lineWidth = 2;
  for (let i = 0; i <= 256; i += 16) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, 256); g.moveTo(0, i); g.lineTo(256, i); g.stroke(); }
  const t = canvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(6, 3);
  return t;
}

// ---- renderer -------------------------------------------------------------------------------

const UP = new THREE.Vector3(0, 1, 0);
const unitCylinder = new THREE.CylinderGeometry(1, 1, 1, 14, 1, true);
const unitSphere = new THREE.SphereGeometry(1, 16, 12);

function idMaterial(id) {
  return new THREE.ShaderMaterial({
    uniforms: { idc: { value: new THREE.Vector3(id / 255, 0, 0) } },
    vertexShader: 'void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
    fragmentShader: 'uniform vec3 idc; void main(){ gl_FragColor = vec4(idc, 1.0); }',
    blending: THREE.NoBlending,
    side: THREE.DoubleSide,
  });
}

class Body {
  // One labelled object: a player or the ball, built from capsules and spheres.
  constructor(id, colors, scene) {
    this.id = id;
    this.group = new THREE.Group();
    this.colors = colors;
    this.materials = {};
    for (const [slot, hex] of Object.entries(colors)) this.materials[slot] = new THREE.MeshLambertMaterial({ color: hex });
    this.idMat = idMaterial(id);
    this.pool = [];
    this.used = 0;
    scene.add(this.group);
  }

  mesh(geo, slot) {
    let m = this.pool[this.used];
    if (!m || m.geometry !== geo) {
      m = new THREE.Mesh(geo, this.materials[slot]);
      m.castShadow = true;
      m.matrixAutoUpdate = false;
      if (this.pool[this.used]) this.group.remove(this.pool[this.used]);
      this.pool[this.used] = m;
      this.group.add(m);
    }
    m.material = this.materials[slot];
    m.userData.slot = slot;
    m.visible = true;
    this.used++;
    return m;
  }

  set(parts) {
    this.used = 0;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), dir = new THREE.Vector3(), q = new THREE.Quaternion();
    for (const p of parts) {
      a.fromArray(p.a);
      const s = this.mesh(unitSphere, p.c);
      s.matrix.compose(a, q.identity(), new THREE.Vector3(p.r, p.r, p.r));
      if (!p.b) continue;
      b.fromArray(p.b);
      const s2 = this.mesh(unitSphere, p.c);
      s2.matrix.compose(b, q.identity(), new THREE.Vector3(p.r, p.r, p.r));
      dir.subVectors(b, a);
      const len = dir.length();
      if (len < 1e-6) continue;
      const cyl = this.mesh(unitCylinder, p.c);
      q.setFromUnitVectors(UP, dir.clone().divideScalar(len));
      cyl.matrix.compose(a.clone().addScaledVector(dir, 0.5), q, new THREE.Vector3(p.r, len, p.r));
    }
    for (let i = this.used; i < this.pool.length; i++) this.pool[i].visible = false;
    this.group.visible = this.used > 0;
  }

  useId(on) {
    for (let i = 0; i < this.used; i++) {
      const m = this.pool[i];
      m.material = on ? this.idMat : this.materials[m.userData.slot];
    }
  }
}

class BroadcastRenderer {
  init(cfg) {
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
    this.camera = new THREE.PerspectiveCamera(30, this.W / this.H, 1, 600);

    // ground: textured pitch over a darker surround
    const surround = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.MeshLambertMaterial({ color: new THREE.Color().setHSL(p.grass_hue, 0.45, 0.16) }));
    surround.position.set(52.5, 34, -0.02);
    surround.receiveShadow = true;
    const pitchTex = pitchTexture(p, rand);
    pitchTex.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const pitch = new THREE.Mesh(new THREE.PlaneGeometry(GROUND.x1 - GROUND.x0, GROUND.y1 - GROUND.y0), new THREE.MeshLambertMaterial({ map: pitchTex }));
    pitch.position.set((GROUND.x0 + GROUND.x1) / 2, (GROUND.y0 + GROUND.y1) / 2, 0);
    pitch.receiveShadow = true;
    this.decor = [surround, pitch];

    // stands and boards behind the far touchline and both goal lines
    const crowdMat = (w, h) => new THREE.MeshLambertMaterial({ map: crowdTexture(p, rand, w, h), side: THREE.DoubleSide });
    const far = quad([-30, 78, 1.2], [135, 78, 1.2], [135, 108, 24], [-30, 108, 24], crowdMat(2048, 512));
    const left = quad([-12, 90, 1.2], [-12, -22, 1.2], [-40, -22, 22], [-40, 90, 22], crowdMat(1536, 384));
    const right = quad([117, -22, 1.2], [117, 90, 1.2], [145, 90, 22], [145, -22, 22], crowdMat(1536, 384));
    const roof = new THREE.Mesh(new THREE.PlaneGeometry(400, 60), new THREE.MeshBasicMaterial({ color: 0x15171c, side: THREE.DoubleSide }));
    roof.position.set(52.5, 112, 26);
    roof.rotation.x = Math.PI / 2;
    const boardMat = new THREE.MeshLambertMaterial({ map: boardTexture(p, rand), side: THREE.DoubleSide });
    const boards = [
      quad([-2, 71.5, 0], [107, 71.5, 0], [107, 71.5, 0.9], [-2, 71.5, 0.9], boardMat),
      quad([-4, 66, 0], [-4, 2, 0], [-4, 2, 0.9], [-4, 66, 0.9], boardMat),
      quad([109, 2, 0], [109, 66, 0], [109, 66, 0.9], [109, 2, 0.9], boardMat),
    ];
    this.decor.push(far, left, right, roof, ...boards);

    // goals: posts and crossbar are occluders in the id pass; the net is decor
    this.posts = [];
    const white = new THREE.MeshLambertMaterial({ color: 0xf4f4f4 });
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
    const netMat = new THREE.MeshLambertMaterial({ map: netTexture(), transparent: true, opacity: 0.55, side: THREE.DoubleSide, depthWrite: false });
    for (const [gx, s] of [[0, -1], [105, 1]]) {
      this.posts.push(bar([gx, 30.34, 0], [gx, 30.34, 2.44], 0.06), bar([gx, 37.66, 0], [gx, 37.66, 2.44], 0.06), bar([gx, 30.34, 2.44], [gx, 37.66, 2.44], 0.06));
      const bx = gx + s * 2;
      this.decor.push(
        quad([bx, 30.34, 0], [bx, 37.66, 0], [bx, 37.66, 2.0], [bx, 30.34, 2.0], netMat),
        quad([gx, 30.34, 2.44], [gx, 37.66, 2.44], [bx, 37.66, 2.0], [bx, 30.34, 2.0], netMat),
        quad([gx, 30.34, 0], [bx, 30.34, 0], [bx, 30.34, 2.0], [gx, 30.34, 2.44], netMat),
        quad([gx, 37.66, 0], [bx, 37.66, 0], [bx, 37.66, 2.0], [gx, 37.66, 2.44], netMat),
      );
    }
    for (const m of [...this.decor, ...this.posts]) this.scene.add(m);

    this.setupLights(p);

    // players and ball, ids 1..n in the order Python sends them
    this.bodies = cfg.objects.map((o, i) => new Body(i + 1, o.colors, this.scene));
    this.bodyById = Object.fromEntries(cfg.objects.map((o, i) => [o.id, this.bodies[i]]));

    // offscreen targets: multisampled beauty pass, and a plain id pass
    this.beautyRT = new THREE.WebGLRenderTarget(this.W, this.H, { samples: 4, type: THREE.HalfFloatType });
    this.idRT = new THREE.WebGLRenderTarget(this.W, this.H, { samples: 0, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter });
    this.idBuf = new Uint8Array(this.W * this.H * 4);

    // post: motion blur along the pan, sensor noise
    this.post = new THREE.ShaderMaterial({
      uniforms: { tex: { value: this.beautyRT.texture }, blur: { value: new THREE.Vector2() }, res: { value: new THREE.Vector2(this.W, this.H) }, noise: { value: p.noise }, frame: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
      fragmentShader: `
        uniform sampler2D tex; uniform vec2 blur; uniform vec2 res; uniform float noise; uniform float frame;
        varying vec2 vUv;
        float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423)); p += dot(p, p.yx + 19.19 + fract(frame * 0.6180339)); return fract((p.x + p.y) * p.x); }
        void main(){
          vec2 d = vec2(blur.x, -blur.y) / res;
          vec3 c = vec3(0.0);
          for (int k = 0; k < 9; k++) c += texture2D(tex, vUv + d * (float(k) / 8.0 - 0.5)).rgb;
          c /= 9.0;
          c += (hash(gl_FragCoord.xy) - 0.5) * 2.0 * noise;
          gl_FragColor = vec4(max(c, 0.0), 1.0);
          #include <colorspace_fragment>
        }`,
      depthTest: false, depthWrite: false,
    });
    this.postScene = new THREE.Scene();
    this.postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.post));
    this.postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    // scorebug: a generic graphic in the top-left corner, an occluder for the labels
    this.bugCanvas = document.createElement('canvas');
    this.bugCanvas.width = 256; this.bugCanvas.height = 32;
    this.bugTex = canvasTexture(this.bugCanvas);
    this.bugTex.generateMipmaps = false;
    this.bugTex.minFilter = THREE.LinearFilter;
    const s = Math.round(this.H / 720 * 100) / 100;
    this.bugRect = [Math.round(32 * s), Math.round(28 * s), Math.round(32 * s) + Math.round(256 * s), Math.round(28 * s) + Math.round(32 * s)];
    const [bx0, by0, bx1, by1] = this.bugRect;
    this.overlayCam = new THREE.OrthographicCamera(0, this.W, 0, -this.H, -1, 1);
    this.overlayScene = new THREE.Scene();
    const bug = new THREE.Mesh(new THREE.PlaneGeometry(bx1 - bx0, by1 - by0), new THREE.MeshBasicMaterial({ map: this.bugTex, transparent: true }));
    bug.position.set((bx0 + bx1) / 2, -(by0 + by1) / 2, 0);
    this.overlayScene.add(bug);
    return { bugRect: this.bugRect, maxAnisotropy: this.renderer.capabilities.getMaxAnisotropy(), gl: this.renderer.getContext().getParameter(this.renderer.getContext().VERSION) };
  }

  setupLights(p) {
    const sky = { day: 0xa9c4e6, dusk: 0xd39468, night: 0x0a0d16, overcast: 0xb8bcc2 }[p.lighting];
    this.scene.background = new THREE.Color(sky);
    const hemi = {
      day: [0xcfe0ff, 0x3a5a2a, 1.1], dusk: [0xe0b090, 0x3a4a2a, 0.7],
      night: [0x9aa8c8, 0x26331f, 0.55], overcast: [0xe2e6ea, 0x45603a, 2.2],
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
    if (p.lighting === 'day') addSun(p.sun_azimuth_deg, p.sun_elevation_deg, 0xfff2dc, 2.6, 2048, 1.5);
    if (p.lighting === 'dusk') addSun(p.sun_azimuth_deg, p.sun_elevation_deg, 0xffb27a, 2.0, 2048, 2);
    if (p.lighting === 'night') {
      for (const az of [45, 135, 225, 315]) addSun(az + p.sun_azimuth_deg * 0.05, 38, 0xeef2ff, 0.75, 1024, 4);
    }
  }

  drawBug(spec) {
    const g = this.bugCanvas.getContext('2d');
    g.clearRect(0, 0, 256, 32);
    g.fillStyle = 'rgba(14,16,24,0.9)'; g.fillRect(0, 0, 256, 32);
    g.fillStyle = '#e5e7eb'; g.fillRect(186, 0, 70, 32);
    g.font = 'bold 18px sans-serif'; g.textBaseline = 'middle';
    g.fillStyle = '#ffffff';
    g.fillText(`${this.p.home_code}  ${spec.score[0]} - ${spec.score[1]}  ${this.p.away_code}`, 10, 17);
    g.fillStyle = '#111827';
    g.fillText(spec.clock, 196, 17);
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
    for (const o of spec.objects) this.bodyById[o.id].set(o.parts);
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
