// Minimal Cloudflare D1 binding backed by node:sqlite (Node >= 22.5), for tests
// and the local dev server. Supports prepare().bind().all()/run()/first() and batch().
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';

function norm(args) {
  return args.map(a => (a === undefined ? null : typeof a === 'boolean' ? (a ? 1 : 0) : a));
}

class Stmt {
  constructor(db, sql, args = []) { this.db = db; this.sql = sql; this.args = args; }
  bind(...args) { return new Stmt(this.db, this.sql, norm(args)); }
  _exec() {
    const st = this.db.prepare(this.sql);
    if (st.columns().length > 0) return { results: st.all(...this.args), success: true, meta: {} };
    const info = st.run(...this.args);
    return { results: [], success: true, meta: { changes: Number(info.changes) } };
  }
  async all() { return this._exec(); }
  async run() { return this._exec(); }
  async first(col) {
    const r = this._exec().results[0];
    if (!r) return null;
    return col ? r[col] : r;
  }
}

export function createD1(schemaPath, file = ':memory:') {
  const db = new DatabaseSync(file);
  if (schemaPath) db.exec(readFileSync(schemaPath, 'utf8'));
  return {
    _raw: db,
    prepare(sql) { return new Stmt(db, sql); },
    async batch(stmts) {
      db.exec('BEGIN');
      try {
        const out = stmts.map(s => s._exec());
        db.exec('COMMIT');
        return out;
      } catch (e) {
        db.exec('ROLLBACK');
        throw e;
      }
    },
    async exec(sql) { db.exec(sql); return { count: 1 }; },
  };
}
