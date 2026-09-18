import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 C2A visual prototype contract', () => {
  test('sidebar groups navigation by product domain instead of one flat menu', () => {
    const source = read('src/components/Sidebar.tsx');
    assert.match(source, /type:\s*['"]group['"]/);
    for (const label of ['数据与扫描', '文件工具', '自动化', '安全与运行', '系统']) {
      assert.match(source, new RegExp(label));
    }
  });

  test('dashboard uses product primitives and removes legacy dashboard-template visuals', () => {
    const source = read('src/pages/Dashboard/index.tsx');
    assert.match(source, /PageHeader/);
    assert.match(source, /MetricCard/);
    assert.match(source, /DataPanel/);
    assert.match(source, /StatusBadge/);
    assert.match(source, /useResponsive/);
    assert.doesNotMatch(source, /ReactECharts/);
    assert.doesNotMatch(source, /type=["']inner["']/);
  });

  test('dashboard preserves snapshot freshness and operational entry points', () => {
    const source = read('src/pages/Dashboard/index.tsx');
    assert.match(source, /扫描快照/);
    assert.match(source, /最近一次扫描发现/);
    assert.match(source, /最近一次扫描预计可释放/);
    assert.match(source, /navigate\(['"]\/scans['"]\)/);
    assert.match(source, /navigate\(['"]\/tasks['"]\)/);
    assert.match(source, /navigate\(['"]\/indexes['"]\)/);
    assert.match(source, /navigate\(['"]\/organizer['"]\)/);
  });

  test('mobile dashboard renders activity as cards instead of squeezing desktop tables', () => {
    const source = read('src/pages/Dashboard/index.tsx');
    assert.match(source, /isMobile/);
    assert.match(source, /nfc-mobile-activity-card/);
    assert.match(source, /nfc-mobile-activity-list/);
  });

  test('visual layer uses hairline panels, grouped nav labels and restrained surfaces', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-page-header',
      '.nfc-metric-grid',
      '.nfc-metric-card',
      '.nfc-data-panel',
      '.nfc-quick-action',
      '.nfc-mobile-activity-card',
      '.nfc-nav-group-label',
    ]) {
      assert.match(css, new RegExp(selector.replace('.', '\\.')));
    }
    assert.match(css, /border:\s*1px solid var\(--nfc-hairline\)/);
  });

  test('dashboard no longer hardcodes the old Ant Design dashboard palette', () => {
    const source = read('src/pages/Dashboard/index.tsx');
    for (const hex of ['#1677ff', '#52c41a', '#fa8c16', '#722ed1']) {
      assert.doesNotMatch(source, new RegExp(hex, 'i'));
    }
  });
});
