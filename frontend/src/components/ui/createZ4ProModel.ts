import {
  CanvasTexture, CircleGeometry, ExtrudeGeometry, Group, Mesh, MeshBasicMaterial,
  MeshStandardMaterial, PlaneGeometry, Shape, SRGBColorSpace, type BufferGeometry,
} from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';

const width = 1.48;
const height = 1.8;
const depth = 2.42;

/** Render the engraved badge and the diagonal indicator strip into tiny local textures. */
function artwork(kind: 'badge' | 'strip' | 'shadow') {
  const canvas = document.createElement('canvas');
  canvas.width = kind === 'strip' ? 640 : 256;
  canvas.height = kind === 'strip' ? 480 : 256;
  const context = canvas.getContext('2d')!;
  if (kind === 'shadow') {
    const fade = context.createRadialGradient(128, 128, 9, 128, 128, 118);
    fade.addColorStop(0, 'rgba(30,24,19,.46)');
    fade.addColorStop(.45, 'rgba(30,24,19,.25)');
    fade.addColorStop(1, 'rgba(30,24,19,0)');
    context.fillStyle = fade;
    context.fillRect(0, 0, 256, 256);
  } else if (kind === 'badge') {
    context.fillStyle = '#8e9293';
    context.beginPath();
    for (const [x, y] of [[120,44],[175,86],[151,107],[121,83],[108,94],[140,119],[116,140],[83,113],[83,74]]) {
      context.lineTo(x, y);
    }
    context.closePath();
    context.fill();
    context.beginPath();
    for (const [x, y] of [[138,211],[82,170],[106,149],[134,173],[149,161],[118,138],[141,117],[174,142],[174,182]]) {
      context.lineTo(x, y);
    }
    context.closePath();
    context.fill();
  } else {
    const tone = context.createLinearGradient(0, 0, 480, 420);
    tone.addColorStop(0, '#52483d');
    tone.addColorStop(.56, '#796957');
    tone.addColorStop(1, '#3b332b');
    context.fillStyle = tone;
    context.fillRect(0, 0, canvas.width, canvas.height);
    for (let y = 0; y < canvas.height; y += 2) {
      const alpha = .025 + .025 * Math.sin(y * .39);
      context.fillStyle = 'rgba(235,212,185,' + alpha + ')';
      context.fillRect(0, y, canvas.width, 1);
    }
    context.save();
    context.translate(315, 267);
    context.rotate(.40);
    for (let i = 0; i < 4; i += 1) {
      context.fillStyle = i < 2 ? '#dbe7c8' : '#c2b492';
      context.beginPath();
      context.arc((i - 1.5) * 10, 0, 2.7, 0, Math.PI * 2);
      context.fill();
    }
    context.restore();
  }
  const texture = new CanvasTexture(canvas);
  texture.colorSpace = SRGBColorSpace;
  return texture;
}

/** Round the face independent of its shallow depth so the cover matches the real silhouette. */
function face(w: number, h: number, radius: number, thickness: number) {
  const x = w / 2;
  const y = h / 2;
  const path = new Shape();
  path.moveTo(-x + radius, -y);
  path.lineTo(x - radius, -y);
  path.quadraticCurveTo(x, -y, x, -y + radius);
  path.lineTo(x, y - radius);
  path.quadraticCurveTo(x, y, x - radius, y);
  path.lineTo(-x + radius, y);
  path.quadraticCurveTo(-x, y, -x, y - radius);
  path.lineTo(-x, -y + radius);
  path.quadraticCurveTo(-x, -y, -x + radius, -y);
  return new ExtrudeGeometry(path, { depth: thickness, bevelEnabled: true, bevelSize: .023,
    bevelThickness: .020, bevelSegments: 4, curveSegments: 14 });
}

