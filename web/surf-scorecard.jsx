// surf-scorecard.jsx: the public Surftracker accuracy scorecard (round 11).
// Breaking surf height only, scored against people's observed reports, with the
// NWS Surf Zone Forecast on the same days for comparison. Data: surf.json
// verification.scorecard (src/surf/forecast.py VERIFICATION).

function SurfScorecard({ card }) {
  if (!card || !card.rows || !card.rows.length) return null;
  const pct = x => `${Math.round(x * 100)}%`;
  const ft = x => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x).toFixed(1)} ft`;
  return (
    <div className="sfs" role="region" aria-label="Surf height accuracy scorecard">
      <div className="sfs-h">Scorecard · breaking surf height vs observed</div>
      <table className="sfs-t">
        <thead><tr><th scope="col"></th><th scope="col">Bias</th><th scope="col">Typical error</th><th scope="col">Within 1.5 ft</th></tr></thead>
        <tbody>
          {card.rows.map(r => (
            <tr key={r.who}><th scope="row">{r.who}</th><td>{ft(r.biasFt)}</td><td>{r.rmseFt.toFixed(1)} ft</td><td>{pct(r.within1_5)}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="sfs-note">{card.truth} Bias below zero means lower than observed. Typical error is the root-mean-square.</p>
      {card.notYet && card.notYet.length > 0 && (
        <p className="sfs-note"><b>Not yet checked:</b> {card.notYet.join('; ')}.</p>
      )}
    </div>
  );
}

window.SurfScorecard = SurfScorecard;
