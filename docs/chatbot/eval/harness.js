// Co-Captain eval harness.
// Loads web/data.js + chat-api.js in a fake `window`, sends each scripted
// conversation to the live chat proxy, and saves transcripts + an auto-score
// of every trip card against window.SD.SCHEDULE.
//
// Usage:  node docs/chatbot/eval/harness.js [caseId ...]
// Output: docs/chatbot/eval/runs/<timestamp>/<caseId>.json + summary.json
//
// Cost note: every turn is one real Claude call through the production worker.
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '../../..');
// CC_WEB_DIR: load the site files from another folder (e.g. copies downloaded
// from the live site) instead of this checkout's web/.
const WEB = process.env.CC_WEB_DIR || path.join(ROOT, 'web');
const PROXY = process.env.CHAT_PROXY_URL || 'https://chatbot.tylerjchristian.workers.dev';
const ORIGIN = process.env.CC_ORIGIN || 'http://localhost:8765';

function loadWindow() {
  const store = {};
  const ctx = {
    console, Intl, Date, Math, JSON, URLSearchParams, encodeURIComponent,
    localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } },
    fetch, TextDecoder,
    location: { search: '', hash: '', pathname: '/' }, document: { addEventListener() {}, querySelector() { return null; } },
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  for (const f of ['dates.js', 'feature-flags.js', 'regions.js', 'data.js', 'region-data.js', 'regulations.js', 'chat-api.js', 'analytics.js']) {
    vm.runInContext(fs.readFileSync(path.join(WEB, f), 'utf8'), ctx, { filename: f });
  }
  // Non-base regions (OC/LA, ...) live in data-region-<id>.js; merge them all.
  const regionFiles = (ctx.SD.META && ctx.SD.META.REGION_FILES) || {};
  for (const [id, f] of Object.entries(regionFiles)) {
    vm.runInContext(fs.readFileSync(path.join(WEB, f.file), 'utf8'), ctx, { filename: f.file });
    ctx.ttRegionData.adopt(id);
  }
  ctx.DEFAULT_FILTERS = {
    year: String(ctx.TT_DATES.getPacificYear()), month: 'all', landing: 'all', boat: 'all',
    tripLength: 'all', species: 'all', minTrips: 1, includeZero: true,
  };
  vm.runInContext('var DEFAULT_FILTERS = window.DEFAULT_FILTERS;', ctx);
  try { ctx.SDA.preprocessTrips(null); } catch (e) { /* app does this at startup */ }
  return ctx;
}

async function callBot(ctx, userMessage, history, regions) {
  // Mirror streamChatMessage() exactly, but with an Origin header (node has none).
  const body = {
    model: 'claude-opus-4-7', max_tokens: 1500, stream: true,
    system: ctx.buildSystemPrompt({ page: 'tripplanner', regions: regions || ['san_diego'] }),
    messages: [...history, { role: 'user', content: userMessage }],
  };
  const t0 = Date.now();
  const res = await fetch(PROXY, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Origin: ORIGIN },
    body: JSON.stringify(body),
  });
  if (!res.ok) return { error: `HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`, ms: Date.now() - t0 };
  const raw = await res.text();
  let text = '', firstTokenMs = null, usage = {};
  for (const line of raw.split('\n')) {
    if (!line.startsWith('data: ')) continue;
    try {
      const d = JSON.parse(line.slice(6));
      if (d.type === 'content_block_delta' && d.delta?.type === 'text_delta') text += d.delta.text || '';
      if (d.type === 'message_start') usage = { ...usage, ...d.message?.usage };
      if (d.type === 'message_delta') usage = { ...usage, ...d.usage };
    } catch (e) { /* ignore */ }
  }
  return { text, ms: Date.now() - t0, usage, systemChars: body.system.length };
}

// ---- scoring ------------------------------------------------------------
function pacificParts(iso) {
  // departureAt is either naive local ("2026-11-27T11:00:00") or UTC-offset (H&M).
  if (!/[zZ]|[+-]\d\d:\d\d$/.test(iso)) return { date: iso.slice(0, 10), time: iso.slice(11, 16) };
  const d = new Date(iso);
  const f = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(d);
  const g = t => f.find(p => p.type === t).value;
  return { date: `${g('year')}-${g('month')}-${g('day')}`, time: `${g('hour')}:${g('minute')}` };
}

