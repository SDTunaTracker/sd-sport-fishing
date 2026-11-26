// AI Fishing Advisor chatbot component.
// Requires chat-api.js to be loaded first.
(function () {

const { useState, useEffect, useRef, Fragment } = React;

const STATUS_MESSAGES = [
  "Checking upcoming trips...",
  "Reading recent fish counts...",
  "Matching trips to what you asked...",
];

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T12:00:00');
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}

function renderInlineText(text, key) {
  const lines = text.split('\n');
  return (
    <span key={key}>
      {lines.map((line, li) => {
        const boldParts = line.split(/(\*\*[^*]+\*\*)/);
        return (
          <span key={li}>
            {li > 0 && <br />}
            {boldParts.map((part, pi) =>
              part.startsWith('**') && part.endsWith('**')
                ? <strong key={pi}>{part.slice(2, -2)}</strong>
                : part
            )}
          </span>
        );
      })}
    </span>
  );
}

function renderMessageContent(text, onInternalNav) {
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  const parts = [];
  let lastIndex = 0;
  let match;
  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push({ type: 'text', value: text.slice(lastIndex, match.index) });
    parts.push({ type: 'link', label: match[1], url: match[2] });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push({ type: 'text', value: text.slice(lastIndex) });

  return parts.map((part, i) => {
    if (part.type === 'link') {
      const isExternal = part.url.startsWith('http');
      return (
        <a
          key={i}
          href={part.url}
          target={isExternal ? '_blank' : undefined}
          rel={isExternal ? 'noopener noreferrer' : undefined}
          className={`chat-link${isExternal ? ' external' : ' internal'}`}
          onClick={() => {
            if (window.TTTrack?.chatLinkClick) TTTrack.chatLinkClick(part.label, part.url, isExternal);
            if (!isExternal && onInternalNav) onInternalNav();
          }}
        >{part.label}</a>
      );
    }
    return renderInlineText(part.value, i);
  });
}

function cleanStreamingText(text) {
  let clean = text;
  // Strip complete followups/actions blocks — they're rendered as UI, not raw text
  clean = clean.replace(/<followups>[\s\S]*?<\/followups>/g, '');
  clean = clean.replace(/<actions>[\s\S]*?<\/actions>/g, '');
  // Hide any tag that opened but hasn't closed yet (still buffering)
  for (const tag of ['trip-card', 'followups', 'actions']) {
    const openIdx  = clean.lastIndexOf(`<${tag}>`);
    const closeIdx = clean.lastIndexOf(`</${tag}>`);
    if (openIdx > closeIdx) clean = clean.substring(0, openIdx);
  }
  return clean.trim();
}

function isBufferingCard(text) {
  const openIdx  = text.lastIndexOf('<trip-card>');
  const closeIdx = text.lastIndexOf('</trip-card>');
  return openIdx > closeIdx;
}

function parseMessageWithCards(text) {
  const cardRegex = /<trip-card>([\s\S]*?)<\/trip-card>/g;
  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = cardRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: text.slice(lastIndex, match.index) });
    }
    try {
      const ref = JSON.parse(match[1].trim());
      // Grounding: the model only references a trip by id. Everything shown is
      // filled from window.SD.SCHEDULE; an unknown id (or a card the model wrote
      // out by hand) is dropped rather than rendered.
      const trip = ref && ref.tripId && window.getTripCardData ? window.getTripCardData(ref.tripId) : null;
      if (trip) {
        const why = Array.isArray(ref.why) ? ref.why.filter(w => typeof w === 'string').slice(0, 3) : [];
        parts.push({ type: 'trip', data: { ...trip, why } });
      } else {
        console.warn('[Co-Captain] dropped trip-card with unknown tripId:', ref && ref.tripId);
      }
    } catch(e) {
      // Malformed JSON — log for debugging but don't render raw tag text.
      console.warn('[Co-Captain] trip-card JSON parse failed:', e.message, match[1].slice(0, 80));
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    const trailing = text.slice(lastIndex);
    // Strip any raw <trip-card> tags the regex missed (mobile safety net).
    const stripped = trailing.replace(/<trip-card>[\s\S]*?<\/trip-card>/g, '');
    if (stripped.trim()) parts.push({ type: 'text', content: stripped });
  }

  return parts;
}

