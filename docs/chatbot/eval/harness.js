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
const WEB = path.join(ROOT, 'web');
const PROXY = process.env.CHAT_PROXY_URL || 'https://chatbot.tylerjchristian.workers.dev';
const ORIGIN = 'http://localhost:8765';

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
  for (const f of ['dates.js', 'feature-flags.js', 'regions.js', 'data.js', 'chat-api.js', 'analytics.js']) {
    vm.runInContext(fs.readFileSync(path.join(WEB, f), 'utf8'), ctx, { filename: f });
  }
  ctx.DEFAULT_FILTERS = {
    year: String(ctx.TT_DATES.getPacificYear()), month: 'all', landing: 'all', boat: 'all',
    tripLength: 'all', species: 'all', minTrips: 1, includeZero: true,
  };
  vm.runInContext('var DEFAULT_FILTERS = window.DEFAULT_FILTERS;', ctx);
  return ctx;
}

async function callBot(ctx, userMessage, history) {
  // Mirror streamChatMessage() exactly, but with an Origin header (node has none).
  const body = {
    model: 'claude-opus-4-7', max_tokens: 1500, stream: true,
    system: ctx.buildSystemPrompt({ page: 'tripplanner', regions: ['san_diego'] }),
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

function scoreCards(ctx, text) {
  const cards = [];
  const re = /<trip-card>([\s\S]*?)<\/trip-card>/g;
  let m;
  while ((m = re.exec(text))) {
    let c;
    try { c = JSON.parse(m[1].trim()); } catch (e) { cards.push({ parseError: true }); continue; }
    const sched = ctx.SD.SCHEDULE.filter(t => t.boat === c.boat && t.landing === c.landing);
    // Match on the date the bot claims (it copies the sliced UTC date for H&M).
    const sameDay = sched.filter(t => t.departureAt.slice(0, 10) === c.departureDate || pacificParts(t.departureAt).date === c.departureDate);
    const match = sameDay.find(t => !c.tripLength || t.tripLength === c.tripLength) || sameDay[0];
    const issues = [];
    if (!sched.length) issues.push('boat/landing not in schedule');
    else if (!match) issues.push('no scheduled trip on that date');
    if (match) {
      const p = pacificParts(match.departureAt);
      if (p.date !== c.departureDate) issues.push(`wrong local date (real ${p.date})`);
      if (Math.round(match.price) !== Math.round(+c.price)) issues.push(`price ${c.price} vs ${match.price}`);
      if (c.openSpots != null && c.openSpots !== match.openSpots) issues.push(`spots ${c.openSpots} vs ${match.openSpots}`);
      const expectedUrl = ctx.buildBookingUrl(match);
      if (!c.bookingUrl) issues.push('no booking url');
      else if (c.bookingUrl !== expectedUrl) issues.push('booking url differs from buildBookingUrl()');
      if (match.landing === 'H&M Landing') issues.push('H&M link is boat page, not trip');
    }
    cards.push({ boat: c.boat, date: c.departureDate, tripLength: c.tripLength, price: c.price, url: c.bookingUrl, issues });
  }
  return cards;
}

async function main() {
  const cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
  const only = process.argv.slice(2);
  const ctx = loadWindow();
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const outDir = path.join(__dirname, 'runs', stamp);
  fs.mkdirSync(outDir, { recursive: true });
  const summary = [];
  for (const c of cases.filter(c => !only.length || only.includes(c.id))) {
    const history = [];
    const turns = [];
    for (const u of c.turns) {
      const r = await callBot(ctx, u, history);
      const cards = r.text ? scoreCards(ctx, r.text) : [];
      turns.push({ user: u, ...r, cards });
      history.push({ role: 'user', content: u }, { role: 'assistant', content: r.text || '' });
      process.stdout.write(`${c.id}: ${r.error ? 'ERR ' + r.error : `${cards.length} cards, ${r.ms}ms`}\n`);
    }
    fs.writeFileSync(path.join(outDir, `${c.id}.json`), JSON.stringify({ case: c, turns }, null, 2));
    const allCards = turns.flatMap(t => t.cards);
    summary.push({
      id: c.id,
      cards: allCards.length,
      cardsWithIssues: allCards.filter(x => x.parseError || x.issues.length).length,
      ms: turns.map(t => t.ms),
      inputTokens: turns.map(t => t.usage?.input_tokens),
    });
  }
  fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('Saved to', outDir);
}

if (require.main === module) main().catch(e => { console.error(e); process.exit(1); });
module.exports = { loadWindow, scoreCards, pacificParts };