// Rules every answer must follow, whatever the question.
const GLOBAL_PROSE_RULES = [
  { re: /forecast score|\b\d+(\.\d)?\s*\/\s*10\b|bite (outlook|forecast)|will (fish|bite) (best|well|better)|conditions (look|are rated)/i, why: 'forecast/prediction language' },
  { re: /^\s*\|.*\|\s*$/m, why: 'markdown table (UI renders raw pipes)' },
  { re: /(link|this) (will )?(book|reserve)s? (it|your|the)|takes you straight to .*reservation page/i, why: 'claims a link books/reserves' },
];

// External links in prose are only OK when they point at an official source
// listed in web/regulations.js (the regs answers cite those). Anything else
// (booking pages, made-up URLs) belongs on a card.
let ALLOWED_PROSE_URLS = new Set();
function proseUrlFails(prose) {
  const fails = [];
  const re = /\]\((https?:\/\/[^)\s]+)\)|(?<!\()\bhttps?:\/\/[^\s)]+/g;
  let m;
  while ((m = re.exec(prose))) {
    const url = (m[1] || m[0]).replace(/[.,;]+$/, '');
    if (!ALLOWED_PROSE_URLS.has(url)) fails.push(`external URL in prose not from regulations sources: ${url.slice(0, 80)}`);
  }
  return fails;
}

function scoreCards(ctx, text) {
  const cards = [];
  const re = /<trip-card>([\s\S]*?)<\/trip-card>/g;
  let m;
  while ((m = re.exec(text))) {
    let c;
    try { c = JSON.parse(m[1].trim()); } catch (e) { cards.push({ parseError: true, issues: ['card JSON parse error'] }); continue; }
    if (c.tripId !== undefined) {
      // New protocol: card is an id reference, hydrated from SCHEDULE by the client.
      const h = ctx.getTripCardData ? ctx.getTripCardData(c.tripId) : null;
      const issues = h ? [] : [`unknown tripId ${c.tripId} (card would be dropped)`];
      if (h && !h.bookingUrl && !h.landingPhone) issues.push('no booking path');
      cards.push({ tripId: c.tripId, hydrated: h, why: c.why || [], boat: h?.boat, date: h?.departDate, tripLength: h?.tripLength, price: h?.price, openSpots: h?.openSpots, landing: h?.landing, url: h?.bookingUrl, bookingKind: h?.bookingKind, issues });
      continue;
    }
    // Legacy protocol: model wrote the whole card.
    const sched = ctx.SD.SCHEDULE.filter(t => t.boat === c.boat && t.landing === c.landing);
    const sameDay = sched.filter(t => t.departureAt.slice(0, 10) === c.departureDate || pacificParts(t.departureAt).date === c.departureDate);
    const match = sameDay.find(t => !c.tripLength || t.tripLength === c.tripLength) || sameDay[0];
    const issues = ['legacy model-written card'];
    if (!sched.length) issues.push('boat/landing not in schedule');
    else if (!match) issues.push('no scheduled trip on that date');
    if (match) {
      const p = pacificParts(match.departureAt);
      if (p.date !== c.departureDate) issues.push(`wrong local date (real ${p.date})`);
      if (Math.round(match.price) !== Math.round(+c.price)) issues.push(`price ${c.price} vs ${match.price}`);
      if (c.openSpots != null && c.openSpots !== match.openSpots) issues.push(`spots ${c.openSpots} vs ${match.openSpots}`);
      if (match.landing === 'H&M Landing') issues.push('H&M link is boat page, not trip');
    }
    cards.push({ boat: c.boat, date: c.departureDate, tripLength: c.tripLength, price: c.price, url: c.bookingUrl, issues });
  }
  return cards;
}

