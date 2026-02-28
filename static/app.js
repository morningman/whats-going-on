/* Email Watcher - Main page logic */

const listSelect = document.getElementById('list-select');
const datePicker = document.getElementById('date-picker');
const btnLoad = document.getElementById('btn-load');
const btnDigest = document.getElementById('btn-digest');
const statusBar = document.getElementById('status-bar');
const digestSection = document.getElementById('digest-section');
const digestContent = document.getElementById('digest-content');
const emailsSection = document.getElementById('emails-section');
const emailCount = document.getElementById('email-count');
const emailList = document.getElementById('email-list');

// Daily Summary elements
const btnDailySummary = document.getElementById('btn-daily-summary');
const btnDailySummaryRefresh = document.getElementById('btn-daily-summary-refresh');
const dailySummaryStatus = document.getElementById('daily-summary-status');
const dailySummaryResult = document.getElementById('daily-summary-result');
const dsRangeSelector = document.getElementById('ds-range-selector');

// Track selected days (default 3)
let selectedDays = 3;

// Range selector event
dsRangeSelector.addEventListener('click', function (e) {
  const btn = e.target.closest('.ds-range-btn');
  if (!btn) return;
  dsRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  selectedDays = parseInt(btn.dataset.days, 10);
  // Try loading cached summary for the new range
  loadCachedDailySummary();
});

// Set default date to today
datePicker.value = new Date().toISOString().split('T')[0];

// Load mailing lists on page load
async function loadLists() {
  try {
    const resp = await fetch('/api/lists');
    const lists = await resp.json();
    lists.forEach(l => {
      const opt = document.createElement('option');
      opt.value = l.id;
      opt.textContent = `${l.name} (${l.type})`;
      listSelect.appendChild(opt);
    });
  } catch (e) {
    showStatus('Failed to load mailing lists', 'error');
  }
}

function showStatus(msg, type) {
  statusBar.textContent = msg;
  statusBar.className = `status status-${type}`;
  statusBar.classList.remove('hidden');
}

function hideStatus() {
  statusBar.classList.add('hidden');
}

function showDailySummaryStatus(msg, type) {
  dailySummaryStatus.textContent = msg;
  dailySummaryStatus.className = `status status-${type}`;
  dailySummaryStatus.classList.remove('hidden');
}

function hideDailySummaryStatus() {
  dailySummaryStatus.classList.add('hidden');
}

// ===== Markdown rendering helper =====

function renderMarkdown(text) {
  let html = escapeHtml(text || '');
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
  html = html.replace(/\n\n/g, '</p><p>');
  return '<p>' + html + '</p>';
}

// ===== Daily Summary =====

async function generateDailySummary(force = false) {
  btnDailySummary.disabled = true;
  btnDailySummary.innerHTML = '<span class="spinner"></span>正在生成摘要（可能需要 1-2 分钟）...';
  btnDailySummaryRefresh.style.display = 'none';
  hideDailySummaryStatus();
  dailySummaryResult.classList.add('hidden');
  dailySummaryResult.innerHTML = '';

  try {
    const params = new URLSearchParams({ days: selectedDays });
    if (force) params.set('force', 'true');
    const resp = await fetch(`/api/daily-summary?${params}`, { method: 'POST' });
    const data = await resp.json();
    if (data.error) {
      showDailySummaryStatus(data.error, 'error');
      return;
    }
    renderDailySummary(data);
    showDailySummaryStatus('摘要生成成功！', 'success');
  } catch (e) {
    showDailySummaryStatus('生成摘要失败: ' + e.message, 'error');
  } finally {
    btnDailySummary.disabled = false;
    btnDailySummary.textContent = '📋 生成摘要';
  }
}

async function loadCachedDailySummary() {
  try {
    const resp = await fetch(`/api/daily-summary?days=${selectedDays}`);
    const data = await resp.json();
    if (data.lists) {
      renderDailySummary(data);
    }
  } catch (e) {
    // No cached summary
  }
}

