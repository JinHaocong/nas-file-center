import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const asset = name => readFileSync(resolve(process.cwd(), 'public', name));

test('browser favicon SVG is consistently monochrome and remains an NAS device', () => {
  const svg = asset('favicon.svg').toString('utf8');
  assert.match(svg, /viewBox="0 0 128 128"/);
  assert.equal((svg.match(/<rect /g) || []).length, 4, 'one chassis and three drive bays');
  assert.equal((svg.match(/<circle /g) || []).length, 3, 'one status dot per drive');
  for (const hex of svg.match(/#[0-9a-f]{6}\b/gi) || []) {
    const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    assert.ok(Math.max(r, g, b) - Math.min(r, g, b) <= 6, `${hex} is not neutral`);
  }
  assert.doesNotMatch(svg, /linearGradient|filter=|#[0-9a-f]{3}(?![0-9a-f])/i);
});

test('legacy ICO contains crisp 16px and 32px PNG fallbacks', () => {
  const ico = asset('favicon.ico');
  assert.equal(ico.readUInt16LE(0), 0);
  assert.equal(ico.readUInt16LE(2), 1);
  const count = ico.readUInt16LE(4);
  assert.equal(count, 2);
  const sizes = [];
  for (let i = 0; i < count; i++) {
    const entry = 6 + i * 16;
    const side = ico[entry] || 256;
    sizes.push(side);
    assert.equal(ico[entry + 1] || 256, side);
    const bytes = ico.readUInt32LE(entry + 8);
    const offset = ico.readUInt32LE(entry + 12);
    assert.ok(offset + bytes <= ico.length);
    assert.equal(ico.subarray(offset, offset + 8).toString('hex'), '89504e470d0a1a0a');
  }
  assert.deepEqual(sizes, [16, 32]);
});

test('Apple touch icon is a 180px PNG and browser icon URLs use new cache keys', () => {
  const png = asset('apple-touch-icon.png');
  assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(png.readUInt32BE(16), 180);
  assert.equal(png.readUInt32BE(20), 180);
  const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8');
  for (const name of ['favicon.svg', 'favicon.ico', 'apple-touch-icon.png']) {
    assert.ok(html.includes(`/${name}?v=mono1`), name + ' cache key');
  }
});
