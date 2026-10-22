/**
 * Snapshot mounted, visible controls on the ACTUAL React page (not TSX guesses).
 * This function is serialized into Chromium by Playwright page.evaluate().
 * All browser-side dependencies are local; the audit never calls fetch or APIs.
 *
 * Scope: programmatic names, broken label references, image alternatives and
 * forbidden positive tabindex. Not a substitute for screen-reader/owner review.
 */
export function captureRouteAccessibility() {
  const controls = [];
  const refs = [];
  const idCounts = new Map();
  for (const node of document.querySelectorAll('[id]'))
    idCounts.set(node.id, (idCounts.get(node.id) || 0) + 1);
  const images = [];
  const positiveTabstops = [];
  const interactive = 'button,a[href],input:not([type="hidden"]),select,textarea,' +
    '[role="button"],[role="link"],[role="tab"],[role="menuitem"],' +
    '[role="checkbox"],[role="radio"],[role="switch"]';
  const norm = text => (text ?? '').replace(/\s+/g, ' ').trim();
  const visible = node => {
    if (node.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
    if (!node.getClientRects().length) return false;
    const style = getComputedStyle(node);
    return style.display !== 'none' &&
      style.visibility !== 'hidden' && style.visibility !== 'collapse';
  };
  const describe = node => {
    const tag = node.tagName.toLowerCase();
    const id = node.id ? '#' + node.id : '';
    const type = node.getAttribute('type');
    const role = node.getAttribute('role');
    return tag + id + (type ? '[type=' + type + ']' : '') +
      (role ? '[role=' + role + ']' : '');
  };
  const referenced = (node, attribute) => {
    const ids = norm(node.getAttribute(attribute)).split(' ').filter(Boolean);
    if (ids.length) {
      for (const id of ids) {
        const found = document.getElementById(id);
        refs.push({
          source: describe(node), attribute, id, found: Boolean(found),
          // Duplicate referenced IDs cause ambiguous associations.
          matches: idCounts.get(id) || 0,
        });
      }
    }
    return ids.map(id => document.getElementById(id))
      .filter(Boolean).map(node => norm(node.textContent)).filter(Boolean).join(' ');
  };
  const nameFor = node => {
    const labelledBy = referenced(node, 'aria-labelledby');
    referenced(node, 'aria-describedby');
    if (node.hasAttribute('aria-labelledby')) return labelledBy;
    const aria = norm(node.getAttribute('aria-label'));
    if (aria) return aria;
    const labels = node.labels ? [...node.labels] : [];
    if (labels.length) {
      const fromLabels = norm(labels.map(label => label.textContent).join(' '));
      if (fromLabels) return fromLabels;
    }
    const enclosing = node.closest('label');
    if (enclosing) {
      const fromLabel = norm(enclosing.textContent);
      if (fromLabel) return fromLabel;
    }
    if (node.tagName.toLowerCase() === 'input') {
      const type = node.type?.toLowerCase() ?? '';
      if (type === 'submit' || type === 'reset' || type === 'button')
        return norm(node.value) || (type === 'submit' ? 'Submit' : type === 'reset' ? 'Reset' : '');
      if (type === 'image') return norm(node.getAttribute('alt'));
    }
    const text = norm(node.innerText || node.textContent);
    if (text) return text;
    const image = node.querySelector('img[alt]');
    if (image) return norm(image.getAttribute('alt'));
    const svgTitle = node.querySelector('svg title');
    if (svgTitle) return norm(svgTitle.textContent);
    return norm(node.getAttribute('title'));
  };
  // Only inspect currently rendered controls. Include disabled controls: they
  // still need understandable names even when temporarily non-operable.
  for (const node of document.querySelectorAll(interactive)) {
    if (!visible(node)) continue;
    controls.push({ element: describe(node), name: nameFor(node) });
    const tabindex = node.getAttribute('tabindex');
    if (tabindex !== null && Number(tabindex) > 0)
      positiveTabstops.push({ element: describe(node), tabindex });
  }
  for (const node of document.querySelectorAll('img')) {
    if (!visible(node)) continue;
    if (node.getAttribute('role') === 'presentation' ||
        node.getAttribute('role') === 'none') continue;
    images.push({ element: describe(node), hasAlt: node.hasAttribute('alt') });
  }
  for (const node of document.querySelectorAll('[tabindex]')) {
    if (!visible(node) || node.matches(interactive)) continue;
    if (Number(node.getAttribute('tabindex')) > 0)
      positiveTabstops.push({ element: describe(node),
        tabindex: node.getAttribute('tabindex') });
  }
  return { controls, refs, images, positiveTabstops };
}

export function assessRouteAccessibility(snapshot) {
  const issues = [];
  for (const control of snapshot.controls) {
    if (!control.name.trim())
      issues.push('Visible interactive control without accessible name: ' + control.element);
  }
  for (const ref of snapshot.refs) {
    if (!ref.found)
      issues.push('Broken ' + ref.attribute + ' ID reference: ' + ref.source + ' -> #' + ref.id);
    else if (ref.matches !== 1)
      issues.push('Ambiguous ' + ref.attribute + ' ID reference: ' + ref.source +
        ' -> #' + ref.id + ' count=' + ref.matches);
  }
  for (const img of snapshot.images) {
    if (!img.hasAlt)
      issues.push('Visible image missing alt attribute: ' + img.element);
  }
  for (const node of snapshot.positiveTabstops) {
    issues.push('Positive tabindex disrupts native keyboard order: ' +
      node.element + ' tabindex=' + node.tabindex);
  }
  return {
    inspectedControls: snapshot.controls.length,
    inspectedImages: snapshot.images.length,
    checkedAriaReferences: snapshot.refs.length,
    positiveTabstops: snapshot.positiveTabstops.length,
    issues,
  };
}
