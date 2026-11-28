import { useEffect, useRef, type RefObject } from 'react';

import { DirectionalLight, HemisphereLight, MathUtils, OrthographicCamera, Scene, WebGLRenderer } from 'three';

import { createZ4ProModel } from './createZ4ProModel';

export interface StorageSceneProps {
  onReady: (ready: boolean) => void;
  pointerArea?: RefObject<HTMLElement>;
}

const yawLimit = MathUtils.degToRad(28);
const pitchLimit = MathUtils.degToRad(12);

/** Map each side of the preview's center independently to the tracking area's edge. */
function pointerOffset(position: number, center: number, start: number, end: number) {
  const extent = position < center ? center - start : end - center;
  return MathUtils.clamp((position - center) / Math.max(extent, 1), -1, 1);
}

/** Render the Z4 Pro during motion and leave the GPU idle at rest. */
export function StorageScene({ onReady, pointerArea }: StorageSceneProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const host = canvas?.parentElement;
    if (!canvas || !host) return;
    const area = pointerArea?.current ?? host;

    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true });
    } catch {
      onReady(false);
      return;
    }

    const scene = new Scene();
    const camera = new OrthographicCamera(-3, 3, 1.95, -1.95, 0.1, 30);
    camera.position.set(-4.6, 2.35, 5.1);
    camera.lookAt(0, -.02, 0);
    const { model, shadow, dispose } = createZ4ProModel();
    scene.add(model, shadow);
    scene.add(new HemisphereLight('#fffdfb', '#b2a89d', 2.18));

    const key = new DirectionalLight('#fffaf5', 1.71);
    key.position.set(-3, 5, 4);
    scene.add(key);
    const fill = new DirectionalLight('#e3ecff', .45);
    fill.position.set(2, 1, -4);
    scene.add(fill);

    renderer.setClearColor(0, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    let pending = 0;
    let lost = false;
    let rendered = false;
    let previousTime = 0;
    let targetX = 0;
    let targetY = 0;

    /** Approach the last pointer position and stop requesting frames once settled. */
    function render(time: number) {
      pending = 0;
      if (lost) return;
      const delta = previousTime ? Math.min((time - previousTime) / 1000, .05) : 1 / 60;
      model.rotation.x = MathUtils.damp(model.rotation.x, targetX, 17, delta);
      model.rotation.y = MathUtils.damp(model.rotation.y, targetY, 17, delta);
      const settling = Math.abs(model.rotation.x - targetX) + Math.abs(model.rotation.y - targetY) > .001;
      if (!settling) model.rotation.set(targetX, targetY, 0);
      renderer.render(scene, camera);
      if (!rendered) {
        rendered = true;
        onReady(true);
      }
      previousTime = settling ? time : 0;
      if (settling) scheduleRender();
    }

    function scheduleRender() {
      if (!pending && !lost) pending = requestAnimationFrame(render);
    }

    function resize() {
      const { clientWidth, clientHeight } = host!;
      if (!clientWidth || !clientHeight) return;
      const aspect = clientWidth / clientHeight;
      const extent = Math.max(1.47, 2.10 / aspect);
      camera.left = -extent * aspect;
      camera.right = extent * aspect;
      camera.top = extent;
      camera.bottom = -extent;
      camera.updateProjectionMatrix();
      renderer.setSize(clientWidth, clientHeight, false);
      scheduleRender();
    }

    /** Follow the surrounding workspace while staying neutral at the card center. */
    function tilt(event: PointerEvent) {
      if (event.pointerType === 'touch') return;
      const card = host!.getBoundingClientRect();
      const bounds = area.getBoundingClientRect();
      if (!card.width || !card.height || !bounds.width || !bounds.height) return;
      targetX = pointerOffset(event.clientY, card.top + card.height / 2, bounds.top, bounds.bottom) * pitchLimit;
      targetY = pointerOffset(event.clientX, card.left + card.width / 2, bounds.left, bounds.right) * yawLimit;
      scheduleRender();
    }

    function reset() {
      targetX = 0;
      targetY = 0;
      scheduleRender();
    }

    function showFallback(event: Event) {
      event.preventDefault();
      lost = true;
      rendered = false;
      onReady(false);
    }

    function restore() {
      lost = false;
      previousTime = 0;
      resize();
    }

    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resize);
    if (observer) observer.observe(host);
    else window.addEventListener('resize', resize);
    area.addEventListener('pointermove', tilt, { passive: true });
    area.addEventListener('pointerleave', reset);
    area.addEventListener('pointercancel', reset);
    window.addEventListener('blur', reset);
    canvas.addEventListener('webglcontextlost', showFallback);
    canvas.addEventListener('webglcontextrestored', restore);
    resize();

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', resize);
      if (pending) cancelAnimationFrame(pending);
      area.removeEventListener('pointermove', tilt);
      area.removeEventListener('pointerleave', reset);
      area.removeEventListener('pointercancel', reset);
      window.removeEventListener('blur', reset);
      canvas.removeEventListener('webglcontextlost', showFallback);
      canvas.removeEventListener('webglcontextrestored', restore);
      dispose();
      renderer.dispose();
      if (!canvas.isConnected) renderer.forceContextLoss();
      onReady(false);
    };
  }, [onReady, pointerArea]);

  return <canvas ref={ref} aria-hidden="true" />;
}
