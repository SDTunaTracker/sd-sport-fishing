// Reddit fishing reports widget — used on Today page and Boat Detail page
const { useMemo } = React;

function redditTimeAgo(dateStr) {
  if (!dateStr) return '';
  const diff = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

function RedditPost({ post, compact }) {
  return (
    <div className={`rd-post${compact ? ' rd-post-compact' : ''}`}>
      <div className="rd-post-body">
        <a href={post.url} target="_blank" rel="noopener noreferrer" className="rd-post-title">
          {post.title}
        </a>
        {!compact && post.snippet && (
          <div className="rd-post-snippet">{post.snippet.slice(0, 150)}{post.snippet.length > 150 ? '…' : ''}</div>
        )}
        <div className="rd-post-meta">
          <span className="rd-subreddit-badge">r/{post.subreddit}</span>
          <span className="rd-meta-sep">·</span>
          <span className="rd-meta-item">↑ {post.score}</span>
          <span className="rd-meta-sep">·</span>
          <span className="rd-meta-item">💬 {post.num_comments}</span>
          <span className="rd-meta-sep">·</span>
          <span className="rd-meta-item rd-meta-date">{redditTimeAgo(post.date)}</span>
          {post.boat_mentioned && (
            <><span className="rd-meta-sep">·</span>
              <span className="rd-meta-boat">{post.boat_mentioned}</span></>
          )}
        </div>
      </div>
      {!compact && (
        <a href={post.url} target="_blank" rel="noopener noreferrer" className="rd-read-link">
          Read on Reddit →
        </a>
      )}
    </div>
  );
}

// Compact widget for Today page — shows 3 most recent posts
function CommunityReportsWidget() {
  const reddit = window.SD.REDDIT;
  if (!reddit || !reddit.reports || reddit.reports.length === 0) return null;
  const posts = reddit.reports.slice(0, 3);
  return (
    <div className="rd-widget">
      <div className="rd-widget-head">
        <div className="rd-widget-title">
          <span className="rd-logo">🎣</span>
          From the Community
        </div>
        <span className="rd-widget-sub">Recent posts from Reddit</span>
      </div>
      <div className="rd-widget-list">
        {posts.map(p => <RedditPost key={p.id} post={p} compact/>)}
      </div>
      <a href="https://www.reddit.com/r/SaltWaterFishing/search/?q=san+diego+sportfishing&sort=new"
         target="_blank" rel="noopener noreferrer" className="rd-widget-footer">
        See more on Reddit →
      </a>
    </div>
  );
}

// Boat-specific panel — shows posts mentioning this boat
function BoatRedditPanel({ boat }) {
  const reddit = window.SD.REDDIT;
  const posts = useMemo(() => {
    if (!reddit || !reddit.reports) return [];
    return reddit.reports.filter(p =>
      p.boat_mentioned === boat ||
      (p.title || '').toLowerCase().includes(boat.toLowerCase()) ||
      (p.snippet || '').toLowerCase().includes(boat.toLowerCase())
    );
  }, [boat, reddit]);

  if (posts.length === 0) {
    return (
      <div className="rd-empty">
        <span className="rd-empty-icon">🔍</span>
        No recent Reddit reports found for {boat}.
      </div>
    );
  }

  return (
    <div className="rd-panel">
      {posts.map(p => <RedditPost key={p.id} post={p}/>)}
    </div>
  );
}

Object.assign(window, { CommunityReportsWidget, BoatRedditPanel });
