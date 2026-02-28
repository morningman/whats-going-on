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
const dailySummaryMeta = document.getElementById('daily-summary-meta');
const dailySummaryContent = document.getElementById('daily-summary-content');

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

// --- Daily Summary ---

async function generateDailySummary(forceRefresh = false) {
  btnDailySummary.disabled = true;
  btnDailySummary.innerHTML = '<span class="spinner"></span>正在生成摘要...';
  btnDailySummaryRefresh.style.display = 'none';
  hideDailySummaryStatus();
  dailySummaryResult.classList.add('hidden');

  try {
    const url = '/api/daily-summary';
    const resp = await fetch(url, { method: 'POST' });
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
    btnDailySummary.textContent = '📋 生成每日摘要';
  }
}

async function loadCachedDailySummary() {
  try {
    const resp = await fetch('/api/daily-summary');
    const data = await resp.json();
    if (data.summary) {
      renderDailySummary(data);
    }
  } catch (e) {
    // No cached summary, fine
  }
}

function renderDailySummary(data) {
  dailySummaryResult.classList.remove('hidden');
  btnDailySummaryRefresh.style.display = 'inline-block';

  // Meta info
  let metaHtml = '';
  if (data.dates && data.dates.length > 0) {
    metaHtml += `<span class="meta-tag">📅 ${data.dates[0]} ~ ${data.dates[data.dates.length - 1]}</span>`;
  }
  if (data.total_emails !== undefined) {
    metaHtml += `<span class="meta-tag">📧 共 ${data.total_emails} 封邮件</span>`;
  }
  if (data.statistics) {
    const listNames = Object.keys(data.statistics);
    metaHtml += `<span class="meta-tag">📋 ${listNames.length} 个邮件组</span>`;
  }
  if (data.generated_at) {
    const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
    metaHtml += `<span class="meta-tag meta-time">⏱️ ${genTime}</span>`;
  }
  dailySummaryMeta.innerHTML = metaHtml;

  // Warnings
  let warningHtml = '';
  if (data.warnings && data.warnings.length > 0) {
    warningHtml = '<div class="daily-summary-warnings">';
    data.warnings.forEach(w => {
      warningHtml += `<div class="warning-item">⚠️ ${escapeHtml(w)}</div>`;
    });
    warningHtml += '</div>';
  }
  if (data.skipped_lists && data.skipped_lists.length > 0) {
    warningHtml += `<div class="daily-summary-warnings"><div class="warning-item">⏭️ 已跳过未认证的私有邮件组: ${escapeHtml(data.skipped_lists.join(', '))}</div></div>`;
  }

  // Summary content
  let html = data.summary || '';
  html = escapeHtml(html);
  // Headers
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // List items
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');

  dailySummaryContent.innerHTML = warningHtml + '<p>' + html + '</p>';
}

// Load emails for selected list and date
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

    // Also check for cached digest
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
    // No cached digest, that's fine
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
    const resp = await fetch(`/api/digest?list_id=${listId}&date=${date}`, {
      method: 'POST',
    });
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
  // Simple markdown-to-HTML: bold, headers, lists
  let html = data.summary || '';
  html = escapeHtml(html);
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // List items
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  digestContent.innerHTML = '<p>' + html + '</p>';
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
btnDailySummary.addEventListener('click', () => generateDailySummary(false));
btnDailySummaryRefresh.addEventListener('click', () => generateDailySummary(true));

// Init
loadLists();
loadCachedDailySummary();