/** Shape the pearl-white panels around the recessed diagonal strip. */
function sidePanel(upper: boolean) {
  const path = new Shape();
  if (upper) {
    path.moveTo(-1.18, .42);
    path.quadraticCurveTo(-1.27, .77, -1.03, .80);
    path.lineTo(1.19, .80);
    path.lineTo(1.18, -.56);
    path.quadraticCurveTo(1.05, -.29, .89, -.24);
    path.lineTo(-1.06, .36);
    path.quadraticCurveTo(-1.15, .38, -1.18, .42);
  } else {
    path.moveTo(-1.17, .06);
    path.quadraticCurveTo(-1.14, .22, -.98, .17);
    path.lineTo(1.05, -.56);
    path.quadraticCurveTo(1.16, -.61, 1.19, -.80);
    path.lineTo(-1.04, -.80);
    path.quadraticCurveTo(-1.18, -.80, -1.18, -.62);
    path.closePath();
  }
  return new ExtrudeGeometry(path, { depth: .012, bevelEnabled: true, bevelSize: .026,
    bevelThickness: .029, bevelSegments: 4, curveSegments: 14 });
}

/** Build a compact Z4 Pro rendering from the enclosure, inset front cover and side panels. */
export function createZ4ProModel() {
  const model = new Group();
  const white = new MeshStandardMaterial({ color: '#f2f2f4', metalness: .04, roughness: .38 });
  const panel = new MeshStandardMaterial({ color: '#f0f1f1', metalness: .02, roughness: .45 });
  const surround = new MeshStandardMaterial({ color: '#302f2e', metalness: .26, roughness: .34 });
  const feet = new MeshStandardMaterial({ color: '#585651', roughness: .7 });
  const badge = artwork('badge');
  const strip = artwork('strip');
  const shadowMap = artwork('shadow');
  const badgeMaterial = new MeshBasicMaterial({ map: badge, transparent: true, depthWrite: false });
  const stripMaterial = new MeshStandardMaterial({ map: strip, metalness: .1, roughness: .56 });
  const shadowMaterial = new MeshBasicMaterial({ map: shadowMap, transparent: true, depthWrite: false, opacity: .78 });
  const geometries = new Set<BufferGeometry>();

  /** Position each part using the same front plane as the outer enclosure. */
  function part(shape: BufferGeometry, surface: MeshBasicMaterial | MeshStandardMaterial, x: number, y: number, z: number) {
    const mesh = new Mesh(shape, surface);
    mesh.position.set(x, y, z);
    geometries.add(shape);
    model.add(mesh);
    return mesh;
  }

  part(new RoundedBoxGeometry(width, height, depth, 4, .19), white, 0, 0, 0);
  part(face(1.39, 1.71, .19, .075), surround, 0, 0, 1.15);
  part(face(1.27, 1.56, .16, .041), panel, 0, 0, 1.199);
  part(new PlaneGeometry(.34, .34), badgeMaterial, 0, .012, 1.261);
  part(new RoundedBoxGeometry(.085, .016, .018, 2, .007), white, 0, -.83, 1.228);
  const foot = new RoundedBoxGeometry(.22, .08, .28, 2, .035);
  for (const x of [-.47, .47]) {
    for (const z of [-.79, .78]) part(foot, feet, x, -.899, z);
  }

  const stripGeometry = new PlaneGeometry(depth - .20, height - .33);
  part(stripGeometry, stripMaterial, -.741, 0, 0).rotation.y = -Math.PI / 2;
  // The light finish wraps across the top of the body. The two left panels
  // make the diagonal recess readable from the default presentation angle.
  part(sidePanel(true), white, -.76, 0, 0).rotation.y = -Math.PI / 2;
  part(sidePanel(false), white, -.76, 0, 0).rotation.y = -Math.PI / 2;

  const shadow = new Mesh(new CircleGeometry(1, 48), shadowMaterial);
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = -.95;
  shadow.scale.set(1.50, 1.72, 1);
  return {
    model,
    shadow,
    /** Release the model and its decorative textures together. */
    dispose() {
      for (const shape of geometries) shape.dispose();
      shadow.geometry.dispose();
      for (const surface of [white, panel, surround, feet, badgeMaterial, stripMaterial, shadowMaterial]) surface.dispose();
      for (const texture of [badge, strip, shadowMap]) texture.dispose();
    },
  };
}
