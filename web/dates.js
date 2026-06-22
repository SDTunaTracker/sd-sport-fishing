// Pacific-time date helpers — exposed as window.TT_DATES.
//
// Background: the scraper runs in UTC (GitHub Actions), and naive
// new Date().toISOString().slice(0,10) returns the *UTC* calendar date.
// After ~5pm Pacific, UTC is already on the next day, so the homepage
// header showed "tomorrow" and the Today's Report filter found nothing.
//
// All "today" semantics in the frontend should go through these helpers
// so PDT/PST is auto-handled by Intl.DateTimeFormat.
(function (root) {
  function getPacificDate(d) {
    var src = d || new Date();
    // 'en-CA' formats as YYYY-MM-DD with a fixed-width zero-padded layout.
    return new Intl.DateTimeFormat('en-CA', {
      timeZone: 'America/Los_Angeles',
      year:  'numeric',
      month: '2-digit',
      day:   '2-digit',
    }).format(src);
  }

  function getPacificHour(d) {
    var src = d || new Date();
    var parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Los_Angeles',
      hour:    'numeric',
      hour12:  false,
    }).formatToParts(src);
    var h = (parts.find(function (p) { return p.type === 'hour'; }) || {}).value;
    // Some runtimes report midnight as "24"; normalize to 0.
    var n = Number(h);
    return n === 24 ? 0 : n;
  }

  function getPacificYear(d) {
    return Number(getPacificDate(d).slice(0, 4));
  }

  function getPacificMonth(d) {
    // 1-12 to match Python's .month / our analytics layer
    return Number(getPacificDate(d).slice(5, 7));
  }

  function pacificDateOffsetDays(daysDelta, base) {
    // Add (or subtract) whole days from today's Pacific calendar date.
    // Uses milliseconds-from-base then re-formats in Pacific, so the result
    // is the Pacific date that corresponds to that moment.
    var anchor = base ? new Date(base.getTime()) : new Date();
    anchor.setTime(anchor.getTime() + daysDelta * 86400000);
    return getPacificDate(anchor);
  }

  root.TT_DATES = {
    getPacificDate:        getPacificDate,
    getPacificHour:        getPacificHour,
    getPacificYear:        getPacificYear,
    getPacificMonth:       getPacificMonth,
    pacificDateOffsetDays: pacificDateOffsetDays,
  };
})(typeof window !== 'undefined' ? window : this);
