// AI Fishing Advisor chatbot component.
// Requires chat-api.js to be loaded first.
(function () {

const { useState, useEffect, useRef, Fragment } = React;

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
  const messagesEndRef = useRef(null);
  const inputRef       = useRef(null);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Focus input when opened
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

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
    setMessages(prev => [...prev, { role: 'user', text: msg }]);
    setLoading(true);

    const history = messages
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));

    const result = await sendChatMessage(msg, history, pageContext);

    incrementChatUsage();
    setLoading(false);
    setMessages(prev => [...prev, {
      role: 'assistant',
      text: result.text,
      dataUsed: result.dataUsed,
      feedback: null
    }]);

    if (window.TTTrack) TTTrack.chatMessage(msg, pageContext);
  }

  function handleFeedback(idx, type) {
    setMessages(prev => prev.map((m, i) => i === idx ? { ...m, feedback: type } : m));
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
                    <div className="chat-bubble">{msg.text}</div>

                    {msg.role === 'assistant' && msg.dataUsed && (
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

                    {msg.role === 'assistant' && (
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
                  </Fragment>
                )}
              </div>
            ))}

            {loading && (
              <div className="chat-message assistant">
                <div className="chat-bubble typing">
                  <span className="typing-dot">●</span>
                  <span className="typing-dot">●</span>
                  <span className="typing-dot">●</span>
                </div>
              </div>
            )}

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
