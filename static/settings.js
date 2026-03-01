/* What's Going On - Settings page logic */

const githubReposContainer = document.getElementById('github-repos-container');
const githubTokenInput = document.getElementById('github-token');

const statusBar = document.getElementById('status-bar');
const providersContainer = document.getElementById('providers-container');
const providerType = document.getElementById('new-provider-type');
const listsContainer = document.getElementById('lists-container');
const listType = document.getElementById('new-list-type');
const ponymailFields = document.getElementById('ponymail-fields');
const pipermailFields = document.getElementById('pipermail-fields');
const asfAuthStatus = document.getElementById('asf-auth-status');
const asfCookieInput = document.getElementById('asf-cookie');

let currentConfig = null;

// --- ASF Authentication ---

async function loadAsfAuthStatus() {
  try {
    const resp = await fetch('/api/asf-auth');
    const data = await resp.json();
    const auth = data.auth || {};
    const lists = data.lists || [];

    let html = '';

    // Auth status
    if (auth.ok) {
      const display = auth.fullname ? `${auth.fullname} (${auth.uid})` : auth.uid;
      html += `<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
        <span style="font-size:1.1em;">✅</span>
        <span style="color:#276749; font-weight:600;">Authenticated as ${escapeHtml(display)}</span>
      </div>`;
    } else {
      html += `<div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
        <span style="font-size:1.1em;">🔒</span>
        <span style="color:#c53030; font-weight:600;">Not authenticated</span>
      </div>`;
    }

    // Private lists info
    const privateLists = lists.filter(l => l.private);
    if (privateLists.length > 0) {
      const names = privateLists.map(l => `<strong>${escapeHtml(l.name)}</strong>`).join(', ');
      const statusIcon = auth.ok ? '✅' : '⚠️';
      html += `<p style="font-size:0.85rem; color:#718096;">
        ${statusIcon} Private lists requiring auth: ${names}
      </p>`;
    }

    asfAuthStatus.innerHTML = html;
  } catch (e) {
    asfAuthStatus.innerHTML = '<p style="color:#c53030; font-size:0.9rem;">Failed to load auth status.</p>';
  }
}

