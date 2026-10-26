// The broadcast look: how footage a viewer watches is lit and graded. Applied only to the broadcast
// stream of a stadium=broadcast clip (the demo match), after the scene is built, so every training,
// validation and test render (stadium=plain) and the fixed tactical views keep their pixels exactly.
// It changes light and colour only: no position, size or label, and it draws nothing from the seed.
//
// What it does, each against a way the old picture read as a game rather than television (design):
// - a filmic tone curve (ACES) instead of a hard clip, so white shirts and the sunlit stripe roll off
//   instead of burning out;
// - image-based light from a physical sky (three.js Sky, Preetham model) as the fill, so the shaded
//   side of a player is lit blue-grey by the sky and green from the turf, not a flat ambient;
// - the stands in the roof's shade and the crowd's clothes in muted, real-world colours (a crowd is
//   a dim, busy texture on television, not a field of saturated tokens);
// - gentler sharpening (fewer halos round the players) and a warm-highlight, green-midtone grade.

import * as THREE from 'three';
import { Sky } from 'three/addons/objects/Sky.js';

export const LOOK = {
  exposure: 1.0,          // ACES compresses mid-tones; this brings the turf back to broadcast level
  envIntensity: 0.22,      // the sky's image-based fill, relative to its physical level
  hemiScale: 0.3,         // the old flat fill, kept a little so the shade side is never black
  sunScale: 1.0,
  shadowMap: 4096,
  turfEnv: 0.25,           // the sky's fill on the turf, relative to the rest (it turned the grass cyan)
  saturation: 1.16,
  sharpen: 0.22,           // was 0.4 in the plain look
  crowdSat: 0.55,          // crowd clothing saturation kept
  crowdLight: 0.62,        // and lightness kept, before the roof shade
  roofShade: 0.45,         // the back rows' brightness relative to the front (in the roof's shadow)
  haze: [70, 700],         // m: daylight haze from near to full, so the far stand sits back (aerial perspective)
};

// The grade, in linear light before the tone curve (render.js post shader, BROADCAST_LOOK).
export const GRADE_GLSL = `
  vec3 broadcastGrade(vec3 c) {
    // white balance a touch warm, as a daylight broadcast is graded
    c *= vec3(1.045, 1.0, 0.94);
    float luma = dot(c, vec3(0.2126, 0.7152, 0.0722));
    // a little more colour in the mid-tones, less in the highlights (ACES adds its own)
    float mid = smoothstep(0.02, 0.25, luma) * (1.0 - smoothstep(0.6, 1.4, luma));
    c = mix(vec3(luma), c, LOOK_SAT + 0.12 * mid);
    // warm highlights, cooler shadows (a split tone, small)
    vec3 warm = vec3(1.04, 1.0, 0.93), cool = vec3(0.96, 1.0, 1.05);
    c *= mix(cool, warm, smoothstep(0.05, 0.6, luma));
    return max(c, 0.0);
  }
`;

function skyEnvironment(renderer, p) {
  const sky = new Sky();
  sky.scale.setScalar(1000);
  const u = sky.material.uniforms;
  // Sky.js assumes y is up; the pitch has z up.
  u.up.value.set(0, 0, 1);
  sky.material.fragmentShader = sky.material.fragmentShader.replace('acos( direction.y )', 'acos( direction.z )');
  sky.material.vertexShader = sky.material.vertexShader.replace('sunPosition.y / 450000.0', 'sunPosition.z / 450000.0');
  u.turbidity.value = 4.5;
  u.rayleigh.value = 1.6;
  u.mieCoefficient.value = 0.004;
  u.mieDirectionalG.value = 0.8;
  const az = THREE.MathUtils.degToRad(p.sun_azimuth_deg), el = THREE.MathUtils.degToRad(p.sun_elevation_deg);
  u.sunPosition.value.set(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el));
  const scene = new THREE.Scene();
  scene.add(sky);
  // the turf below the horizon: what lights a player's underside and shaded flank
  const ground = new THREE.Mesh(new THREE.CircleGeometry(900, 32), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.05, 0.11, 0.03) }));
  ground.position.z = -5;
  scene.add(ground);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = pmrem.fromScene(scene, 0, 0.1, 2000).texture;
  pmrem.dispose();
  return env;
}