function renderDailySummary(data) {
  dailySummaryResult.classList.remove('hidden');
  btnDailySummaryRefresh.style.display = 'inline-block';

  const lists = data.lists || [];
  const dates = data.dates || [];
  const emailMeta = data.email_meta || {};
  const numDays = dates.length;

  // Build the complete HTML
  let html = '';

  // --- Meta bar ---
  html += '<div class="daily-summary-meta">';
  if (dates.length > 0) {
    html += `<span class="meta-tag">📅 ${dates[0]} ~ ${dates[dates.length - 1]}</span>`;
  }
  if (data.total_emails !== undefined) {
    html += `<span class="meta-tag">📧 共 ${data.total_emails} 封邮件</span>`;
  }
  html += `<span class="meta-tag">📋 ${lists.length} 个邮件组</span>`;
  if (data.generated_at) {
    const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
    html += `<span class="meta-tag meta-time">⏱️ ${genTime}</span>`;
  }
  html += '</div>';

  // --- Warnings ---
  if (data.warnings && data.warnings.length > 0) {
    html += '<div class="daily-summary-warnings">';
    data.warnings.forEach(w => {
      html += `<div class="warning-item">⚠️ ${escapeHtml(w)}</div>`;
    });
    html += '</div>';
  }
  if (data.skipped_lists && data.skipped_lists.length > 0) {
    html += `<div class="daily-summary-warnings"><div class="warning-item">⏭️ 已跳过未认证的私有邮件组: ${escapeHtml(data.skipped_lists.join(', '))}</div></div>`;
  }

  // --- Tab navigation ---
  if (lists.length === 0) {
    html += '<p style="color:#718096;">无可显示的邮件组</p>';
    dailySummaryResult.innerHTML = html;
    return;
  }

  html += '<div class="ds-tabs">';
  html += '<div class="ds-tab-nav" role="tablist">';
  lists.forEach((list, idx) => {
    const emailCount = data.statistics?.[list.name]?.total || 0;
    const activeClass = idx === 0 ? ' active' : '';
    html += `<button class="ds-tab-btn${activeClass}" data-tab="ds-tab-${idx}" role="tab">${escapeHtml(list.name)}<span class="ds-tab-count">${emailCount}</span></button>`;
  });
  html += '</div>';

  // --- Tab panels ---
  lists.forEach((list, idx) => {
    const hiddenClass = idx === 0 ? '' : ' hidden';
    html += `<div class="ds-tab-panel${hiddenClass}" id="ds-tab-${idx}" role="tabpanel">`;

    // Overview section
    const overviewLabel = numDays === 1 ? '📊 当日总览' : `📊 ${numDays}日总览`;
    html += '<div class="ds-overview">';
    html += `<h3 class="ds-section-label">${overviewLabel}</h3>`;
    html += `<div class="ds-overview-content digest-content">${renderMarkdown(list.overview)}</div>`;
    html += '</div>';

    // Day buttons
    const days = list.days || [];
    if (days.length > 0) {
      html += '<div class="ds-day-section">';
      html += '<h3 class="ds-section-label">📅 每日详情</h3>';
      html += '<div class="ds-day-btns">';
      days.forEach((day, dayIdx) => {
        const dayCount = data.statistics?.[list.name]?.per_day?.[day.date] || 0;
        html += `<button class="ds-day-btn" data-panel="ds-tab-${idx}" data-day="${dayIdx}">`;
        html += `<span class="ds-day-date">${day.date}</span>`;
        html += `<span class="ds-day-count">${dayCount} 封</span>`;
        html += `</button>`;
      });
      html += '</div>';

      // Day detail panels (hidden by default)
      days.forEach((day, dayIdx) => {
        html += `<div class="ds-day-detail hidden" id="ds-day-${idx}-${dayIdx}">`;
        html += `<h4>${day.date} 摘要</h4>`;
        html += `<div class="digest-content">${renderMarkdown(day.summary)}</div>`;

        // --- Email links for this day ---
        const listMeta = emailMeta[list.name] || {};
        const dayEmails = listMeta[day.date] || [];
        if (dayEmails.length > 0) {
          html += '<div class="ds-email-links">';
          html += '<h5 class="ds-email-links-title">📨 相关邮件</h5>';
          html += '<ul class="ds-email-list">';
          dayEmails.forEach(em => {
            const subject = escapeHtml(em.subject || '(no subject)');
            const from = escapeHtml(em.from || '');
            if (em.link) {
              html += `<li class="ds-email-link-item">`;
              html += `<a href="${escapeHtml(em.link)}" target="_blank" rel="noopener" class="ds-email-link">🔗 ${subject}</a>`;
              html += `<span class="ds-email-from">${from}</span>`;
              html += `</li>`;
            } else {
              html += `<li class="ds-email-link-item">`;
              html += `<span class="ds-email-nolink">${subject}</span>`;
              html += `<span class="ds-email-from">${from}</span>`;
              html += `</li>`;
            }
          });
          html += '</ul>';
          html += '</div>';
        }

        html += '</div>';
      });
      html += '</div>';
    }

    html += '</div>'; // tab panel
  });

  html += '</div>'; // ds-tabs

  dailySummaryResult.innerHTML = html;
}

