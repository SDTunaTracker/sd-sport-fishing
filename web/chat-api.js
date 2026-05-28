// Replace with your Cloudflare Worker URL after deploying
const CHAT_PROXY_URL = 'https://chatbot.tylerjchristian.workers.dev';

function getRegionLandings(regions) {
  const r = regions || ['san_diego'];
  if (window.getLandingsForRegion && window.getEffectiveRegion) {
    return window.getLandingsForRegion(window.getEffectiveRegion(r)) || window.SD.LANDINGS;
  }
  return window.SD?.LANDINGS || [];
}

function getUpcomingTripsForChat(regions) {
  const today   = new Date().toISOString().slice(0, 10);
  const cutoff  = new Date(Date.now() + 120 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const allowed = getRegionLandings(regions);

  return (window.SD?.SCHEDULE || [])
    .filter(t =>
      t.departureDate >= today &&
      t.departureDate <= cutoff &&
      t.openSpots > 0 &&
      allowed.includes(t.landing)
    )
    .sort((a, b) => a.departureDate.localeCompare(b.departureDate))
    .slice(0, 100)
    .map(t => ({
      boat:            t.boat,
      landing:         t.landing,
      departure:       t.departureDate,
      departureTime:   t.departureTime,
      returnDate:      t.returnDate,
      tripLength:      t.tripLength,
      price:           t.price,
      effectivePrice:  t.effectivePrice,
      openSpots:       t.openSpots,
      maxLoad:         t.maxLoad,
      mealsIncluded:   t.mealsIncluded,
      moonPhase:       t.moonPhase,
      forecastScore:   t.forecastScore,
      winRate:         t.winRate,
      avgTPA:          t.avgTPA,
    }));
}

function getBoatStatsForChat(regions) {
  const allowed = getRegionLandings(regions);
  try {
    const yearTrips = SDA.filterTrips({
      ...DEFAULT_FILTERS,
      year: String(new Date().getFullYear())
    }).filter(t => allowed.includes(t.landing));

    const { rows } = SDA.boatLeaderboard(yearTrips, 'all', 5);
    return rows.slice(0, 15).map(b => ({
      boat:        b.boat,
      landing:     b.landing,
      winRate:     b.winRate,
      avgTPA:      b.avgTPAPerDay?.toFixed(2),
      tripCount:   b.tripCount,
      streak:      b.streak?.current_streak_type,
      streakCount: b.streak?.current_streak,
    }));
  } catch (e) { return []; }
}

function buildSystemPrompt(pageContext) {
  const today    = window.SD?.TODAY;
  const forecast = window.SD?.FORECAST;
  const meta     = window.SD?.META;
  const community = window.SD?.COMMUNITY;
  const regions  = pageContext?.regions || ['san_diego'];

  const upcomingTrips = getUpcomingTripsForChat(regions);
  const boatStats     = getBoatStatsForChat(regions);

  const inshore  = forecast?.inshore?.today;
  const offshore = forecast?.offshore?.today;
  const scrapeTime = meta?.lastScrape
    ? new Date(meta.lastScrape).toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit',
        timeZone: 'America/Los_Angeles', timeZoneName: 'short'
      })
    : 'unknown';

  const upcomingSection = upcomingTrips.length > 0
    ? upcomingTrips.map(t =>
        `${t.boat} (${t.landing}) | ${t.tripLength} | Departs ${t.departure} ${t.departureTime || ''} | Returns ${t.returnDate} | $${t.price}${t.mealsIncluded ? ' (meals incl.)' : ''} | ${t.openSpots} spots open | Moon: ${t.moonPhase || 'N/A'} | Forecast: ${t.forecastScore ?? 'N/A'}/10 | Win Rate: ${t.winRate ?? 'N/A'}%`
      ).join('\n')
    : 'No upcoming trips with open spots in the next 30 days.';

  const boatSection = boatStats.length > 0
    ? boatStats.map(b =>
        `${b.boat} (${b.landing}): ${b.winRate}% win rate, ${b.avgTPA} TPA/day, ${b.tripCount} trips, ${b.streak === 'hot' ? `🔥 ${b.streakCount} straight good trips` : b.streak === 'cold' ? `❄️ ${b.streakCount} straight slow trips` : 'mixed recent form'}`
      ).join('\n')
    : 'No boat stats available.';

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

UPCOMING TRIPS (next 30 days, open spots only):
${upcomingSection}

BOAT PERFORMANCE THIS SEASON:
${boatSection}

COMMUNITY INTEL:
${community?.biteReport?.species?.slice(0, 3)?.map(s => `${s.name}: ${s.status}`)?.join(', ') || 'No recent reports'}

${pageContext?.boat ? `USER IS VIEWING: ${pageContext.boat} boat page` : ''}
${pageContext?.page ? `CURRENT PAGE: ${pageContext.page}` : ''}
${pageContext?.region && pageContext.region !== 'san_diego' ? `REGION: User is viewing ${pageContext.region === 'all_socal' ? 'All SoCal' : pageContext.region} data. Only suggest follow-ups about boats and trips in that region — don't reference boats from other regions unless viewing All SoCal.` : 'REGION: San Diego.'}

