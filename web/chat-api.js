// Replace with your Cloudflare Worker URL after deploying
const CHAT_PROXY_URL = 'https://chatbot.tylerjchristian.workers.dev';

function getRegionLandings(regions) {
  const r = regions || ['san_diego'];
  if (window.getLandingsForRegion && window.getEffectiveRegion) {
    return window.getLandingsForRegion(window.getEffectiveRegion(r)) || window.SD.LANDINGS;
  }
  return window.SD?.LANDINGS || [];
}

function buildBookingUrl(t) {
  let base = null;
  switch (t.landing) {
    case 'Point Loma Sportfishing':
      base = t.sourceId ? `https://pointloma.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(t.sourceId)}` : null;
      break;
    case 'Seaforth Sportfishing':
      base = t.sourceId ? `https://seaforth.fishingreservations.net/sales/user.php?trip_id=${encodeURIComponent(t.sourceId)}` : null;
      break;
    case "Fisherman's Landing":
      base = t.sourceId ? `https://fishermanslanding.fishingreservations.net/resos/user.php?trip_id=${encodeURIComponent(t.sourceId)}` : null;
      break;
    case 'H&M Landing': {
      const slug = (t.boat || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
      base = slug ? `https://www.hmlanding.com/boat/${slug}` : null;
      break;
    }
    default: break;
  }
  if (!base) return null;
  if (window.TTTrack?.buildUrl) return TTTrack.buildUrl(base, t.boat, t.landing, t.departureDate || '');
  return base;
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
      bookingUrl:      buildBookingUrl(t),
      boatPageUrl:     `#boat/${encodeURIComponent(t.boat)}`,
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

function extractCleanText(rawText) {
  return rawText
    .replace(/<followups>[\s\S]*?<\/followups>/, '')
    .replace(/<actions>[\s\S]*?<\/actions>/, '')
    .trim();
}

function extractFollowups(rawText) {
  const match = rawText.match(/<followups>([\s\S]*?)<\/followups>/);
  if (!match) return [];
  try { return JSON.parse(match[1].trim()); } catch(e) { return []; }
}

function extractActions(rawText) {
  const match = rawText.match(/<actions>([\s\S]*?)<\/actions>/);
  if (!match) return [];
  try { return JSON.parse(match[1].trim()); } catch(e) { return []; }
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
        `${t.boat} (${t.landing}) | ${t.tripLength} | Departs ${t.departure} ${t.departureTime || ''} | Returns ${t.returnDate} | $${t.price}${t.mealsIncluded ? ' (meals incl.)' : ''} | ${t.openSpots}/${t.maxLoad || '?'} spots | Moon: ${t.moonPhase || 'N/A'} | Forecast: ${t.forecastScore ?? 'N/A'}/10 | Win Rate: ${t.winRate ?? 'N/A'}% | AvgTPA: ${t.avgTPA ?? 'N/A'} | BoatPage: ${t.boatPageUrl} | Booking: ${t.bookingUrl || 'N/A'}`
      ).join('\n')
    : 'No upcoming trips with open spots in the next 120 days.';

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

UPCOMING TRIPS (next 120 days, open spots only):
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

For specific trip recommendations, embed each trip using this structured format that renders as a rich card in the UI. Populate ALL fields with real data from the trips list above:

<trip-card>
{"boat": "Pacific Queen", "landing": "Fisherman's Landing", "tripLength": "2 Day", "departureDate": "2026-06-15", "departureTime": "10:00 AM", "returnDate": "2026-06-17", "price": 1200, "mealsIncluded": true, "openSpots": 21, "maxLoad": 55, "moonPhase": "Full Moon", "moonEmoji": "🌕", "forecastScore": 8.8, "winRate": 68, "avgTPA": 1.83, "bookingUrl": "https://fishermanslanding.fishingreservations.net/resos/user.php?trip_id=12345", "boatPageUrl": "#boat/Pacific%20Queen"}
</trip-card>

Moon emoji guide: 🌑 New Moon · 🌒 Waxing Crescent · 🌓 First Quarter · 🌔 Waxing Gibbous · 🌕 Full Moon · 🌖 Waning Gibbous · 🌗 Last Quarter · 🌘 Waning Crescent. Omit moonEmoji and moonPhase if N/A.

Include up to 3 trip cards per response. After each card, add one sentence explaining why you picked it. If Booking is N/A, omit the bookingUrl field.

Always end trip recommendations with: "Want me to narrow this down? Tell me your preferred dates, budget, or trip length."

If no trips match, say so honestly and suggest the [Trip Planner](#tripplanner).

CONTEXT AWARENESS:
- If user is on a boat detail page: focus recommendations on that boat's upcoming trips first
- If user mentions a budget: filter to that range
- If user mentions dates: only show trips in that range
- If user mentions trip length: only show matching lengths
- If user mentions a species: weight boats with strong history for that species

LINK GENERATION:
Include clickable markdown links [text](url) in your responses. Use the BoatPage and Booking URLs provided in each trip's data above.

Internal app pages (use these exact formats):
- Boat detail: use the BoatPage field from the trip data (e.g. #boat/Pacific%20Queen)
- Trip Planner: [Trip Planner](#tripplanner)
- Today's report: [Today's Report](#today)
- Forecast: [Forecast](#forecast)
- Leaderboard: [Boat Leaderboard](#analytics/boats)

When to link:
- First mention of any boat: link to its boat page using #boat/{name encoded}
- "Trip Planner" suggestions: always make it a link
- Page suggestions: link the page name

RESPONSE LENGTH:
- Simple questions: 2-3 sentences
- Trip recommendations: use trip cards + 1 sentence each
- Comparisons: short table or bullets
- Never write more than 6 paragraphs

RESPONSE FORMATTING:
- For trip recommendations: use the trip card format above
- Use bold only for key stats, not entire phrases
- Keep paragraphs to 2-3 sentences max
- Use bullet lists for comparisons, not analysis paragraphs

VOICE:
- Talk like a knowledgeable local friend, not a fishing report
- Be direct: "Pacific Queen has been crushing it lately" not "Pacific Queen is a solid producer"
- Avoid filler phrases like "Top boats to watch" or "Early August is typically prime time"

FUTURE DATE QUESTIONS:
- The upcoming trips window covers 120 days — for dates beyond that, provide historical analysis
- Reference seasonal patterns confidently and suggest booking early

FOLLOW-UP SUGGESTIONS:
After your main response, suggest 2-3 relevant follow-up questions. Format at the very end:

<followups>
["Compare Pacific Queen vs Shogun", "Show me cheaper alternatives", "What about a 3-day trip instead?"]
</followups>

QUICK ACTIONS:
After responses about specific trips or boats, include 1-3 quick action buttons (after followups, at the very end):

<actions>
[
  {"label": "Compare these boats", "action": "compare", "data": ["Pacific Queen", "Shogun"]},
  {"label": "View Pacific Queen", "action": "view-boat", "data": "Pacific Queen"},
  {"label": "Show overnight trips", "action": "view-trips", "data": {"tripLength": "Overnight"}}
]
</actions>

Action types: "compare" (array of 2 boat names), "view-boat" (single boat name string), "view-trips" (object with filter keys).
Only include actions when they add clear navigation value. Skip if none are relevant.

GUIDELINES:
- Be friendly, conversational, helpful
- Use actual data in your answers
- Be honest about uncertainty
- Recommend specific boats by name when asked
- Reference specific conditions (temps, wind, forecast scores)
- Don't make up data you don't have
- Keep it focused on San Diego sportfishing
- Speak like a knowledgeable local angler, not a robot`;
}

async function streamChatMessage(userMessage, history, pageContext, onUpdate) {
  const response = await fetch(CHAT_PROXY_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: 'claude-opus-4-7',
      max_tokens: 800,
      stream: true,
      system: buildSystemPrompt(pageContext),
      messages: [...history, { role: 'user', content: userMessage }]
    })
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status} from worker`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let fullText = '';
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const data = JSON.parse(line.slice(6));
        if (data.type === 'content_block_delta' && data.delta?.type === 'text_delta') {
          fullText += data.delta.text || '';
          onUpdate(fullText);
        }
      } catch(e) {}
    }
  }

  return fullText;
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

  if (a.includes('departs') || a.includes('$') || a.includes('spots') || a.includes('book') || a.includes('trip-card')) {
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
