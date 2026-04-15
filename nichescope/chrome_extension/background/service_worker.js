/**
 * NicheScope — Background service worker (Manifest V3).
 * Handles API communication and caches data for gap analysis,
 * demand signals, seasonal calendar, and format intelligence.
 */

const DEFAULT_API_URL = "http://localhost:8000";

// Cache data for 1 hour
const CACHE_TTL_MS = 60 * 60 * 1000;
const cache = {
  gaps: { data: null, timestamp: 0 },
  demands: { data: null, timestamp: 0 },
  calendar: { data: null, timestamp: 0 },
  formats: { data: null, timestamp: 0 },
};

/**
 * Generic cached API fetcher.
 */
async function fetchCached(cacheKey, url, apiKey) {
  const now = Date.now();
  const entry = cache[cacheKey];
  if (entry && entry.data && now - entry.timestamp < CACHE_TTL_MS) {
    return entry.data;
  }

  const response = await fetch(url, {
    headers: { "X-API-Key": apiKey },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  const data = await response.json();
  cache[cacheKey] = { data, timestamp: now };
  return data;
}

/**
 * Listen for messages from content script or popup.
 */
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  chrome.storage.sync.get(["apiUrl", "apiKey", "nicheId"], async (settings) => {
    const apiUrl = settings.apiUrl || DEFAULT_API_URL;
    const apiKey = settings.apiKey;
    const nicheId = settings.nicheId;

    if (!apiKey || !nicheId) {
      sendResponse({ error: "Not configured. Click the NicheScope icon to set up." });
      return;
    }

    try {
      let data;

      switch (request.type) {
        case "GET_GAPS":
          data = await fetchCached("gaps", `${apiUrl}/api/gaps?niche_id=${nicheId}&limit=5`, apiKey);
          break;

        case "GET_DEMANDS":
          data = await fetchCached("demands", `${apiUrl}/api/insights/demands?niche_id=${nicheId}`, apiKey);
          break;

        case "GET_CALENDAR":
          data = await fetchCached("calendar", `${apiUrl}/api/insights/calendar?niche_id=${nicheId}`, apiKey);
          break;

        case "GET_FORMATS":
          data = await fetchCached("formats", `${apiUrl}/api/insights/formats?niche_id=${nicheId}`, apiKey);
          break;

        default:
          sendResponse({ error: `Unknown request type: ${request.type}` });
          return;
      }

      sendResponse({ data });
    } catch (err) {
      sendResponse({ error: err.message });
    }
  });
  return true; // async response
});
