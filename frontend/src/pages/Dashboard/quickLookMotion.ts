/** Find a fully visible thumbnail in the workspace, including the list's own scroll area. */
function visibleThumbnail(path: string) {
  const row = [...document.querySelectorAll<HTMLButtonElement>('.nfc-file-workspace-entries button[data-workspace-entry]')]
    .find(candidate => candidate.dataset.workspaceEntry === path && !candidate.disabled);
  const image = row?.querySelector<HTMLElement>('.nfc-file-workspace-entry-name .nfc-media-thumbnail');
  const bounds = image?.getBoundingClientRect();
  if (!bounds?.width || !bounds.height) return;

  const scroll = row?.closest('.nfc-file-workspace-list-scroll')?.getBoundingClientRect();
  if (bounds.left < Math.max(0, scroll?.left ?? 0) ||
      bounds.top < Math.max(0, scroll?.top ?? 0) ||
      bounds.right > Math.min(window.innerWidth, scroll?.right ?? window.innerWidth) ||
      bounds.bottom > Math.min(window.innerHeight, scroll?.bottom ?? window.innerHeight)) return;
  return bounds;
}

/** Project the dialog into the thumbnail's rectangle, or fade in place for an off-screen row. */
export function animateQuickLookPanel(panel: HTMLElement, path: string, opening: boolean, previous: Animation | null) {
  if (!panel.animate) return;
  const current = getComputedStyle(panel);
  // Read the actual frame before cancelling an interrupted entrance.
  const visualFrame = { transform: current.transform, opacity: current.opacity };
  previous?.cancel();

  const bounds = panel.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const expanded = { transform: getComputedStyle(panel).transform, opacity: 1 };
  const desktop = window.matchMedia('(min-width: 768px)').matches;
  const origin = desktop ? visibleThumbnail(path) : undefined;
  const base = expanded.transform === 'none' ? '' : expanded.transform + ' ';
  let collapsed = { transform: desktop ? expanded.transform : base + 'translateY(10px)', opacity: 0 };
  if (origin) {
    const dx = origin.left + origin.width / 2 - bounds.left - bounds.width / 2;
    const dy = origin.top + origin.height / 2 - bounds.top - bounds.height / 2;
    const scale = 'scale(' + origin.width / bounds.width + ',' + origin.height / bounds.height + ')';
    collapsed = { transform: base + 'translate(' + dx + 'px,' + dy + 'px) ' + scale, opacity: opening ? .66 : .12 };
  }
  return panel.animate(opening ? [collapsed, expanded] : [visualFrame, collapsed], {
    duration: origin ? opening ? 245 : 190 : 155,
    easing: 'cubic-bezier(.22,.7,.28,1)',
    fill: 'both',
  });
}
