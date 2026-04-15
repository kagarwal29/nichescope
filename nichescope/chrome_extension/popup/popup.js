/**
 * NicheScope popup — settings management.
 */

document.addEventListener("DOMContentLoaded", () => {
  const apiUrlInput = document.getElementById("apiUrl");
  const apiKeyInput = document.getElementById("apiKey");
  const nicheIdInput = document.getElementById("nicheId");
  const saveBtn = document.getElementById("saveBtn");
  const statusDiv = document.getElementById("status");

  // Load saved settings
  chrome.storage.sync.get(["apiUrl", "apiKey", "nicheId"], (settings) => {
    apiUrlInput.value = settings.apiUrl || "http://localhost:8000";
    apiKeyInput.value = settings.apiKey || "";
    nicheIdInput.value = settings.nicheId || "";
  });

  // Save settings and test connection
  saveBtn.addEventListener("click", async () => {
    const apiUrl = apiUrlInput.value.trim().replace(/\/$/, "");
    const apiKey = apiKeyInput.value.trim();
    const nicheId = nicheIdInput.value.trim();

    if (!apiKey) {
      statusDiv.textContent = "API key is required";
      statusDiv.className = "status err";
      return;
    }

    // Save to chrome.storage
    chrome.storage.sync.set({ apiUrl, apiKey, nicheId });

    // Test connection
    statusDiv.textContent = "Testing connection...";
    statusDiv.className = "status";

    try {
      const response = await fetch(`${apiUrl}/health`);
      if (response.ok) {
        statusDiv.textContent = "✅ Connected to NicheScope!";
        statusDiv.className = "status ok";
      } else {
        statusDiv.textContent = `❌ Server responded with ${response.status}`;
        statusDiv.className = "status err";
      }
    } catch (err) {
      statusDiv.textContent = `❌ Cannot reach server: ${err.message}`;
      statusDiv.className = "status err";
    }
  });
});