function shadeCrowd(crowd) {
  if (!crowd) return;
  const [torso, head] = crowd.meshes;
  const hsl = { h: 0, s: 0, l: 0 };
  const c = new THREE.Color();
  const m = new THREE.Matrix4();
  const pos = new THREE.Vector3();
  let zMin = Infinity, zMax = -Infinity;
  for (let i = 0; i < torso.count; i++) {
    torso.getMatrixAt(i, m); pos.setFromMatrixPosition(m);
    zMin = Math.min(zMin, pos.z); zMax = Math.max(zMax, pos.z);
  }
  for (let i = 0; i < torso.count; i++) {
    torso.getMatrixAt(i, m); pos.setFromMatrixPosition(m);
    // The roof's shadow: the back rows sit in shade, the front ones in the open.
    const t = (pos.z - zMin) / Math.max(zMax - zMin, 1e-3);
    const shade = 1.0 - (1.0 - LOOK.roofShade) * THREE.MathUtils.smoothstep(t, 0.25, 0.85);
    // A per-fan variation from the seat's position (no draw from the seed).
    const jitter = 0.85 + 0.3 * (Math.abs(Math.sin(pos.x * 12.9898 + pos.y * 78.233) * 43758.5453) % 1);
    torso.getColorAt(i, c); c.getHSL(hsl);
    c.setHSL(hsl.h, hsl.s * LOOK.crowdSat, hsl.l * LOOK.crowdLight * jitter * shade + 0.02);
    torso.setColorAt(i, c);
    head.getColorAt(i, c); c.getHSL(hsl);
    c.setHSL(hsl.h, hsl.s * 0.8, hsl.l * 0.85 * shade);
    head.setColorAt(i, c);
  }
  torso.instanceColor.needsUpdate = true;
  head.instanceColor.needsUpdate = true;
}

// r: the BroadcastRenderer after init built its scene. Returns what it did, for clip.json.
export function applyBroadcastLook(r) {
  const R = r.renderer;
  R.toneMapping = THREE.ACESFilmicToneMapping;
  R.toneMappingExposure = LOOK.exposure;
  r.scene.environment = skyEnvironment(R, r.p);
  r.scene.environmentIntensity = LOOK.envIntensity;
  r.scene.traverse((o) => {
    if (o.isHemisphereLight) o.intensity *= LOOK.hemiScale;
    if (o.isDirectionalLight) {
      o.intensity *= LOOK.sunScale;
      if (o.castShadow) {
        o.shadow.mapSize.set(LOOK.shadowMap, LOOK.shadowMap);
        o.shadow.map?.dispose();
        o.shadow.map = null;
      }
    }
  });
  const [, surround, pitch] = r.decor;
  for (const m of [surround, pitch]) m.material.envMapIntensity = LOOK.turfEnv;
  shadeCrowd(r.crowd);
  // Haze: the scenery only, never a player or the ball, so nothing labelled changes colour with depth.
  r.scene.fog = new THREE.Fog(new THREE.Color(0.62, 0.68, 0.74), LOOK.haze[0], LOOK.haze[1]);
  for (const b of r.bodies) {
    for (const m of Object.values(b.materials)) m.fog = false;
    if (b.eyeMat) b.eyeMat.fog = false;
  }
  // Graphics are drawn after the grade and keep their exact colours (vision reads the scorebug).
  r.overlayScene.traverse((o) => { if (o.material) o.material.toneMapped = false; });
  r.post.defines = { ...(r.post.defines || {}), BROADCAST_LOOK: 1, LOOK_SAT: LOOK.saturation.toFixed(3) };
  r.post.uniforms.sharpen.value = LOOK.sharpen;
  r.post.needsUpdate = true;
  return { tone: 'aces', ...LOOK };
}