// Per-turn expectations from cases.json `checks[turnIndex]`.
function scoreTurn(text, cards, check) {
  const prose = (text || '').replace(/<trip-card>[\s\S]*?<\/trip-card>/g, '').replace(/<followups>[\s\S]*?<\/followups>/g, '').replace(/<actions>[\s\S]*?<\/actions>/g, '');
  const fails = [];
  GLOBAL_PROSE_RULES.forEach(r => { if (r.re.test(prose)) fails.push(r.why); });
  fails.push(...proseUrlFails(prose));
  const ok = cards.filter(c => c.hydrated);
  if (cards.some(c => c.issues && c.issues.length)) fails.push(`${cards.filter(c => c.issues && c.issues.length).length} card(s) with issues`);
  if (cards.length > 3) fails.push(`${cards.length} cards (max 3)`);
  if (check) {
    if (check.minCards != null && ok.length < check.minCards) fails.push(`expected ≥${check.minCards} cards, got ${ok.length}`);
    if (check.maxCards != null && ok.length > check.maxCards) fails.push(`expected ≤${check.maxCards} cards, got ${ok.length}`);
    ok.forEach(c => {
      const h = c.hydrated;
      if (check.minSpots != null && h.openSpots < check.minSpots) fails.push(`${h.boat} ${h.departDate}: ${h.openSpots} spots < ${check.minSpots}`);
      if (check.maxPrice != null && h.price > check.maxPrice) fails.push(`${h.boat} ${h.departDate}: $${h.price} > $${check.maxPrice}`);
      if (check.dateFrom && h.departDate < check.dateFrom) fails.push(`${h.boat} departs ${h.departDate} < ${check.dateFrom}`);
      if (check.dateTo && h.departDate > check.dateTo) fails.push(`${h.boat} departs ${h.departDate} > ${check.dateTo}`);
      if (check.lengths && !check.lengths.includes(h.tripLength)) fails.push(`${h.boat} length ${h.tripLength} not in ${check.lengths.join('/')}`);
      if (check.boat && h.boat !== check.boat) fails.push(`expected boat ${check.boat}, got ${h.boat}`);
    });
    (check.mustSay || []).forEach(s => { if (!new RegExp(s, 'i').test(prose)) fails.push(`missing /${s}/`); });
    (check.mustNotSay || []).forEach(s => { if (new RegExp(s, 'i').test(prose)) fails.push(`said /${s}/`); });
  }
  return { pass: fails.length === 0, fails };
}

async function main() {
  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
  const only = process.argv.slice(2);
  const ctx = loadWindow();
  ALLOWED_PROSE_URLS = new Set(Object.values((ctx.TT_REGS && ctx.TT_REGS.sources) || {}).map(s => s.url));
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const outDir = path.join(__dirname, 'runs', stamp);
  fs.mkdirSync(outDir, { recursive: true });
  const summary = [];
  for (const c of cases.filter(c => !only.length || only.includes(c.id))) {
    const history = [];
    const turns = [];
    for (const [ti, u] of c.turns.entries()) {
      const r = await callBot(ctx, u, history, c.regions);
      const cards = r.text ? scoreCards(ctx, r.text) : [];
      const verdict = r.error ? { pass: false, fails: [r.error] } : scoreTurn(r.text, cards, (c.checks || [])[ti]);
      turns.push({ user: u, ...r, cards, verdict });
      history.push({ role: 'user', content: u }, { role: 'assistant', content: r.text || '' });
      process.stdout.write(`${verdict.pass ? 'PASS' : 'FAIL'} ${c.id}#${ti + 1}: ${cards.length} cards, ${r.ms}ms${verdict.fails.length ? ' | ' + verdict.fails.join('; ') : ''}\n`);
    }
    fs.writeFileSync(path.join(outDir, `${c.id}.json`), JSON.stringify({ case: c, turns }, null, 2));
    const allCards = turns.flatMap(t => t.cards);
    summary.push({
      id: c.id,
      turnsPassed: `${turns.filter(t => t.verdict.pass).length}/${turns.length}`,
      fails: turns.flatMap(t => t.verdict.fails),
      cards: allCards.length,
      cardsWithIssues: allCards.filter(x => x.parseError || (x.issues || []).length).length,
      ms: turns.map(t => t.ms),
      inputTokens: turns.map(t => t.usage?.input_tokens),
    });
  }
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  const tp = summary.reduce((n, s) => n + +s.turnsPassed.split('/')[0], 0);
  const tt = summary.reduce((n, s) => n + +s.turnsPassed.split('/')[1], 0);
  console.log(`\nAuto-checks: ${tp}/${tt} turns pass. Saved to ${outDir}`);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
module.exports = { loadWindow, scoreCards, scoreTurn, pacificParts };
