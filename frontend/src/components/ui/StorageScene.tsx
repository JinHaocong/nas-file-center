import { useEffect, useRef } from 'react';
import {
  BoxGeometry, Color, DirectionalLight, Group, HemisphereLight, Mesh, MeshStandardMaterial,
  OrthographicCamera, Scene, WebGLRenderer, type BufferGeometry, type Material,
} from 'three';
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';

export interface StorageSceneProps { onReady: (ready: boolean) => void }

/** Draw a small storage model on demand and release resources when the inspector closes. */
export function StorageScene({ onReady }: StorageSceneProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;

    const context = canvas.getContext('webgl2', { alpha: true, antialias: true });
    if (!context) { onReady(false); return; }

    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, context, alpha: true, antialias: true });
    } catch {
      onReady(false);
      return;
    }

    const scene = new Scene();
    const camera = new OrthographicCamera(-3, 3, 1.95, -1.95, 0.1, 30);
    camera.position.set(3.4, 2.2, 4.8);
    camera.lookAt(0, 0.85, 0);
    const model = new Group();
    scene.add(model);

    const geometry = new Set<BufferGeometry>();
    const materials = new Set<Material>();
    const frameMaterial = new MeshStandardMaterial({ color: '#53675c', metalness: 0.28, roughness: 0.42 });
    const panelMaterial = new MeshStandardMaterial({ color: '#a6b3a1', metalness: 0.12, roughness: 0.52 });
    const trimMaterial = new MeshStandardMaterial({ color: '#292f2b', roughness: 0.68 });
    const lightMaterial = new MeshStandardMaterial({ color: '#6adf99', emissive: new Color('#237f50'), emissiveIntensity: 0.85 });

    /** Group reusable surfaces so each geometry and material is disposed once. */
    function place(shape: BufferGeometry, material: Material, x: number, y: number, z: number) {
      geometry.add(shape);
      materials.add(material);
      const mesh = new Mesh(shape, material);
      mesh.position.set(x, y, z);
      model.add(mesh);
    }

    place(new RoundedBoxGeometry(2.15, 1.65, 1.45, 3, 0.13), frameMaterial, 0, 0.92, 0);
    place(new RoundedBoxGeometry(1.99, 0.11, 1.35, 3, 0.055), panelMaterial, 0, 1.78, 0);
    const bay = new RoundedBoxGeometry(0.41, 1.28, 0.09, 2, 0.034);
    const baySlot = new BoxGeometry(0.24, 0.04, 0.025);
    for (const x of [-0.68, -0.23, 0.23, 0.68]) {
      place(bay, trimMaterial, x, 0.91, 0.75);
      place(baySlot, panelMaterial, x, 0.42, 0.805);
    }
    const signal = new BoxGeometry(0.075, 0.045, 0.025);
    place(signal, lightMaterial, -0.82, 1.66, 0.758);
    place(signal, lightMaterial, -0.69, 1.66, 0.758);

    scene.add(new HemisphereLight('#faf6e9', '#34473d', 2.45));
    const key = new DirectionalLight('#f2f4eb', 2.5);
    key.position.set(3, 5, 4);
    scene.add(key);

    renderer.setClearColor(0, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    let pending = 0;
    let lost = false;

    function scheduleRender() {
      if (pending || lost) return;
      pending = requestAnimationFrame(() => {
        pending = 0;
        renderer.render(scene, camera);
      });
    }

    function resize() {
      const { clientWidth, clientHeight } = canvas!;
      if (!clientWidth || !clientHeight) return;
      const aspect = clientWidth / clientHeight;
      const extent = Math.max(1.58, 2.05 / aspect);
      camera.left = -extent * aspect;
      camera.right = extent * aspect;
      camera.top = extent;
      camera.bottom = -extent;
      camera.updateProjectionMatrix();
      renderer.setSize(clientWidth, clientHeight, false);
      scheduleRender();
    }

    function tilt(event: PointerEvent) {
      if (event.pointerType === 'touch') return;
      const bounds = canvas!.getBoundingClientRect();
      model.rotation.y = ((event.clientX - bounds.left) / bounds.width - 0.5) * 0.42;
      model.rotation.x = ((event.clientY - bounds.top) / bounds.height - 0.5) * 0.16;
      scheduleRender();
    }

    function reset() { model.rotation.set(0, 0, 0); scheduleRender(); }
    function showFallback() { lost = true; onReady(false); }

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    observer?.observe(canvas);
    canvas.addEventListener('pointermove', tilt, { passive: true });
    canvas.addEventListener('pointerleave', reset);
    canvas.addEventListener('webglcontextlost', showFallback);
    resize();
    onReady(true);

    return () => {
      observer?.disconnect();
      if (pending) cancelAnimationFrame(pending);
      canvas.removeEventListener('pointermove', tilt);
      canvas.removeEventListener('pointerleave', reset);
      canvas.removeEventListener('webglcontextlost', showFallback);
      for (const shape of geometry) shape.dispose();
      for (const material of materials) material.dispose();
      renderer.dispose();
      if (!canvas.isConnected) renderer.forceContextLoss();
      onReady(false);
    };
  }, [onReady]);

  return <canvas ref={ref} aria-hidden="true" />;
}