const LANDING_SHORT = {
  'H&M Landing': 'H&M Landing', "Fisherman's Landing": "Fisherman's Landing",
  'Point Loma Sportfishing': 'Point Loma', 'Seaforth Sportfishing': 'Seaforth',
};

function asOfLabel(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('en-US', { timeZone: 'America/Los_Angeles', weekday: 'short', hour: 'numeric', minute: '2-digit' });
  } catch (e) { return ''; }
}

function readSaved() {
  try { return JSON.parse(localStorage.getItem('tt_saved_trips') || '[]'); } catch (e) { return []; }
}
function writeSaved(list) {
  try { localStorage.setItem('tt_saved_trips', JSON.stringify(list.slice(-50))); } catch (e) {}
}

function shareText(trip) {
  const lines = [
    `${trip.boat} (${LANDING_SHORT[trip.landing] || trip.landing}), ${trip.tripLength}`,
    `Departs ${trip.departLabel}`,
    trip.price != null ? `$${trip.price}/person` : null,
    trip.openSpots != null ? `${trip.openSpots} spots open as of ${asOfLabel(trip.spotsAsOf)}` : null,
  ].filter(Boolean);
  return lines.join(' · ');
}

function track(name, payload) {
  try { if (window.TTTrack && TTTrack[name]) TTTrack[name](payload); } catch (e) {}
}

