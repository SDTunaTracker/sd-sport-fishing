#!/usr/bin/env node
// Syntax-check every script the site ships: web/*.js and web/dist/*.js.
// Same check as `node --check`, done in one process with vm.Script (parse
// only, nothing runs), parsed as a classic browser script.
//
// Why: on 2026-11-26 web/metric-definitions.js shipped with an unescaped
// apostrophe ('... don't count ...'). The file failed to parse, so
// window.METRIC_DEFINITIONS was undefined and every boat page rendered
// nothing. No check caught it. `node --check` would have.
//
// Run: node scripts/check-js-syntax.mjs        (exit 0 = all parse, 1 = any fail)
// Used by scripts/verify-deploy.py (pre-commit hook) and
// .github/workflows/js-syntax.yml (pull requests).
import { Script } from 'node:vm';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dirs = ['web', join('web', 'dist')];

const files = [];
for (const d of dirs) {
  let names = [];
  try { names = readdirSync(join(root, d)); } catch { continue; }
  for (const n of names) {
    const p = join(root, d, n);
    if (n.endsWith('.js') && statSync(p).isFile()) files.push(p);
  }
}

const failures = [];
for (const f of files.sort()) {
  const rel = relative(root, f);
  try {
    new Script(readFileSync(f, 'utf8'), { filename: rel });   // compiles, never runs
  } catch (e) {
    // e.stack starts with "<file>:<line>", the source line, a caret, a blank
    // line, then "SyntaxError: ...". Keep those, drop the "at ..." frames.
    const lines = String(e.stack || e).split(/\r?\n/).filter(l => !/^\s+at /.test(l));
    // Long lines: show ~100 chars around the caret so the error stays visible.
    let [where = '', code = '', caret = ''] = lines;
    const at = caret.indexOf('^');
    if (code.length > 120 && at >= 0) {
      const from = Math.max(0, at - 70);
      code = (from ? '…' : '') + code.slice(from, at + 30) + (at + 30 < code.length ? '…' : '');
      caret = ' '.repeat(at - from + (from ? 1 : 0)) + '^';
    }
    const src = [where, code, caret];
    const msg = lines.find(l => /Error:/.test(l)) || String(e);
    failures.push({ file: rel, err: [...src, msg].join('\n    ') });
  }
}

if (failures.length) {
  const bar = '='.repeat(72);
  console.error(`\n${bar}\n❌ JS SYNTAX CHECK FAILED: ${failures.length} of ${files.length} shipped script(s) do not parse.`);
  console.error('   A browser stops at the first syntax error, so everything in these files is missing on the live site.\n');
  for (const { file, err } of failures) console.error(`  ✗ ${file}\n    ${err}\n`);
  console.error(`Fix the files above (for a .jsx bundle in web/dist/, fix the .jsx source and rebuild).\n${bar}\n`);
  process.exit(1);
}
console.log(`OK: all ${files.length} shipped scripts parse (syntax check of web/*.js and web/dist/*.js).`);