// --- Event delegation for tabs and day buttons (registered once) ---
dailySummaryResult.addEventListener('click', function (e) {
  // Tab switching
  const tabBtn = e.target.closest('.ds-tab-btn');
  if (tabBtn) {
    const targetId = tabBtn.dataset.tab;
    // Deactivate all tabs
    dailySummaryResult.querySelectorAll('.ds-tab-btn').forEach(b => b.classList.remove('active'));
    dailySummaryResult.querySelectorAll('.ds-tab-panel').forEach(p => p.classList.add('hidden'));
    // Activate clicked tab
    tabBtn.classList.add('active');
    document.getElementById(targetId).classList.remove('hidden');
    return;
  }

  // Day button toggle
  const dayBtn = e.target.closest('.ds-day-btn');
  if (dayBtn) {
    const panelId = dayBtn.dataset.panel;
    const dayIdx = dayBtn.dataset.day;
    const detailId = `ds-day-${panelId.split('-').pop()}-${dayIdx}`;
    const detail = document.getElementById(detailId);
    if (detail) {
      const isVisible = !detail.classList.contains('hidden');
      // Collapse all day details in this panel
      const panel = document.getElementById(panelId);
      panel.querySelectorAll('.ds-day-detail').forEach(d => d.classList.add('hidden'));
      panel.querySelectorAll('.ds-day-btn').forEach(b => b.classList.remove('active'));
      // Toggle
      if (!isVisible) {
        detail.classList.remove('hidden');
        dayBtn.classList.add('active');
      }
    }
    return;
  }
});

// ===== Existing per-list email/digest functions =====

async function loadEmails() {
  const listId = listSelect.value;
  const date = datePicker.value;
  if (!listId || !date) {
    showStatus('Please select a mailing list and date.', 'info');
    return;
  }

  hideStatus();
  btnLoad.disabled = true;
  btnLoad.textContent = 'Loading...';
  emailsSection.classList.add('hidden');
  digestSection.classList.add('hidden');

  try {
    const resp = await fetch(`/api/emails?list_id=${listId}&date=${date}`);
    const data = await resp.json();
    if (data.error) {
      showStatus(data.error, 'error');
      return;
    }
    renderEmails(data.emails || []);
    btnDigest.disabled = false;
    loadCachedDigest(listId, date);
  } catch (e) {
    showStatus('Failed to load emails: ' + e.message, 'error');
  } finally {
    btnLoad.disabled = false;
    btnLoad.textContent = 'Load Emails';
  }
}

function renderEmails(emails) {
  emailCount.textContent = emails.length;
  emailList.innerHTML = '';
  emailsSection.classList.remove('hidden');

  if (emails.length === 0) {
    emailList.innerHTML = '<p style="color:#718096;">No emails found for this date.</p>';
    btnDigest.disabled = true;
    return;
  }

  emails.forEach(em => {
    const div = document.createElement('div');
    div.className = 'email-item';
    div.innerHTML = `
      <div class="subject">${escapeHtml(em.subject || '(no subject)')}</div>
      <div class="meta">${escapeHtml(em.from)} &middot; ${em.date}</div>
      <div class="body">${escapeHtml(em.body || '')}</div>
    `;
    div.querySelector('.subject').addEventListener('click', () => {
      div.querySelector('.body').classList.toggle('open');
    });
    emailList.appendChild(div);
  });
}

async function loadCachedDigest(listId, date) {
  try {
    const resp = await fetch(`/api/digest?list_id=${listId}&date=${date}`);
    const data = await resp.json();
    if (data.summary) {
      renderDigest(data);
    }
  } catch (e) {
    // No cached digest
  }
}

async function generateDigest() {
  const listId = listSelect.value;
  const date = datePicker.value;
  if (!listId || !date) return;

  btnDigest.disabled = true;
  btnDigest.innerHTML = '<span class="spinner"></span>Generating...';
  hideStatus();

  try {
    const resp = await fetch(`/api/digest?list_id=${listId}&date=${date}`, { method: 'POST' });
    const data = await resp.json();
    if (data.error) {
      showStatus(data.error, 'error');
      return;
    }
    renderDigest(data);
    showStatus('Digest generated successfully!', 'success');
  } catch (e) {
    showStatus('Failed to generate digest: ' + e.message, 'error');
  } finally {
    btnDigest.disabled = false;
    btnDigest.textContent = 'Generate Digest';
  }
}

function renderDigest(data) {
  digestSection.classList.remove('hidden');
  digestContent.innerHTML = renderMarkdown(data.summary);
  if (data.generated_at) {
    digestContent.innerHTML += `<p style="color:#718096;font-size:0.85rem;margin-top:12px;">Generated: ${data.generated_at}</p>`;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Event listeners
btnLoad.addEventListener('click', loadEmails);
btnDigest.addEventListener('click', generateDigest);
btnDailySummary.addEventListener('click', () => generateDailySummary(true));
btnDailySummaryRefresh.addEventListener('click', () => {
  // Delete cache for current range and regenerate
  fetch(`/api/daily-summary?days=${selectedDays}`, { method: 'DELETE' }).finally(() => generateDailySummary(true));
});

// Init
loadLists();
loadCachedDailySummary();
