/** Wait until the open Radix layer actually owns the point the browser audit inspects. */
export async function waitForInteractivePortal(page, selector, point = 'dialog') {
  await page.waitForFunction(({ sel, point }) => {
    const dialog = document.querySelector(sel);
    if (!dialog || getComputedStyle(dialog).visibility !== 'visible' ||
        dialog.getAttribute('data-state') !== 'open') return false;
    const box = dialog.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return false;
    const offset = point === 'picker' ? Math.min(70, box.height / 3) : Math.min(100, box.height / 2);
    const x = point === 'viewport' ? innerWidth / 2 :
      Math.max(1, Math.min(innerWidth - 1, box.left + box.width / 2));
    const y = point === 'viewport' ? innerHeight / 2 :
      Math.max(1, Math.min(innerHeight - 1, box.top + offset));
    return Boolean(document.elementFromPoint(x, y)?.closest(sel));
  }, { sel: selector, point }, { timeout: 3500, polling: 'raf' });
}