function ChatTripCard({ trip, position, msgIndex, onAsk, compact }) {
  const { useState: useS } = React;
  const [stage, setStage] = useS('card');        // card → summary (booking hand-off)
  const [live, setLive] = useS(null);            // null | 'checking' | {open, checkedAt} | 'unknown'
  const [saved, setSaved] = useS(() => readSaved().includes(trip.tripId));
  const [shareMsg, setShareMsg] = useS('');
  const landingName = LANDING_SHORT[trip.landing] || trip.landing;
  const asOf = asOfLabel(trip.spotsAsOf);
  const ctx = { tripId: trip.tripId, boat: trip.boat, landing: trip.landing, tripLength: trip.tripLength, price: trip.price, position, msgIndex, bookingKind: trip.bookingKind };

  function toggleSave() {
    const list = readSaved().filter(id => id !== trip.tripId);
    if (!saved) list.push(trip.tripId);
    writeSaved(list);
    setSaved(!saved);
    track('chatSave', { ...ctx, saved: !saved });
  }

  async function share() {
    const text = shareText(trip);
    const url = trip.bookingUrl || `https://thetunatracker.com/${trip.boatPageUrl}`;
    track('chatShare', ctx);
    try {
      if (navigator.share) { await navigator.share({ title: `${trip.boat}: ${trip.departLabel}`, text, url }); return; }
      await navigator.clipboard.writeText(`${text}\n${url}`);
      setShareMsg('Copied. Paste it to your group.');
    } catch (e) {
      if (e && e.name === 'AbortError') return;
      setShareMsg('Couldn’t share. Long-press the Book link to copy it.');
    }
    setTimeout(() => setShareMsg(''), 4000);
  }

  function openSummary() {
    setStage('summary');
    track('chatBookIntent', ctx);
    if (window.getLiveSpots && live === null && trip.landing === 'H&M Landing') {
      setLive('checking');
      window.getLiveSpots(trip.tripId).then(r => {
        setLive(r || 'unknown');
        if (r) track('chatLiveCheck', { ...ctx, liveOpen: r.open });
      });
    }
  }

  const soldOut = live && typeof live === 'object' && live.open === 0;
  const liveLine = live === 'checking' ? 'Checking live availability…'
    : live && typeof live === 'object'
      ? (live.open === 0 ? 'Sold out right now (it filled after our last update).'
        : `${live.open} spots open right now (checked live).`)
      : null;

  function handOff() {
    track('chatBookClick', ctx);
    if (window.TTTrack?.chatLinkClick) TTTrack.chatLinkClick('Book', trip.bookingUrl, true);
  }

  const handOffCopy = trip.bookingKind === 'exact_trip'
    ? (trip.landing === 'H&M Landing'
        ? `Opens H&M Landing's booking checkout (Xola) with this departure already selected. You'll choose guests, then finish booking and pay there.`
        : `Opens ${landingName}'s reservation page for this exact trip. You'll finish booking and pay there.`)
    : trip.bookingKind === 'trip_list'
      ? `Opens ${landingName}'s list of upcoming trips. Find the ${trip.boat} on ${trip.departLabel.split(' ').slice(0, 2).join(' ')}, then finish booking and pay there.`
    : trip.bookingKind === 'trip_type_calendar'
      ? `Opens ${landingName}'s booking calendar for the ${trip.boat} ${trip.tripLength}. Tap ${trip.departLabel.split(' ').slice(0, 2).join(' ')} on the calendar, then finish booking and pay there.`
      : `This trip can't be booked online from here. Call ${landingName} to book.`;

  return (
    <div className={`chat-trip-card cc-card${compact ? ' cc-compact' : ''}`} role="group" aria-label={`${trip.boat} ${trip.tripLength}, ${trip.departLabel}`}>
      <div className="cc-card-top">
        <div>
          <div className="cc-boat">{trip.boat}</div>
          <div className="cc-sub">{landingName} · {trip.tripLength}</div>
        </div>
        {!compact && (
          <button className={`cc-icon-btn${saved ? ' on' : ''}`} onClick={toggleSave}
                  aria-pressed={saved} aria-label={saved ? `Unsave ${trip.boat} trip` : `Save ${trip.boat} trip`}
                  title={saved ? 'Saved' : 'Save'}>{saved ? '★' : '☆'}</button>
        )}
      </div>

      <div className="cc-when">{trip.departLabel}{trip.returnLabel ? ` → ${trip.returnLabel}` : ''}</div>

      <div className="cc-facts">
        {trip.price != null && <span className="cc-price">${trip.price}<small>/person</small></span>}
        {trip.openSpots != null && (
          <span className={`cc-spots${trip.openSpots <= 5 ? ' low' : ''}`}>
            {trip.openSpots}{trip.capacity ? ` of ${trip.capacity}` : ''} open
          </span>
        )}
        {trip.tripStatus && <span className="cc-tag">{trip.tripStatus}</span>}
      </div>

      {trip.why && trip.why.length > 0 && (
        <ul className="cc-why">
          {trip.why.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}

      {stage === 'card' ? (
        <div className="cc-actions">
          {trip.bookingUrl || trip.landingPhone ? (
            <button className="cc-btn primary" onClick={openSummary}>{compact ? 'Book' : 'Book this trip'}</button>
          ) : null}
          {!compact && <button className="cc-btn" onClick={share}>Share</button>}
          {!compact && (
            <a className="cc-btn ghost" href={trip.boatPageUrl}
               onClick={() => track('chatBoatClick', ctx)}>Boat stats</a>
          )}
        </div>
      ) : (
        <div className="cc-summary" role="region" aria-label="Booking summary">
          <div className="cc-summary-title">Before you go</div>
          <ul>
            <li><b>{trip.boat}</b>, {trip.tripLength}, departs <b>{trip.departLabel}</b> from {trip.landing}</li>
            {trip.price != null && <li><b>${trip.price}</b> per person{trip.included ? ` (includes ${trip.included})` : ''}. Licenses, permits and fees may be extra.</li>}
            {liveLine
              ? <li className={soldOut ? 'cc-live bad' : 'cc-live'} aria-live="polite">{liveLine}</li>
              : trip.openSpots != null && <li>{trip.openSpots} spots open as of {asOf}. Spots can go fast.</li>}
            {!soldOut && <li>{handOffCopy}</li>}
          </ul>
          <div className="cc-actions">
            {soldOut && onAsk && (
              <button className="cc-btn primary" onClick={() => onAsk(`The ${trip.boat} ${trip.tripLength} on ${trip.departLabel} just sold out. What are the closest alternatives?`)}>
                Show alternatives
              </button>
            )}
            {trip.bookingUrl && !soldOut ? (
              <a className="cc-btn primary" href={trip.bookingUrl} target="_blank" rel="noopener noreferrer" onClick={handOff}>
                Continue to {landingName} →
              </a>
            ) : null}
            {trip.landingPhone && (
              <a className={`cc-btn${trip.bookingUrl ? '' : ' primary'}`} href={`tel:${trip.landingPhone.replace(/[^0-9+]/g, '')}`}
                 onClick={() => track('chatCallClick', ctx)}>Call {trip.landingPhone}</a>
            )}
            <button className="cc-btn ghost" onClick={() => setStage('card')}>Back</button>
          </div>
        </div>
      )}
      {shareMsg && <div className="cc-note" role="status">{shareMsg}</div>}
      <div className="cc-asof">Price & spots as of {asOf}. Confirm on the landing's site.</div>
    </div>
  );
}

// Fallback starters if the quick-pick list isn't loaded.
const SUGGESTED_QUESTIONS = [
  "Best overnight this week",
  "Best trip under $300",
  "Where are the yellowtail?",
  "Best full day this weekend",
];

// One-tap answer: best bet + up to 2 alternates, from the website's ranking.
function QuickPickBlock({ pick, msgIndex, onAsk }) {
  const { best, alternates, reason, asOf } = pick.result || {};
  if (!best) {
    return (
      <div className="cc-qp">
        <div className="cc-qp-empty">{reason || 'Nothing matches right now.'}</div>
        <div className="cc-qp-actions">
          <button className="cc-btn" onClick={() => onAsk(`${pick.label} — nothing matched. What are the closest real options?`)}>
            Show closest options
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="cc-qp">
      <div className="cc-qp-label">Best bet</div>
      <ChatTripCard trip={best} position={1} msgIndex={msgIndex} onAsk={onAsk}/>
      {alternates.length > 0 && <div className="cc-qp-label">Also good</div>}
      {alternates.map((t, i) => (
        <ChatTripCard key={t.tripId} trip={t} position={i + 2} msgIndex={msgIndex} onAsk={onAsk} compact/>
      ))}
      <div className="cc-qp-foot">Ranked from recent catch history, open seats and price{asOf ? `, as of ${asOfLabel(asOf)}` : ''}. Not a forecast.</div>
    </div>
  );
}

function ChatBot({ pageContext }) {
  const [open, setOpen]                     = useState(false);
  const [messages, setMessages]             = useState([]);
  const [input, setInput]                   = useState('');
  const [loading, setLoading]               = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [expandedReasoning, setExpandedReasoning] = useState({});
  const [statusIdx, setStatusIdx]           = useState(0);
  const messagesEndRef = useRef(null);
  const inputRef       = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  useEffect(() => {
    if (open && window.innerWidth < 768) {
      document.body.classList.add('chat-open');
    } else {
      document.body.classList.remove('chat-open');
    }
    return () => document.body.classList.remove('chat-open');
  }, [open]);

  // Visual Viewport API: resize panel to actual visible height when keyboard appears
  useEffect(() => {
    if (!open) return;
    const handleViewportResize = () => {
      if (window.visualViewport) {
        const panel = document.querySelector('.chat-panel');
        if (panel) panel.style.height = `${window.visualViewport.height}px`;
      }
    };
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', handleViewportResize);
      handleViewportResize();
    }
    return () => {
      if (window.visualViewport) {
        window.visualViewport.removeEventListener('resize', handleViewportResize);
      }
      const panel = document.querySelector('.chat-panel');
      if (panel) panel.style.height = '';
    };
  }, [open]);

  // Rotate status message while loading
  useEffect(() => {
    if (!loading) return;
    const interval = setInterval(() => {
      setStatusIdx(prev => (prev + 1) % STATUS_MESSAGES.length);
    }, 1500);
    return () => clearInterval(interval);
  }, [loading]);

  function handleInputFocus(e) {
    setTimeout(() => {
      e.target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, 300);
  }

  async function handleSend(text) {
    const msg = (text || input).trim();
    if (!msg || loading) return;

    if (getChatUsage() >= DAILY_LIMIT) {
      setMessages(prev => [...prev, {
        role: 'limit',
        text: "You've used your free questions for today. Pro users get unlimited access."
      }]);
      if (window.TTTrack) TTTrack.chatLimitHit();
      return;
    }

    setInput('');
    setShowSuggestions(false);

    const history = messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));

    // Add user message and streaming placeholder; capture placeholder index before state updates
    const placeholderIdx = messages.length + 1;
    setMessages(prev => [...prev, { role: 'user', text: msg }]);
    setMessages(prev => [...prev, { role: 'assistant', text: '', streaming: true, followups: [], actions: [], dataUsed: null, feedback: null }]);
    setLoading(true);
    setStatusIdx(0);

    if (window.TTTrack) TTTrack.chatMessage(msg, pageContext);

    try {
      const rawText = await streamChatMessage(
        msg, history, pageContext,
        (partialText) => {
          const cleaned = cleanStreamingText(partialText);
          const buildingCard = isBufferingCard(partialText);
          setMessages(prev => prev.map((m, i) =>
            i === placeholderIdx ? { ...m, text: cleaned, buildingCard } : m
          ));
        }
      );

      incrementChatUsage();
      const cleanText   = extractCleanText(rawText);
      const parsedParts = parseMessageWithCards(cleanText);
      const followups   = extractFollowups(rawText);
      const actions     = extractActions(rawText);
      const dataUsed    = extractDataUsed(msg, cleanText, pageContext?.regions || ['san_diego']);
      const shownTrips  = parsedParts.filter(p => p.type === 'trip').map(p => p.data);
      if (shownTrips.length && window.TTTrack?.chatRecommend) {
        TTTrack.chatRecommend({ msgIndex: placeholderIdx, tripIds: shownTrips.map(t => t.tripId), landings: shownTrips.map(t => t.landing) });
      }

      setMessages(prev => prev.map((m, i) =>
        i === placeholderIdx
          ? { ...m, text: cleanText, parsedParts, streaming: false, followups, actions, dataUsed }
          : m
      ));
    } catch (err) {
      setMessages(prev => prev.map((m, i) =>
        i === placeholderIdx
          ? { ...m, text: (err && err.message && !/^HTTP /.test(err.message) && !/fetch/i.test(err.message)) ? err.message : 'Something went wrong — please try again.', streaming: false }
          : m
      ));
    }

    setLoading(false);
  }

  // One-tap starter: answered locally from the shared site ranking (no model
  // call). Falls back to asking the model if the ranking module isn't loaded.
  function handleQuickPick(qp) {
    if (loading) return;
    const result = window.ccRunQuickPick ? window.ccRunQuickPick(qp.intent, pageContext?.regions) : null;
    if (!result) { handleSend(qp.label); return; }
    setShowSuggestions(false);
    const idx = messages.length + 1;
    const historyText = window.ccQuickPickHistoryText ? window.ccQuickPickHistoryText(qp.label, result) : qp.label;
    setMessages(prev => [
      ...prev,
      { role: 'user', text: qp.label },
      { role: 'assistant', text: historyText, quickpick: { intent: qp.intent, label: qp.label, result },
        followups: ['Show cheaper options', 'Anything with more open seats?', 'Compare the top two'] },
    ]);
    const ids = [result.best, ...(result.alternates || [])].filter(Boolean);
    if (window.TTTrack?.chatQuickPick) TTTrack.chatQuickPick({ intent: qp.intent, msgIndex: idx, tripIds: ids.map(t => t.tripId), empty: !result.best });
    if (ids.length && window.TTTrack?.chatRecommend) {
      TTTrack.chatRecommend({ msgIndex: idx, tripIds: ids.map(t => t.tripId), landings: ids.map(t => t.landing) });
    }
  }

  function handleFeedback(idx, type) {
    setMessages(prev => prev.map((m, i) => i === idx ? { ...m, feedback: type } : m));
  }

  function handleFollowup(idx, text) {
    setMessages(prev => prev.map((m, i) => i === idx ? { ...m, followups: [] } : m));
    handleSend(text);
  }

  function handleAction(action) {
    switch(action.action) {
      case 'compare':
        window.location.hash = '#analytics/headtohead';
        setOpen(false);
        break;
      case 'view-boat':
        window.location.hash = `#boat/${encodeURIComponent(action.data)}`;
        setOpen(false);
        break;
      case 'view-trips': {
        const params = action.data ? new URLSearchParams(action.data).toString() : '';
        window.location.hash = params ? `#tripplanner?${params}` : '#tripplanner';
        setOpen(false);
        break;
      }
      default:
        break;
    }
    if (window.TTTrack?.chatAction) TTTrack.chatAction(action.action, action.data);
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  function handleReset() {
    setMessages([]);
    setShowSuggestions(true);
    setInput('');
  }

  return (
    <Fragment>
      {/* Floating action button */}
      <button
        className={`chat-fab${open ? ' open' : ''}`}
        onClick={() => {
          setOpen(o => !o);
          if (!open && window.TTTrack) TTTrack.chatOpen();
        }}
        aria-label="Ask Co-Captain"
        title="Ask Co-Captain"
      >
        💬
      </button>

      {/* Chat panel */}
      {open && (
        <div className="chat-panel">

          {/* Header */}
          <div className="chat-header">
            <button className="chat-header-minimize" onClick={handleReset} aria-label="New conversation" title="New conversation">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="5" y1="12" x2="19" y2="12"/>
              </svg>
            </button>
            <div className="chat-header-title">
              <span className="chat-title">Co-Captain</span>
            </div>
            <button className="chat-header-close" onClick={() => setOpen(false)} aria-label="Close">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>

          {/* Messages */}
          <div className="chat-messages">

            {messages.length === 0 && (
              <Fragment>
                <div className="chat-date-pill-wrap">
                  <span className="chat-date-pill">
                    {new Date().toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}
                  </span>
                </div>
                <div className="chat-message assistant">
                  <div className="chat-bubble assistant">
                    Hey, I'm Co-Captain — your AI fishing partner. Ask me about boats, fish counts, trips, or what's biting.
                  </div>
                </div>
                <div className="chat-disclaimer">AI can be inaccurate. Verify important information.</div>
              </Fragment>
            )}

            {showSuggestions && (
              <div className="chat-suggestions" role="group" aria-label="Quick picks">
                {((window.ccQuickPickList && window.ccQuickPickList()) || SUGGESTED_QUESTIONS.map(q => ({ label: q }))).map((qp, i) => (
                  <button key={i} className="chat-suggestion-chip"
                          onClick={() => qp.intent ? handleQuickPick(qp) : handleSend(qp.label)}>
                    {qp.label}
                  </button>
                ))}
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`chat-message ${msg.role}`}>
                {msg.role === 'limit' ? (
                  <div className="chat-limit-msg">
                    <div>{msg.text}</div>
                    <button className="btn primary sm" style={{ marginTop: 8 }}>
                      Upgrade to Pro →
                    </button>
                  </div>
                ) : (
                  <Fragment>
                    <div className={`chat-bubble ${msg.role}`}>
                      {msg.quickpick ? (
                        <QuickPickBlock pick={msg.quickpick} msgIndex={i} onAsk={handleSend}/>
                      ) : msg.streaming && !msg.text ? (
                        <div className="chat-status">
                          <div className="chat-status-dots">
                            <span className="typing-dot">●</span>
                            <span className="typing-dot">●</span>
                            <span className="typing-dot">●</span>
                          </div>
                          <div className="chat-status-text">{STATUS_MESSAGES[statusIdx]}</div>
                        </div>
                      ) : (
                        <Fragment>
                          {(() => { let pos = 0; return (msg.parsedParts || parseMessageWithCards(msg.text)).map((part, pi) =>
                            part.type === 'trip'
                              ? <ChatTripCard key={pi} trip={part.data} position={++pos} msgIndex={i} onAsk={handleSend} />
                              : <Fragment key={pi}>{renderMessageContent(part.content, () => setOpen(false))}</Fragment>
                          ); })()}
                          {msg.streaming && msg.buildingCard ? (
                            <div className="chat-building-indicator">
                              <span className="typing-dot">●</span>
                              <span className="typing-dot">●</span>
                              <span className="typing-dot">●</span>
                              <span>Building recommendations...</span>
                            </div>
                          ) : (
                            msg.streaming && <span className="chat-streaming-cursor">▎</span>
                          )}
                        </Fragment>
                      )}
                    </div>

                    {msg.role === 'assistant' && msg.dataUsed && !msg.streaming && (
                      <div className="chat-reasoning">
                        <button
                          className="chat-reasoning-toggle"
                          onClick={() => setExpandedReasoning(prev => ({ ...prev, [i]: !prev[i] }))}
                        >
                          {expandedReasoning[i] ? '▼' : '▶'} Data used
                        </button>
                        {expandedReasoning[i] && (
                          <div className="chat-reasoning-content">
                            {msg.dataUsed.map((d, j) => (
                              <div key={j} className="chat-data-item">· {d}</div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}

                    {msg.role === 'assistant' && !msg.streaming && (
                      <div className="chat-feedback">
                        <button
                          className={`chat-feedback-btn${msg.feedback === 'up' ? ' active' : ''}`}
                          onClick={() => handleFeedback(i, 'up')}
                          title="Helpful"
                        >👍</button>
                        <button
                          className={`chat-feedback-btn${msg.feedback === 'down' ? ' active' : ''}`}
                          onClick={() => handleFeedback(i, 'down')}
                          title="Not helpful"
                        >👎</button>
                      </div>
                    )}

                    {msg.role === 'assistant' && msg.actions && msg.actions.length > 0 && (
                      <div className="chat-actions">
                        {msg.actions.map((action, j) => (
                          <button
                            key={j}
                            className="chat-action-btn"
                            onClick={() => handleAction(action)}
                          >
                            {action.label}
                          </button>
                        ))}
                      </div>
                    )}

                    {msg.role === 'assistant' && msg.followups && msg.followups.length > 0 && (
                      <div className="chat-followups">
                        <div className="chat-followups-label">Continue the conversation:</div>
                        <div className="chat-followups-list">
                          {msg.followups.map((fu, j) => (
                            <button
                              key={j}
                              className="chat-followup-chip"
                              onClick={() => handleFollowup(i, fu)}
                            >
                              {fu} →
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </Fragment>
                )}
              </div>
            ))}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="chat-input-area">
            <input
              type="text"
              ref={inputRef}
              className="chat-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={handleInputFocus}
              placeholder="Ask Co-Captain..."
            />
            <button
              className="chat-send-btn"
              onClick={() => handleSend()}
              disabled={!input.trim() || loading}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{width:18,height:18}}>
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22 2 15 22 11 13 2 9 22 2" fill="currentColor" stroke="none"/>
              </svg>
            </button>
          </div>

          {DAILY_LIMIT < 999 && (
            <div className="chat-usage">
              {getChatUsage()}/{DAILY_LIMIT} free questions today
            </div>
          )}

        </div>
      )}
    </Fragment>
  );
}

Object.assign(window, { ChatBot });

})();