// Login with username/password
document.getElementById('btn-asf-login').addEventListener('click', async () => {
  const username = document.getElementById('asf-username').value.trim();
  const password = document.getElementById('asf-password').value;
  if (!username || !password) {
    showStatus('Please enter both username and password.', 'error');
    return;
  }
  const btn = document.getElementById('btn-asf-login');
  btn.disabled = true;
  btn.textContent = 'Logging in...';
  try {
    const resp = await fetch('/api/asf-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const result = await resp.json();
    showStatus(result.message, result.ok ? 'success' : 'error');
    if (result.ok) {
      document.getElementById('asf-username').value = '';
      document.getElementById('asf-password').value = '';
      loadAsfAuthStatus();
    }
  } catch (e) {
    showStatus('Login failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Login';
  }
});

// Verify & Save cookie (fallback)
document.getElementById('btn-asf-verify').addEventListener('click', async () => {
  const cookie = asfCookieInput.value.trim();
  if (!cookie) {
    showStatus('Please paste the session cookie first.', 'error');
    return;
  }
  const btn = document.getElementById('btn-asf-verify');
  btn.disabled = true;
  btn.textContent = 'Verifying...';
  try {
    const resp = await fetch('/api/asf-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie }),
    });
    const result = await resp.json();
    showStatus(result.message, result.ok ? 'success' : 'error');
    if (result.ok) {
      asfCookieInput.value = '';
      loadAsfAuthStatus();
    }
  } catch (e) {
    showStatus('Failed to verify cookie: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Verify & Save';
  }
});

// Toggle cookie visibility
document.getElementById('btn-asf-toggle-cookie').addEventListener('click', () => {
  const btn = document.getElementById('btn-asf-toggle-cookie');
  if (asfCookieInput.type === 'password') {
    asfCookieInput.type = 'text';
    btn.textContent = '🙈 Hide';
  } else {
    asfCookieInput.type = 'password';
    btn.textContent = '👁 Show';
  }
});

// Logout
document.getElementById('btn-asf-logout').addEventListener('click', async () => {
  if (!confirm('Clear ASF authentication?')) return;
  try {
    const resp = await fetch('/api/asf-auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie: '' }),
    });
    const result = await resp.json();
    showStatus(result.message, result.ok ? 'success' : 'error');
    loadAsfAuthStatus();
  } catch (e) {
    showStatus('Failed to clear auth: ' + e.message, 'error');
  }
});

// Provider type defaults
const PROVIDER_DEFAULTS = {
  anthropic: { model: 'claude-sonnet-4-20250514', placeholder: 'https://api.anthropic.com' },
  openai: { model: 'gpt-4o', placeholder: 'https://api.openai.com/v1' },
  google: { model: 'gemini-2.0-flash', placeholder: 'https://generativelanguage.googleapis.com' },
};

function showStatus(msg, type) {
  statusBar.textContent = msg;
  statusBar.className = `status status-${type}`;
  statusBar.classList.remove('hidden');
}

// --- Provider Management ---

// Update defaults when provider type changes
providerType.addEventListener('change', () => {
  const t = providerType.value;
  const defaults = PROVIDER_DEFAULTS[t] || {};
  document.getElementById('new-provider-model').value = defaults.model || '';
  document.getElementById('new-provider-base-url').placeholder = defaults.placeholder || '';
});

function renderProviders() {
  providersContainer.innerHTML = '';
  const providers = currentConfig?.llm?.providers || [];
  const activeId = currentConfig?.llm?.active_provider || '';

  if (providers.length === 0) {
    providersContainer.innerHTML = '<p style="color:#718096;">No LLM providers configured.</p>';
    return;
  }

  providers.forEach((p, idx) => {
    const isActive = p.id === activeId;
    const div = document.createElement('div');
    div.className = 'provider-item' + (isActive ? ' active' : '');

    const typeLabel = { anthropic: 'Anthropic', openai: 'OpenAI', google: 'Google' }[p.type] || p.type;
    const baseUrlDisplay = p.base_url || '(default)';

    div.innerHTML = `
      <div class="provider-radio">
        <input type="radio" name="active-provider" value="${escapeHtml(p.id)}" ${isActive ? 'checked' : ''}>
      </div>
      <div class="info">
        <div class="name">${escapeHtml(p.name)}</div>
        <div class="detail">${typeLabel} · ${escapeHtml(p.model)} · ${escapeHtml(baseUrlDisplay)}</div>
      </div>
      <button class="btn btn-danger btn-sm" data-idx="${idx}">Remove</button>
    `;

    div.querySelector('input[type="radio"]').addEventListener('change', () => {
      currentConfig.llm.active_provider = p.id;
      renderProviders();
    });

    div.querySelector('button').addEventListener('click', () => {
      removeProvider(idx);
    });

    providersContainer.appendChild(div);
  });
}

function removeProvider(idx) {
  const removed = currentConfig.llm.providers.splice(idx, 1)[0];
  // If we removed the active provider, select the first remaining
  if (removed.id === currentConfig.llm.active_provider) {
    currentConfig.llm.active_provider =
      currentConfig.llm.providers.length > 0 ? currentConfig.llm.providers[0].id : '';
  }
  renderProviders();
}

// Add provider
document.getElementById('btn-add-provider').addEventListener('click', () => {
  const name = document.getElementById('new-provider-name').value.trim();
  if (!name) {
    showStatus('Please enter a provider name.', 'error');
    return;
  }

  const type = providerType.value;
  const baseUrl = document.getElementById('new-provider-base-url').value.trim();
  const authToken = document.getElementById('new-provider-auth-token').value.trim();
  const model = document.getElementById('new-provider-model').value.trim();

  if (!authToken) {
    showStatus('Please enter an auth token.', 'error');
    return;
  }
  if (!model) {
    showStatus('Please enter a model name.', 'error');
    return;
  }

  // Generate ID from name
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');

  if (!currentConfig.llm) {
    currentConfig.llm = { active_provider: '', providers: [] };
  }
  if (!currentConfig.llm.providers) {
    currentConfig.llm.providers = [];
  }

  // Check for duplicate ID
  if (currentConfig.llm.providers.some(p => p.id === id)) {
    showStatus('A provider with this ID already exists.', 'error');
    return;
  }

  const provider = { id, name, type, base_url: baseUrl, auth_token: authToken, model };
  currentConfig.llm.providers.push(provider);

  // Auto-select if it's the first provider
  if (currentConfig.llm.providers.length === 1 || !currentConfig.llm.active_provider) {
    currentConfig.llm.active_provider = id;
  }

  renderProviders();

  // Clear form
  document.getElementById('new-provider-name').value = '';
  document.getElementById('new-provider-base-url').value = '';
  document.getElementById('new-provider-auth-token').value = '';
  // Reset model to current type default
  const defaults = PROVIDER_DEFAULTS[type] || {};
  document.getElementById('new-provider-model').value = defaults.model || '';

  showStatus('Provider added. Click "Save All Settings" to persist.', 'info');
});

// --- Mailing List Management (unchanged logic) ---

// Toggle fields based on selected type
listType.addEventListener('change', () => {
  const t = listType.value;
  ponymailFields.classList.toggle('hidden', t !== 'ponymail');
  pipermailFields.classList.toggle('hidden', t !== 'pipermail');
});

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
    const privateBadge = ml.private
      ? '<span style="background:#fed7d7; color:#c53030; font-size:0.75rem; padding:2px 6px; border-radius:3px; margin-left:6px;">🔒 PRIVATE</span>'
      : '';
    div.innerHTML = `
      <div class="info">
        <div class="name">${escapeHtml(ml.name)}${privateBadge}</div>
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

// --- GitHub Repo Management ---

function renderGithubRepos() {
  githubReposContainer.innerHTML = '';
  const repos = currentConfig?.github?.repos || [];
  if (repos.length === 0) {
    githubReposContainer.innerHTML = '<p style="color:#718096;">No GitHub repos configured.</p>';
    return;
  }
  repos.forEach((r, idx) => {
    const div = document.createElement('div');
    div.className = 'list-item';
    div.innerHTML = `
      <div class="info">
        <div class="name">${escapeHtml(r.name)}</div>
        <div class="detail">${escapeHtml(r.owner)}/${escapeHtml(r.repo)}</div>
      </div>
      <button class="btn btn-danger btn-sm" data-idx="${idx}">Remove</button>
    `;
    div.querySelector('button').addEventListener('click', () => {
      currentConfig.github.repos.splice(idx, 1);
      renderGithubRepos();
    });
    githubReposContainer.appendChild(div);
  });
}

document.getElementById('btn-add-gh-repo').addEventListener('click', () => {
  const repoStr = document.getElementById('new-gh-repo').value.trim();
  const displayName = document.getElementById('new-gh-name').value.trim();
  if (!repoStr) {
    showStatus('Please enter a repository (owner/repo).', 'error');
    return;
  }
  const parts = repoStr.split('/');
  if (parts.length !== 2 || !parts[0] || !parts[1]) {
    showStatus('Repository format should be owner/repo (e.g., apache/doris).', 'error');
    return;
  }
  const owner = parts[0].trim();
  const repo = parts[1].trim();
  const name = displayName || `${owner}/${repo}`;
  const id = `${owner}-${repo}`.toLowerCase();

  if (!currentConfig.github) currentConfig.github = { token: '', repos: [] };
  if (!currentConfig.github.repos) currentConfig.github.repos = [];

  if (currentConfig.github.repos.some(r => r.id === id)) {
    showStatus('This repo is already configured.', 'error');
    return;
  }

  currentConfig.github.repos.push({ id, name, owner, repo });
  renderGithubRepos();

  document.getElementById('new-gh-repo').value = '';
  document.getElementById('new-gh-name').value = '';
  showStatus('Repo added. Click "Save All Settings" to persist.', 'info');
});

// --- Load & Save ---

async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    currentConfig = await resp.json();
    renderProviders();
    renderLists();
    renderGithubRepos();
    // Load GitHub token
    githubTokenInput.value = currentConfig?.github?.token || '';
  } catch (e) {
    showStatus('Failed to load config', 'error');
  }
}

// --- Inline save status (shown above the Save button) ---
const saveStatusEl = document.getElementById('save-status');
let _saveStatusTimer = null;

function showSaveStatus(msg, type) {
  if (_saveStatusTimer) clearTimeout(_saveStatusTimer);
  saveStatusEl.textContent = msg;
  saveStatusEl.className = `status status-${type}`;
  saveStatusEl.classList.remove('hidden');
  // Auto-hide after 4 seconds
  _saveStatusTimer = setTimeout(() => {
    saveStatusEl.classList.add('hidden');
    _saveStatusTimer = null;
  }, 4000);
}

// Save all settings
document.getElementById('btn-save').addEventListener('click', async () => {
  // Update GitHub token from input
  if (!currentConfig.github) currentConfig.github = { token: '', repos: [] };
  currentConfig.github.token = githubTokenInput.value.trim();

  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentConfig),
    });
    const result = await resp.json();
    if (result.ok) {
      showSaveStatus('✅ Settings saved!', 'success');
      // Reload config from backend to reflect actual stored state
      await loadConfig();
    } else {
      showSaveStatus('❌ Failed to save: ' + (result.error || 'Unknown error'), 'error');
    }
  } catch (e) {
    showSaveStatus('❌ Failed to save settings: ' + e.message, 'error');
  }
});

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Init
loadConfig();
loadAsfAuthStatus();
