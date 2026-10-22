import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  captureRouteAccessibility, assessRouteAccessibility,
} from './route-accessibility-audit.mjs';

test('accepts named controls, decorative alt, unique references and native tabindex', () => {
  const result = assessRouteAccessibility({
    controls: [
      { element: 'button', name: '取消' },
      { element: 'input#query', name: '检索目录' },
      { element: 'a[href]', name: '返回' },
    ],
    refs: [
      { source: 'input#query', attribute: 'aria-labelledby',
        id: 'query-label', found: true, matches: 1 },
    ],
    images: [{ element: 'img', hasAlt: true }],
    positiveTabstops: [],
  });
  assert.deepEqual(result, {
    inspectedControls: 3, inspectedImages: 1,
    checkedAriaReferences: 1, positiveTabstops: 0, issues: [],
  });
});
test('rejects missing names, broken/duplicate ARIA refs, missing alt and positive tabindex', () => {
  const result = assessRouteAccessibility({
    controls: [{ element: 'button', name: ' ' }, { element: 'input#name', name: '' }],
    refs: [
      { source: 'button', attribute: 'aria-labelledby', id: 'missing',
        found: false, matches: 0 },
      { source: 'input#name', attribute: 'aria-describedby', id: 'dup',
        found: true, matches: 2 },
    ],
    images: [{ element: 'img', hasAlt: false }],
    positiveTabstops: [{ element: 'a', tabindex: '3' }],
  });
  assert.equal(result.issues.length, 6);
  for (const pattern of [
    /without accessible name: button/, /without accessible name: input#name/,
    /Broken aria-labelledby ID reference/, /Ambiguous aria-describedby ID reference/,
    /missing alt attribute/, /Positive tabindex disrupts/,
  ]) assert.ok(result.issues.some(message => pattern.test(message)), String(pattern));
});
test('mounted DOM snapshot inspects rendered native and ARIA control names', () => {
  const originalDocument = globalThis.document;
  const originalStyle = globalThis.getComputedStyle;
  const makeNode = (tagName, attrs = {}, textContent = '') => ({
    tagName: tagName.toUpperCase(),
    id: attrs.id ?? '', type: attrs.type ?? '',
    textContent, innerText: textContent, labels: [],
    getAttribute: key => attrs[key] ?? null,
    hasAttribute: key => Object.hasOwn(attrs, key),
    getClientRects: () => [1],
    closest: () => null, matches: () => false,
    querySelector: () => null,
  });
  const label = makeNode('span', { id: 'scan-label' }, '扫描路径');
  const input = makeNode('input', {
    id: 'scan-root', type: 'text', 'aria-labelledby': 'scan-label',
    'aria-describedby': 'scan-help',
  });
  const help = makeNode('p', { id: 'scan-help' }, '只读路径');
  const button = makeNode('button', { 'aria-label': '刷新扫描' });
  const unnamed = makeNode('button');
  const hidden = makeNode('button');
  hidden.closest = () => ({});
  const img = makeNode('img', { alt: '' });
  const nodes = [label, input, help, button, unnamed, hidden, img];
  globalThis.document = {
    getElementById: id => nodes.find(node => node.id === id) ?? null,
    querySelectorAll: selector => {
      if (selector === '[id]') return nodes.filter(node => node.id);
      if (selector === 'img') return [img];
      if (selector === '[tabindex]') return [];
      return [input, button, unnamed, hidden];
    },
  };
  globalThis.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
  try {
    const snapshot = captureRouteAccessibility();
    const audit = assessRouteAccessibility(snapshot);
    assert.equal(audit.inspectedControls, 3);
    assert.equal(audit.inspectedImages, 1);
    assert.equal(audit.checkedAriaReferences, 2);
    assert.deepEqual(audit.issues, [
      'Visible interactive control without accessible name: button',
    ]);
  } finally {
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
    if (originalStyle === undefined) delete globalThis.getComputedStyle;
    else globalThis.getComputedStyle = originalStyle;
  }
});
test('all real route and theme visits run fail-closed mounted a11y checks', () => {
  const visual = readFileSync('scripts/browser-full-route-visual.mjs', 'utf8');
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  const suite = readFileSync('scripts/run-tests.mjs', 'utf8');
  for (const phrase of [
    "import { captureRouteAccessibility, assessRouteAccessibility }",
    "tab.evaluate(captureRouteAccessibility)",
    "audit.accessibility = assessRouteAccessibility(a11ySnapshot)",
    "if (audit.accessibility.issues.length) problems.push(",
    "assert.deepEqual(failures, []",
    "if (request.method() !== 'GET')",
  ]) assert.ok(visual.includes(phrase), 'Missing real all-route guard: ' + phrase);
  assert.ok(workflow.includes('node scripts/browser-full-route-visual.mjs'));
  assert.ok(suite.includes('node --test scripts/route-accessibility-audit.test.mjs'));
});

test('Audit search has an explicit accessible name instead of placeholder-only labeling', () => {
  const auditPage = readFileSync('src/pages/Audit/index.tsx', 'utf8');
  assert.match(auditPage, /<input id="audit-search-input" type="search" value=\{searchText\}[\s\S]*?aria-label="搜索审计事件（操作或路径）"/);
  assert.match(auditPage, /placeholder="搜索操作\/路径\.\.\."/);
});
