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

// --- Slack Workspace Management ---

const slackWsContainer = document.getElementById('slack-workspaces-container');

function showChannelPicker(parentDiv, allChannels, existingIds, wsIdx) {
  // Remove any existing picker
  const oldPicker = parentDiv.querySelector('.channel-picker');
  if (oldPicker) oldPicker.remove();

  const picker = document.createElement('div');
  picker.className = 'channel-picker';
  picker.style.cssText = 'margin-top:12px;padding:12px;border:1px solid #3182ce;border-radius:8px;background:#f7fafc;';

  // Sort: new channels first, then already-added
  const sorted = [...allChannels].sort((a, b) => {
    const aEx = existingIds.has(a.id) ? 1 : 0;
    const bEx = existingIds.has(b.id) ? 1 : 0;
    if (aEx !== bEx) return aEx - bEx;
    return a.name.localeCompare(b.name);
  });

  const newCount = sorted.filter(ch => !existingIds.has(ch.id)).length;

  picker.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
      <strong style="font-size:0.95rem;">Select Channels (${allChannels.length} found, ${newCount} new)</strong>
      <button class="btn btn-sm btn-secondary picker-close" style="padding:2px 8px;">✕</button>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
      <input type="text" class="picker-search" placeholder="Search channels..." style="flex:1;padding:6px 10px;border:1px solid #cbd5e0;border-radius:6px;font-size:0.9rem;">
      <button class="btn btn-sm btn-secondary picker-select-all">Select All</button>
      <button class="btn btn-sm btn-secondary picker-select-none">Select None</button>
    </div>
    <div class="picker-list" style="max-height:300px;overflow-y:auto;margin-bottom:8px;">
      ${sorted.map(ch => {
    const isExisting = existingIds.has(ch.id);
    const memberInfo = ch.num_members ? ` · ${ch.num_members} members` : '';
    const topicInfo = ch.topic ? ` · ${escapeHtml(ch.topic).substring(0, 60)}` : '';
    return `
          <label style="display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:4px;cursor:pointer;${isExisting ? 'opacity:0.5;' : ''}" class="picker-label" data-name="${escapeHtml(ch.name)}">
            <input type="checkbox" value="${escapeHtml(ch.id)}" data-name="${escapeHtml(ch.name)}" ${isExisting ? 'checked disabled' : ''} style="width:16px;height:16px;accent-color:#3182ce;">
            <span style="font-weight:500;">#${escapeHtml(ch.name)}</span>
            <span style="font-size:0.8rem;color:#718096;">${isExisting ? '(已添加)' : ''}${memberInfo}${topicInfo}</span>
          </label>`;
  }).join('')}
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-secondary btn-sm picker-cancel">Cancel</button>
      <button class="btn btn-primary btn-sm picker-confirm">Add Selected</button>
    </div>
  `;

  parentDiv.appendChild(picker);

  // Search filter
  const searchInput = picker.querySelector('.picker-search');
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.toLowerCase();
    picker.querySelectorAll('.picker-label').forEach(label => {
      const name = label.dataset.name.toLowerCase();
      label.style.display = name.includes(q) ? 'flex' : 'none';
    });
  });

  // Select all (only new, visible ones)
  picker.querySelector('.picker-select-all').addEventListener('click', () => {
    picker.querySelectorAll('.picker-label').forEach(label => {
      if (label.style.display === 'none') return;
      const cb = label.querySelector('input[type="checkbox"]');
      if (!cb.disabled) cb.checked = true;
    });
  });

  // Select none
  picker.querySelector('.picker-select-none').addEventListener('click', () => {
    picker.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      if (!cb.disabled) cb.checked = false;
    });
  });

  // Cancel / Close
  const closePicker = () => picker.remove();
  picker.querySelector('.picker-cancel').addEventListener('click', closePicker);
  picker.querySelector('.picker-close').addEventListener('click', closePicker);

  // Confirm
  picker.querySelector('.picker-confirm').addEventListener('click', () => {
    const ws = currentConfig.slack.workspaces[wsIdx];
    if (!ws.channels) ws.channels = [];
    let added = 0;
    picker.querySelectorAll('input[type="checkbox"]:checked:not(:disabled)').forEach(cb => {
      ws.channels.push({ id: cb.value, name: cb.dataset.name });
      added++;
    });
    picker.remove();
    if (added > 0) {
      renderSlackWorkspaces();
      showStatus(`Added ${added} channel(s). Click "Save All Settings" to persist.`, 'info');
    }
  });

  // Focus search
  searchInput.focus();
}


function renderSlackWorkspaces() {
  if (!slackWsContainer) return;
  slackWsContainer.innerHTML = '';
  const workspaces = currentConfig?.slack?.workspaces || [];
  if (workspaces.length === 0) {
    slackWsContainer.innerHTML = '<p style="color:#718096;">No Slack workspaces configured.</p>';
    return;
  }
  workspaces.forEach((ws, wsIdx) => {
    const div = document.createElement('div');
    div.className = 'list-item';
    div.style.flexDirection = 'column';
    div.style.alignItems = 'stretch';

    const tokenStatus = ws.token ? '✅ Token configured' : '⚠️ No token';
    const channelCount = (ws.channels || []).length;

    let channelsHtml = '';
    if (ws.channels && ws.channels.length > 0) {
      channelsHtml = '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;">' +
        '<div style="font-size:0.85rem;color:#718096;margin-bottom:4px;">Channels:</div>' +
        ws.channels.map((ch, chIdx) =>
          `<span style="display:inline-flex;align-items:center;gap:4px;background:#ebf4ff;color:#2b6cb0;padding:2px 8px;border-radius:12px;font-size:0.82rem;margin:2px 4px 2px 0;">` +
          `#${escapeHtml(ch.name)} ` +
          `<button onclick="removeSlackChannel(${wsIdx},${chIdx})" style="background:none;border:none;color:#c53030;cursor:pointer;font-size:0.8rem;padding:0 2px;">✕</button>` +
          `</span>`
        ).join('') +
        '</div>';
    }

    div.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <div class="info">
          <div class="name">${escapeHtml(ws.name)}</div>
          <div class="detail">${tokenStatus} · ${channelCount} channels</div>
        </div>
        <div style="display:flex;gap:6px;">
          <button class="btn btn-secondary btn-sm" data-ws-idx="${wsIdx}" data-action="fetch-channels">📥 Fetch Channels</button>
          <button class="btn btn-danger btn-sm" data-ws-idx="${wsIdx}" data-action="remove-ws">Remove</button>
        </div>
      </div>
      ${channelsHtml}
    `;

    // Event delegation for buttons
    div.querySelector('[data-action="remove-ws"]').addEventListener('click', () => {
      currentConfig.slack.workspaces.splice(wsIdx, 1);
      renderSlackWorkspaces();
    });

    div.querySelector('[data-action="fetch-channels"]').addEventListener('click', async (e) => {
      const btn = e.target;
      if (!ws.token) {
        showStatus('Please configure a token for this workspace first.', 'error');
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Fetching...';
      try {
        const resp = await fetch(`/api/slack/channels/fetch?workspace_id=${encodeURIComponent(ws.id)}`);
        const data = await resp.json();
        if (data.error) {
          showStatus('Failed to fetch channels: ' + data.error, 'error');
          return;
        }
        if (data.length === 0) {
          showStatus('No channels found in this workspace.', 'info');
          return;
        }
        // Show checkbox list panel
        const existing = new Set((ws.channels || []).map(c => c.id));
        showChannelPicker(div, data, existing, wsIdx);
      } catch (e) {
        showStatus('Failed to fetch channels: ' + e.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = '📥 Fetch Channels';
      }
    });

    slackWsContainer.appendChild(div);
  });
}

window.removeSlackChannel = function (wsIdx, chIdx) {
  currentConfig.slack.workspaces[wsIdx].channels.splice(chIdx, 1);
  renderSlackWorkspaces();
};

document.getElementById('btn-add-slack-ws').addEventListener('click', () => {
  const name = document.getElementById('new-slack-name').value.trim();
  const token = document.getElementById('new-slack-token').value.trim();
  if (!name) {
    showStatus('Please enter a workspace name.', 'error');
    return;
  }
  const id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '');
  if (!currentConfig.slack) currentConfig.slack = { workspaces: [] };
  if (!currentConfig.slack.workspaces) currentConfig.slack.workspaces = [];
  if (currentConfig.slack.workspaces.some(w => w.id === id)) {
    showStatus('A workspace with this ID already exists.', 'error');
    return;
  }
  currentConfig.slack.workspaces.push({ id, name, token, channels: [] });
  renderSlackWorkspaces();
  document.getElementById('new-slack-name').value = '';
  document.getElementById('new-slack-token').value = '';
  showStatus('Workspace added. Click "Save All Settings" to persist.', 'info');
});

// --- Load & Save ---

async function loadConfig() {
  try {
    const resp = await fetch('/api/config');
    currentConfig = await resp.json();
    renderProviders();
    renderLists();
    renderGithubRepos();
    renderSlackWorkspaces();
    // Load GitHub token
    githubTokenInput.value = currentConfig?.github?.token || '';
    // Load Feishu webhook URL
    document.getElementById('feishu-webhook').value = currentConfig?.feishu?.webhook_url || '';
    // Load Slack push webhook URL
    document.getElementById('slack-push-webhook').value = currentConfig?.slack?.push_webhook_url || '';
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

  // Update Feishu webhook URL from input
  if (!currentConfig.feishu) currentConfig.feishu = { webhook_url: '' };
  currentConfig.feishu.webhook_url = document.getElementById('feishu-webhook').value.trim();

  // Update Slack push webhook URL from input
  if (!currentConfig.slack) currentConfig.slack = { push_webhook_url: '', workspaces: [] };
  currentConfig.slack.push_webhook_url = document.getElementById('slack-push-webhook').value.trim();

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
