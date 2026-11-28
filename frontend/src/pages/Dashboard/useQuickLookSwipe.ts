import { useLayoutEffect, useRef } from 'react';

import type { PointerEvent } from 'react';

type SwipeDirection = -1 | 1;

interface SwipeOptions {
  path: string | null;
  motion: boolean;
  previous: boolean;
  next: boolean;
  onStep: (direction: SwipeDirection) => void;
}

interface Gesture {
  id: number;
  x: number;
  y: number;
  width: number;
  horizontal: boolean;
  offset: number;
}

const swipeThreshold = 42;
const directionThreshold = 8;
const directionRatio = 1.3;
const resistance = .24;

/** Move the artwork by the gesture offset without rerendering its controls. */
export function useQuickLookSwipe({ path, motion, previous, next, onStep }: SwipeOptions) {
  const track = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const settlement = useRef<Animation | null>(null);

  /** Clear drag state whenever selection, motion preference or view lifecycle changes. */
  function reset(element = track.current) {
    gesture.current = null;
    settlement.current?.cancel();
    settlement.current = null;
    if (element) {
      delete element.dataset.sliding;
      element.style.removeProperty('transform');
    }
  }

  useLayoutEffect(() => {
    reset();
    return () => reset();
  }, [path, motion]);

  /** Keep navigation anchored to the pointer until a commit or a bounce has settled. */
  function settle(offset: number, width: number, direction?: SwipeDirection) {
    const element = track.current;
    const target = (direction ? -direction : 0) * width;
    if (!motion || !element?.animate || offset === target) {
      reset();
      if (direction) onStep(direction);
      return;
    }

    const animation = element.animate(
      [{ transform: 'translate3d(' + offset + 'px,0,0)' }, { transform: 'translate3d(' + target + 'px,0,0)' }],
      { duration: direction ? 215 : 185, easing: 'cubic-bezier(.22,.7,.28,1)', fill: 'both' },
    );
    settlement.current = animation;
    // Keep the final position until the next selection mounts to avoid a flash back to the old file.
    void animation.finished.then(() => {
      if (direction) onStep(direction);
      else reset(element);
    }, () => {});
  }

  /** Record a potential touch drag without capturing a vertical pan or a tap. */
  function start(event: PointerEvent<HTMLDivElement>) {
    if (!event.isPrimary || event.pointerType === 'mouse' || settlement.current ||
        (event.target as Element).closest('button')) return;
    gesture.current = {
      id: event.pointerId, x: event.clientX, y: event.clientY,
      width: event.currentTarget.clientWidth, horizontal: false, offset: 0,
    };
  }

  /** Lock a recognized horizontal swipe and leave vertical movement to the browser. */
  function move(event: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (!active || active.id !== event.pointerId) return;

    const dx = event.clientX - active.x;
    const dy = event.clientY - active.y;
    if (!active.horizontal) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < directionThreshold) return;
      if (Math.abs(dx) <= Math.abs(dy) * directionRatio) {
        gesture.current = null;
        return;
      }
      active.horizontal = true;
      event.currentTarget.setPointerCapture?.(event.pointerId);
    }
    const canStep = dx > 0 ? previous : next;
    const limit = active.width;
    active.offset = Math.max(-limit, Math.min(limit, dx)) * (canStep ? 1 : resistance);
    if (motion && track.current) {
      track.current.dataset.sliding = '';
      track.current.style.transform = 'translate3d(' + active.offset + 'px,0,0)';
    }
  }

  /** Commit a horizontal drag that crosses the threshold and has a neighboring file. */
  function end(event: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (!active || active.id !== event.pointerId) return;
    gesture.current = null;
    if (!active.horizontal) return;

    const distance = event.clientX - active.x;
    const direction: SwipeDirection = distance > 0 ? -1 : 1;
    const commit = Math.abs(distance) > swipeThreshold && (direction === -1 ? previous : next);
    settle(active.offset, active.width, commit ? direction : undefined);
  }

  /** Bounce cancelled drags back to the current file. */
  function cancel(event: PointerEvent<HTMLDivElement>) {
    const active = gesture.current;
    if (!active || active.id !== event.pointerId) return;
    gesture.current = null;
    if (active.horizontal) settle(active.offset, active.width);
  }

  return {
    track, reset,
    onPointerDown: start, onPointerMove: move, onPointerUp: end,
    onPointerCancel: cancel, onLostPointerCapture: cancel,
  };
}
