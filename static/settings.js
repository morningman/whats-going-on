/* Email Watcher - Settings page logic */

const statusBar = document.getElementById('status-bar');
const llmApiKey = document.getElementById('llm-api-key');
const llmModel = document.getElementById('llm-model');
const listsContainer = document.getElementById('lists-container');
const listType = document.getElementById('new-list-type');
const ponymailFields = document.getElementById('ponymail-fields');
const pipermailFields = document.getElementById('pipermail-fields');

let currentConfig = null;

function showStatus(msg, type) {
  statusBar.textContent = msg;
  statusBar.className = `status status-${type}`;
  statusBar.classList.remove('hidden');
}

// Toggle fields based on selected type
listType.addEventListener('change', () => {
  const t = listType.value;
  ponymailFields.classList.toggle('hidden', t !== 'ponymail');
  pipermailFields.classList.toggle('hidden', t !== 'pipermail');
});

// Load existing config
async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    currentConfig = await resp.json();
    llmModel.value = currentConfig.llm?.model || 'claude-sonnet-4-20250514';
    // Don't overwrite password field with masked value
    renderLists();
  } catch (e) {
    showStatus('Failed to load config', 'error');
  }
}

function renderLists() {
  listsContainer.innerHTML = '';
  const lists = currentConfig?.mailing_lists || [];
  if (lists.length === 0) {
    listsContainer.innerHTML = '<p style="color:#718096;">No mailing lists configured.</p>';
    return;
  }
  lists.forEach((ml, idx) => {
    const div = document.createElement('div');
    div.className = 'list-item';
    div.innerHTML = `
      <div class="info">
        <div class="name">${escapeHtml(ml.name)}</div>
        <div class="detail">${ml.type} &middot; ${ml.id}</div>
      </div>
      <button class="btn btn-danger" data-idx="${idx}">Remove</button>
    `;
    div.querySelector('button').addEventListener('click', () => removeList(idx));
    listsContainer.appendChild(div);
  });
}

function removeList(idx) {
  currentConfig.mailing_lists.splice(idx, 1);
  renderLists();
}

function getNewListConfig() {
  const type = listType.value;
  const name = document.getElementById('new-list-name').value.trim();
  if (!name) return null;

  let config = {};
  if (type === 'ponymail') {
    config = {
      base_url: document.getElementById('pm-base-url').value.trim(),
      list: document.getElementById('pm-list').value.trim(),
      domain: document.getElementById('pm-domain').value.trim(),
    };
  } else if (type === 'pipermail') {
    config = {
      base_url: document.getElementById('pip-base-url').value.trim(),
      auth: null,
    };
  }

  // Generate ID from name
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
  return { id, name, type, config };
}

// Test connection
document.getElementById('btn-test').addEventListener('click', async () => {
  const listData = getNewListConfig();
  if (!listData) {
    showStatus('Please fill in the list name and config.', 'error');
    return;
  }
  const btn = document.getElementById('btn-test');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  try {
    const resp = await fetch('/api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: listData.type, config: listData.config }),
    });
    const result = await resp.json();
    showStatus(result.message, result.ok ? 'success' : 'error');
  } catch (e) {
    showStatus('Connection test failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
});

// Add list
document.getElementById('btn-add-list').addEventListener('click', () => {
  const listData = getNewListConfig();
  if (!listData) {
    showStatus('Please fill in the list name.', 'error');
    return;
  }
  if (!currentConfig.mailing_lists) currentConfig.mailing_lists = [];
  // Check for duplicate ID
  if (currentConfig.mailing_lists.some(ml => ml.id === listData.id)) {
    showStatus('A list with this ID already exists.', 'error');
    return;
  }
  currentConfig.mailing_lists.push(listData);
  renderLists();
  // Clear form
  document.getElementById('new-list-name').value = '';
  document.getElementById('pm-list').value = '';
  document.getElementById('pm-domain').value = '';
  showStatus('List added. Click "Save All Settings" to persist.', 'info');
});

// Save all settings
document.getElementById('btn-save').addEventListener('click', async () => {
  const apiKeyVal = llmApiKey.value.trim();
  // Only update API key if user typed a new one (not the masked value)
  if (apiKeyVal && !apiKeyVal.includes('...')) {
    currentConfig.llm.api_key = apiKeyVal;
  }
  currentConfig.llm.model = llmModel.value.trim();

  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig),
    });
    const result = await resp.json();
    if (result.ok) {
      showStatus('Settings saved!', 'success');
    } else {
      showStatus('Failed to save: ' + (result.error || 'Unknown error'), 'error');
    }
  } catch (e) {
    showStatus('Failed to save settings: ' + e.message, 'error');
  }
});

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Init
loadConfig();