TRIP RECOMMENDATION INSTRUCTIONS:
When a user asks about trips, booking, or what to book — always search the upcoming trips list above and recommend specific trips by name, date, and price. Never recommend a trip with 0 open spots. Prefer trips with higher forecast scores when all else is equal. Flag trips on a full moon or new moon as a bonus.

Format trip recommendations like this:
"Based on what you're looking for, here are my top picks:

1. **Pacific Queen** — 2 Day trip
   Departs Fri Jun 15 · 10:00 AM
   Returns Sun Jun 17 · 6:00 PM
   $1,200/person · Meals included
   21 spots open · 🌕 Full Moon
   Forecast: 8.8/10 · Win Rate: 68%
   → Book at Fisherman's Landing

2. **Shogun** — 3 Day trip
   ..."

Always end trip recommendations with: "Want me to narrow this down? Tell me your preferred dates, budget, or trip length."

If no trips match, say so honestly and suggest the Trip Planner page.

CONTEXT AWARENESS:
- If user is on a boat detail page: focus recommendations on that boat's upcoming trips first
- If user mentions a budget: filter to that range
- If user mentions dates: only show trips in that range
- If user mentions trip length: only show matching lengths
- If user mentions a species: weight boats with strong history for that species

RESPONSE LENGTH:
- Simple questions: 2-3 sentences
- Trip recommendations: 5-8 lines max per trip
- Comparisons: short table or bullets
- Never write more than 6 paragraphs
- Give the headline answer first, offer to go deeper via follow-ups

RESPONSE FORMATTING:
- For trip recommendations: use the numbered list format above
- For simple questions: 2-4 sentences
- For comparisons: use a simple table
- Never recommend a trip with 0 open spots
- Use bold only for boat names and key stats — not entire phrases or sentence prefixes
- Don't start sentences with "**My suggestion:**" or similar — just say it naturally
- Keep paragraphs to 2-3 sentences max
- Use bullet lists for comparisons only, not for paragraphs of analysis
- Skip technical jargon (coordinates, zone codes) without context — explain it or leave it out

VOICE:
- Talk like a knowledgeable local friend, not a fishing report or corporate advisor
- Be direct: "Pacific Queen has been crushing it lately — 2.25 tuna/angler/day" not "Pacific Queen is a solid producer"
- Avoid phrases like "Top boats to watch", "the workhorse of the fleet", "Early August is typically prime time"
- Say it plainly: "Early August is one of the best times of year for bluefin"

FUTURE DATE QUESTIONS:
- The upcoming trips window covers 120 days — if a user asks about dates beyond that, don't apologize for the data window
- Instead provide historical analysis: "Based on the last few years, the top boats in early August have been..."
- Reference seasonal patterns confidently
- Suggest booking early since summer trips fill fast
- Recommend specific boats known for that time of year

FOLLOW-UP SUGGESTIONS:
After your main response, suggest 2-3 relevant follow-up questions the user might want to ask next. Format them as a JSON array between special markers at the very end of your response:

<followups>
["Compare Pacific Queen vs Shogun", "Show me cheaper alternatives", "What about a 3-day trip instead?"]
</followups>

Follow-ups should be natural next questions based on what was just discussed, specific and actionable, and vary by context. Good examples:
- After trip recs: "Compare these boats head to head", "Show me trips with meals included", "Find me earlier departures"
- After boat question: "What's this boat's upcoming schedule?", "How does it compare to [competitor]?"
- After forecast: "What conditions drive that score?", "Should I book inshore or offshore?"
- After species: "Best boats for [species]", "When is peak season for [species]?"

GUIDELINES:
- Be friendly, conversational, helpful
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
        model: 'claude-opus-4-7',
        max_tokens: 800,
        system: buildSystemPrompt(pageContext),
        messages: [
          ...conversationHistory,
          { role: 'user', content: userMessage }
        ]
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status} from worker`);
    }

    const data = await response.json();

    if (data.error) {
      throw new Error(`Anthropic: ${data.error.type} — ${data.error.message}`);
    }

    const regions  = pageContext?.regions || ['san_diego'];
    const rawText  = data.content[0].text;

    let followups = [];
    let cleanText = rawText;
    const followupMatch = rawText.match(/<followups>([\s\S]*?)<\/followups>/);
    if (followupMatch) {
      try { followups = JSON.parse(followupMatch[1].trim()); } catch (e) { followups = []; }
      cleanText = rawText.replace(/<followups>[\s\S]*?<\/followups>/, '').trim();
    }

    return {
      text:     cleanText,
      followups,
      usage:    data.usage,
      dataUsed: extractDataUsed(userMessage, cleanText, regions)
    };

  } catch (error) {
    console.error('Chat error:', error);
    return {
      text:     "Debug: " + (error.message || String(error)),
      followups: [],
      usage:    null,
      dataUsed: null
    };
  }
}

function extractDataUsed(question, answer, regions) {
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

  if (a.includes('departs') || a.includes('$') || a.includes('spots open') || a.includes('book')) {
    const upcoming = getUpcomingTripsForChat(regions);
    used.push(`Trip schedule: ${upcoming.length} upcoming trips checked`);
  }

  if (a.includes('win rate') || a.includes('tpa') || a.includes('streak')) {
    const stats = getBoatStatsForChat(regions);
    used.push(`Boat performance: ${stats.length} boats analyzed`);
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
