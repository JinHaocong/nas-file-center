/**
 * Stage only the eight exact-HEAD GitHub Actions full-route artifacts into
 * the layout expected by build-visual-review-pack.mjs.
 *
 * actions/download-artifact (merge-multiple: false) extracts each artifact
 * into a directory named exactly "full-route-visual-<width>-<HEAD>".
 * Reject missing, mixed-HEAD, duplicate and unexpected downloads before
 * moving any files. build-visual-review-pack then validates every manifest.
 */
import assert from 'node:assert/strict';
import {
  existsSync, mkdirSync, readdirSync, renameSync,
} from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { visualViewports } from './visual-fixtures.mjs';

export function stageVisualArtifacts(downloadDir, destination, expectedHeadSha) {
  assert.match(expectedHeadSha || '', /^[a-f0-9]{40}$/,
    'Expected a full exact GitHub pull request HEAD SHA');
  const input = resolve(downloadDir);
  const output = resolve(destination);
  assert.notEqual(input, output, 'Input and output directories must differ');
  assert.ok(existsSync(input), 'Missing downloaded artifact directory: ' + input);
  assert.ok(!existsSync(output), 'Refusing to overwrite an existing evidence directory');
  const entries = readdirSync(input, { withFileTypes: true });
  const widths = [...visualViewports];
  assert.equal(entries.length, widths.length,
    'Expected exactly eight standalone GitHub Action artifacts');
  const folders = new Map();
  for (const entry of entries) {
    assert.ok(entry.isDirectory(), 'Unexpected file/link in artifact download: ' + entry.name);
    const match = /^full-route-visual-(\d+)-([a-f0-9]{40})$/.exec(entry.name);
    assert.ok(match, 'Unexpected artifact directory name: ' + entry.name);
    const width = Number(match[1]);
    assert.ok(widths.includes(width), 'Unexpected viewport width: ' + width);
    assert.equal(match[2], expectedHeadSha, 'Mixed or stale PR HEAD artifact: ' + entry.name);
    assert.ok(!folders.has(width), 'Duplicate viewport artifact: ' + width);
    folders.set(width, entry.name);
  }
  assert.deepEqual([...folders.keys()].sort((a, b) => a - b),
    widths.sort((a, b) => a - b), 'Width coverage incomplete');
  // No writes until every artifact filename/HEAD has passed validation.
  mkdirSync(output, { recursive: true });
  for (const width of widths) {
    renameSync(join(input, folders.get(width)), join(output, String(width)));
  }
  return widths.length;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const count = stageVisualArtifacts(process.argv[2], process.argv[3], process.argv[4]);
    console.log('Staged ' + count + ' exact-HEAD viewport artifacts for offline human review');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  }
}
