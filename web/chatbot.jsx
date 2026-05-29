// AI Fishing Advisor chatbot component.
// Requires chat-api.js to be loaded first.
(function () {

const { useState, useEffect, useRef, Fragment } = React;

const STATUS_MESSAGES = [
  "Analyzing forecast data...",
  "Checking upcoming trips...",
  "Reviewing boat performance...",
  "Looking at recent reports...",
  "Calculating recommendations...",
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
      const tripData = JSON.parse(match[1].trim());
      parts.push({ type: 'trip', data: tripData });
    } catch(e) {
      parts.push({ type: 'text', content: match[0] });
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIndex) });
  }

  return parts;
}

function ChatTripCard({ trip }) {
  return (
    <div className="chat-trip-card">
      <div className="chat-trip-header">
        <div className="chat-trip-boat">{trip.boat}</div>
        {trip.forecastScore != null && (
          <span className="score-badge">{trip.forecastScore}/10</span>
        )}
      </div>

      <div className="chat-trip-meta">
        <span className="chat-trip-landing">{trip.landing}</span>
        {trip.tripLength && <span className="chat-trip-length">{trip.tripLength}</span>}
      </div>

      <div className="chat-trip-details">
        <div className="chat-trip-row">
          <span className="label">DEP</span>
          <span>{formatDate(trip.departureDate)}{trip.departureTime ? ` · ${trip.departureTime}` : ''}</span>
        </div>
        <div className="chat-trip-row">
          <span className="label">RET</span>
          <span>{formatDate(trip.returnDate)}</span>
        </div>
        {trip.moonPhase && (
          <div className="chat-trip-row">
            <span>{trip.moonEmoji || '🌙'} {trip.moonPhase}</span>
          </div>
        )}
      </div>

      <div className="chat-trip-stats">
        {trip.winRate != null && (
          <div className="stat">
            <span className="stat-value">{trip.winRate}%</span>
            <span className="stat-label">Win Rate</span>
          </div>
        )}
        {trip.avgTPA != null && (
          <div className="stat">
            <span className="stat-value">{trip.avgTPA}</span>
            <span className="stat-label">TPA/day</span>
          </div>
        )}
        {trip.openSpots != null && (
          <div className="stat">
            <span className="stat-value">{trip.openSpots}{trip.maxLoad ? `/${trip.maxLoad}` : ''}</span>
            <span className="stat-label">Open</span>
          </div>
        )}
      </div>

      <div className="chat-trip-footer">
        <div className="chat-trip-price">
          ${trip.price}
          {trip.mealsIncluded && <span className="meals-badge">🍽️ Meals</span>}
        </div>
        {trip.bookingUrl && trip.bookingUrl !== 'N/A' && (
          <a
            href={trip.bookingUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="chat-trip-book-btn"
            onClick={() => {
              if (window.TTTrack?.chatLinkClick) TTTrack.chatLinkClick('Book', trip.bookingUrl, true);
            }}
          >Book →</a>
        )}
      </div>
    </div>
  );
}

const SUGGESTED_QUESTIONS = [
  "What's the best trip this weekend?",
  "Find me an overnight trip under $500",
  "Which boat is hottest right now?",
  "Best trip for bluefin this month?",
];

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
      const cleanText = extractCleanText(rawText);
      const followups = extractFollowups(rawText);
      const actions   = extractActions(rawText);
      const dataUsed  = extractDataUsed(msg, cleanText, pageContext?.regions || ['san_diego']);

      setMessages(prev => prev.map((m, i) =>
        i === placeholderIdx
          ? { ...m, text: cleanText, streaming: false, followups, actions, dataUsed }
          : m
      ));
    } catch (err) {
      setMessages(prev => prev.map((m, i) =>
        i === placeholderIdx
          ? { ...m, text: 'Something went wrong — please try again.', streaming: false }
          : m
      ));
    }

    setLoading(false);
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
        aria-label="Open fishing advisor"
      >
        {open ? '✕' : '💬'}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="chat-panel">

          {/* Header */}
          <div className="chat-header">
            <div className="chat-header-left">
              <span className="chat-fish-icon">🐟</span>
              <div>
                <div className="chat-title">Fishing Advisor</div>
                <div className="chat-subtitle">Powered by AI · San Diego data</div>
              </div>
            </div>
            <div className="chat-header-actions">
              <button className="chat-icon-btn" onClick={handleReset} title="New conversation">↺</button>
              <button className="chat-icon-btn" onClick={() => setOpen(false)} title="Close">✕</button>
            </div>
          </div>

          {/* Messages */}
          <div className="chat-messages">

            {messages.length === 0 && (
              <div className="chat-welcome">
                <div className="chat-welcome-text">
                  Ask me anything about San Diego sportfishing — conditions, boats, trip planning, or what's biting!
                </div>
              </div>
            )}

            {showSuggestions && (
              <div className="chat-suggestions">
                {SUGGESTED_QUESTIONS.map((q, i) => (
                  <button key={i} className="chat-suggestion-btn" onClick={() => handleSend(q)}>
                    {q}
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
                    <div className="chat-bubble">
                      {msg.streaming && !msg.text ? (
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
                          {parseMessageWithCards(msg.text).map((part, pi) =>
                            part.type === 'trip'
                              ? <ChatTripCard key={pi} trip={part.data} />
                              : <Fragment key={pi}>{renderMessageContent(part.content, () => setOpen(false))}</Fragment>
                          )}
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
            <textarea
              ref={inputRef}
              className="chat-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onFocus={handleInputFocus}
              placeholder="Ask about fishing conditions..."
              rows={1}
            />
            <button
              className="chat-send-btn"
              onClick={() => handleSend()}
              disabled={!input.trim() || loading}
            >➤</button>
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
