/**
 * NicheScope — Background service worker (Manifest V3).
 * Caches gap, demand, calendar, and format data for 1 hour.
 */
const DEFAULT_API_URL = "http://localhost:8000";
const CACHE_TTL_MS = 60 * 60 * 1000;
const cache = {
  gaps: { data: null, timestamp: 0 },
  demands: { data: null, timestamp: 0 },
  calendar: { data: null, timestamp: 0 },
  formats: { data: null, timestamp: 0 },
};

async function fetchCached(cacheKey, url, apiKey) {
  const now = Date.now();
  const entry = cache[cacheKey];
  if (entry?.data && now - entry.timestamp < CACHE_TTL_MS) return entry.data;
  const response = await fetch(url, { headers: { "X-API-Key": apiKey } });
  if (!response.ok) throw new Error(`API error: ${response.status}`);
  const data = await response.json();
  cache[cacheKey] = { data, timestamp: now };
  return data;
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  chrome.storage.sync.get(["apiUrl", "apiKey", "nicheId"], async (settings) => {
    const apiUrl = settings.apiUrl || DEFAULT_API_URL;
    const { apiKey, nicheId } = settings;
    if (!apiKey || !nicheId) {
      sendResponse({ error: "Not configured. Click the NicheScope icon to set up." });
      return;
    }
    try {
      const urls = {
        GET_GAPS:     `${apiUrl}/api/gaps?niche_id=${nicheId}&limit=5`,
        GET_DEMANDS:  `${apiUrl}/api/insights/demands?niche_id=${nicheId}`,
        GET_CALENDAR: `${apiUrl}/api/insights/calendar?niche_id=${nicheId}`,
        GET_FORMATS:  `${apiUrl}/api/insights/formats?niche_id=${nicheId}`,
      };
      const cacheKeys = { GET_GAPS: "gaps", GET_DEMANDS: "demands", GET_CALENDAR: "calendar", GET_FORMATS: "formats" };
      const key = cacheKeys[request.type];
      if (!key) { sendResponse({ error: `Unknown type: ${request.type}` }); return; }
      const data = await fetchCached(key, urls[request.type], apiKey);
      sendResponse({ data });
    } catch (err) {
      sendResponse({ error: err.message });
    }
  });
  return true;
});
