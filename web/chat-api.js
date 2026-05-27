// Replace with your Cloudflare Worker URL after deploying
const CHAT_PROXY_URL = 'https://chatbot.tylerjchristian.workers.dev';

function buildSystemPrompt(pageContext) {
  const today    = window.SD?.TODAY;
  const forecast = window.SD?.FORECAST;
  const meta     = window.SD?.META;
  const community = window.SD?.COMMUNITY;

  // Top 5 boats current year
  const topBoats = (() => {
    try {
      const yearTrips = SDA.filterTrips({
        ...DEFAULT_FILTERS,
        year: String(new Date().getFullYear())
      });
      const { rows } = SDA.boatLeaderboard(yearTrips, 'all', 5);
      return rows.slice(0, 5).map(b =>
        `${b.boat} (${b.landing}) — ` +
        `${b.avgTPAPerDay?.toFixed(2)} tuna/angler/day, ${b.winRate || '?'}% win rate`
      ).join('\n');
    } catch (e) { return 'Data unavailable'; }
  })();

  const inshore  = forecast?.inshore?.today;
  const offshore = forecast?.offshore?.today;
  const scrapeTime = meta?.lastScrape
    ? new Date(meta.lastScrape).toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit',
        timeZone: 'America/Los_Angeles', timeZoneName: 'short'
      })
    : 'unknown';

  return `You are a knowledgeable and friendly fishing advisor for The Tuna Tracker — San Diego's most detailed sportfishing analytics site.

Your job is to help anglers make better decisions about when to fish, which boat to book, and what to expect offshore.

CURRENT DATA (updated ${scrapeTime}):

TODAY'S CATCH:
- Date: ${today?.date || 'unknown'}
- Total tuna: ${today?.trophyCount || 0}
- Anglers out: ${today?.anglers || 0}
- Boats fishing: ${today?.boats || 0}

FISHING FORECAST:
Inshore (Full Day trips):
- Score: ${inshore?.overall_score || 'N/A'}/10
- Conditions: ${inshore?.conditions_label || 'N/A'}
- Water temp: ${inshore?.sst || 'N/A'}°F nearshore
- Wind: ${inshore?.wind_speed || 'N/A'}kn
- Confidence: ${inshore?.confidence || 'N/A'}

Offshore (Overnight+ trips):
- Score: ${offshore?.overall_score || 'N/A'}/10
- Conditions: ${offshore?.conditions_label || 'N/A'}
- Water temp: ${offshore?.sst || 'N/A'}°F at 60-Mile Bank
- SST gradient: ${offshore?.sst_gradient || 'N/A'}°F break
- Upwelling: ${offshore?.upwelling_label || 'N/A'}
- Wind: ${offshore?.wind_speed || 'N/A'}kn ${offshore?.wind_direction || ''}
- Eddy detected: ${offshore?.eddy_detected ? 'Yes' : 'No'}
- Confidence: ${offshore?.confidence || 'N/A'}

TOP BOATS THIS SEASON:
${topBoats}

COMMUNITY INTEL:
${community?.biteReport?.species?.slice(0, 3)?.map(s => `${s.name}: ${s.status}`)?.join(', ') || 'No recent reports'}

${pageContext?.boat ? `USER IS VIEWING: ${pageContext.boat} boat page` : ''}
${pageContext?.page ? `CURRENT PAGE: ${pageContext.page}` : ''}

GUIDELINES:
- Be friendly, conversational, helpful
- 2-4 sentences for simple questions
- Use actual data in your answers
- Be honest about uncertainty
- Use fishing terms naturally
- Recommend specific boats by name when asked
- Reference specific conditions (temps, wind, forecast scores)
- Don't make up data you don't have
- For trip planning questions mention the Trip Planner page
- Keep it focused on San Diego sportfishing
- Speak like a knowledgeable local angler, not a robot`;
}

async function sendChatMessage(userMessage, conversationHistory, pageContext) {
  try {
    const response = await fetch(CHAT_PROXY_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: 'claude-sonnet-4-6',
        max_tokens: 400,
        system: buildSystemPrompt(pageContext),
        messages: [
          ...conversationHistory,
          { role: 'user', content: userMessage }
        ]
      })
    });

    const data = await response.json();

    if (data.error) {
      throw new Error(data.error.message);
    }

    return {
      text: data.content[0].text,
      usage: data.usage,
      dataUsed: extractDataUsed(userMessage, data.content[0].text)
    };

  } catch (error) {
    console.error('Chat error:', error);
    return {
      text: "Sorry, I'm having trouble connecting right now. Please try again in a moment.",
      usage: null,
      dataUsed: null
    };
  }
}

function extractDataUsed(question, answer) {
  const used = [];
  const a = answer.toLowerCase();

  if (a.includes('tuna') || a.includes('catch') || a.includes('today')) {
    const t = window.SD?.TODAY;
    if (t) used.push(`Today's counts: ${t.trophyCount} tuna, ${t.boats} boats`);
  }

  if (a.includes('forecast') || a.includes('conditions') || a.includes('score')) {
    const f = window.SD?.FORECAST;
    if (f?.offshore?.today) used.push(`Offshore forecast: ${f.offshore.today.overall_score}/10`);
    if (f?.inshore?.today)  used.push(`Inshore forecast: ${f.inshore.today.overall_score}/10`);
  }

  if (a.includes('boat') || a.includes('captain')) {
    used.push('Boat leaderboard data');
  }

  if (a.includes('temperature') || a.includes('°f') || a.includes('water')) {
    used.push(`SST: ${window.SD?.FORECAST?.offshore?.today?.sst || '?'}°F offshore`);
  }

  return used.length > 0 ? used : null;
}

function getChatUsage() {
  const today = new Date().toISOString().slice(0, 10);
  return parseInt(localStorage.getItem(`tt_chat_${today}`) || '0');
}

function incrementChatUsage() {
  const today = new Date().toISOString().slice(0, 10);
  const key   = `tt_chat_${today}`;
  const next  = getChatUsage() + 1;
  localStorage.setItem(key, next);
  return next;
}

const DAILY_LIMIT = 999; // Set to 999 until Pro auth is built
