/* Email page logic — single combined flow (mirrors github.js) */

const listSelect = document.getElementById('list-select');
const emailRangeSelector = document.getElementById('email-range-selector');
const emailLangSelector = document.getElementById('email-lang-selector');
const btnEmailRun = document.getElementById('btn-email-run');
const emailStatus = document.getElementById('email-status');
const emailProgressLog = document.getElementById('email-progress-log');
const digestSection = document.getElementById('digest-section');
const digestContent = document.getElementById('digest-content');
const emailsSection = document.getElementById('emails-section');
const emailCount = document.getElementById('email-count');
const emailList = document.getElementById('email-list');

let selectedEmailDays = 3;
let selectedEmailLang = 'zh';

// Range selector
emailRangeSelector.addEventListener('click', function (e) {
  const btn = e.target.closest('.ds-range-btn');
  if (!btn) return;
  emailRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  selectedEmailDays = parseInt(btn.dataset.days, 10);
});

// Language selector
emailLangSelector.addEventListener('click', function (e) {
  const btn = e.target.closest('.ds-range-btn');
  if (!btn) return;
  emailLangSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  selectedEmailLang = btn.dataset.lang;
});

// Load mailing lists
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
    if (lists.length === 0) {
      showEmailStatus('请先在 Settings 页面添加邮件组', 'info');
    }
  } catch (e) {
    showEmailStatus('加载邮件组列表失败: ' + e.message, 'error');
  }
}

function showEmailStatus(msg, type) {
  emailStatus.textContent = msg;
  emailStatus.className = `status status-${type}`;
  emailStatus.classList.remove('hidden');
}

function hideEmailStatus() {
  emailStatus.classList.add('hidden');
}

// --- Markdown rendering helper (powered by marked.js) ---

function renderMarkdown(text) {
  if (typeof marked !== 'undefined') {
    const renderer = new marked.Renderer();
    const originalLinkRenderer = renderer.link.bind(renderer);
    renderer.link = function (href, title, text) {
      const html = originalLinkRenderer(href, title, text);
      return html.replace('<a ', '<a target="_blank" rel="noopener noreferrer" ');
    };
    return marked.parse(text || '', { renderer: renderer, breaks: true, gfm: true });
  }
  // fallback
  return '<p>' + escapeHtml(text || '') + '</p>';
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// --- Progress Log ---

const ICON_MAP = {
  progress: '⏳',
  done: '✅',
  error: '❌',
  retry: '🔄',
};

function clearProgressLog() {
  emailProgressLog.innerHTML = '';
  emailProgressLog.classList.add('hidden');
}

function appendProgressItem(type, message) {
  emailProgressLog.classList.remove('hidden');
  const item = document.createElement('div');
  item.className = `progress-item progress-${type}`;
  const icon = ICON_MAP[type] || '📌';
  const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  item.innerHTML = `<span class="progress-time">${time}</span> <span class="progress-icon">${icon}</span> <span class="progress-msg">${escapeHtml(message)}</span>`;
  if (type === 'progress') {
    item.classList.add('progress-active');
  }
  emailProgressLog.appendChild(item);
  emailProgressLog.scrollTop = emailProgressLog.scrollHeight;
}

function markProgressComplete() {
  emailProgressLog.querySelectorAll('.progress-active').forEach(el => {
    el.classList.remove('progress-active');
  });
}

// --- Combined SSE flow: load emails → render → generate digest ---

function runCombinedFlow() {
  const listId = listSelect.value;
  if (!listId) {
    showEmailStatus('请选择一个邮件组', 'info');
    return;
  }

  hideEmailStatus();
  clearProgressLog();
  btnEmailRun.disabled = true;
  btnEmailRun.innerHTML = '<span class="spinner"></span>加载中...';
  emailsSection.classList.add('hidden');
  digestSection.classList.add('hidden');

  const url = `/api/email/digest/stream?list_id=${encodeURIComponent(listId)}&days=${selectedEmailDays}&lang=${selectedEmailLang}`;
  const es = new EventSource(url);

  es.onmessage = function (e) {
    let event;
    try {
      event = JSON.parse(e.data);
    } catch {
      return;
    }

    if (event.type === 'progress') {
      appendProgressItem('progress', event.message);
    } else if (event.type === 'retry') {
      appendProgressItem('retry', event.message);
    } else if (event.type === 'emails_loaded') {
      // Email data fetched — render immediately
      markProgressComplete();
      appendProgressItem('done', '邮件加载完成，开始生成摘要...');
      renderEmails(event.data.emails || []);
      btnEmailRun.innerHTML = '<span class="spinner"></span>生成摘要中...';
    } else if (event.type === 'error') {
      appendProgressItem('error', event.message);
      markProgressComplete();
      showEmailStatus(event.message, 'error');
      es.close();
      resetButton();
    } else if (event.type === 'done') {
      markProgressComplete();
      appendProgressItem('done', '摘要生成成功！');
      es.close();
      renderDigest(event.data);
      showEmailStatus('加载完成，摘要已生成！', 'success');
      resetButton();
    }
  };

  es.onerror = function () {
    es.close();
    markProgressComplete();
    appendProgressItem('error', '连接中断，请重试');
    showEmailStatus('连接中断', 'error');
    resetButton();
  };
}

function resetButton() {
  btnEmailRun.disabled = false;
  btnEmailRun.textContent = '加载邮件并生成摘要';
}

// --- Rendering ---

function renderEmails(emails) {
  emailCount.textContent = emails.length;
  emailList.innerHTML = '';
  emailsSection.classList.remove('hidden');

  if (emails.length === 0) {
    emailList.innerHTML = '<p style="color:#718096;">该时间范围内没有邮件。</p>';
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

function renderDigest(data) {
  digestSection.classList.remove('hidden');
  digestContent.innerHTML = renderMarkdown(data.summary);
  if (data.generated_at) {
    const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
    digestContent.innerHTML += `<p style="color:#718096;font-size:0.85rem;margin-top:12px;">⏱️ 生成于 ${genTime}</p>`;
  }
}

// --- History Summaries ---

const historyToggle = document.getElementById('history-toggle');
const historyList = document.getElementById('history-list');
const historyContent = document.getElementById('history-content');
const historyDetail = document.getElementById('history-detail');
const historyBack = document.getElementById('history-back');

let historyExpanded = false;

historyToggle.addEventListener('click', function () {
  historyExpanded = !historyExpanded;
  historyToggle.querySelector('.toggle-icon').textContent = historyExpanded ? '▼' : '▶';
  if (historyExpanded) {
    historyList.classList.remove('hidden');
    historyContent.classList.add('hidden');
    loadHistorySummaries();
  } else {
    historyList.classList.add('hidden');
    historyContent.classList.add('hidden');
  }
});

historyBack.addEventListener('click', function () {
  historyContent.classList.add('hidden');
  historyList.classList.remove('hidden');
});

async function loadHistorySummaries() {
  try {
    const resp = await fetch('/api/summaries?type=email');
    const files = await resp.json();
    if (files.length === 0) {
      historyList.innerHTML = '<p style="color:#718096;padding:12px;">暂无历史摘要记录</p>';
      return;
    }
    historyList.innerHTML = files.map(f => {
      const sourceLabel = f.source_id;
      return `
        <div class="history-item" data-filename="${escapeHtml(f.filename)}">
          <div class="history-item-title">📧 ${escapeHtml(sourceLabel)}</div>
          <div class="history-item-meta">
            <span>📅 内容日期: ${f.content_date}</span>
            <span>🕐 生成日期: ${f.gen_date}</span>
            <span>🌐 ${f.lang === 'zh' ? '中文' : 'English'}</span>
          </div>
        </div>`;
    }).join('');

    historyList.querySelectorAll('.history-item').forEach(item => {
      item.addEventListener('click', () => viewHistorySummary(item.dataset.filename));
    });
  } catch (e) {
    historyList.innerHTML = '<p style="color:#e53e3e;">加载历史摘要失败: ' + escapeHtml(e.message) + '</p>';
  }
}

async function viewHistorySummary(filename) {
  historyList.classList.add('hidden');
  historyContent.classList.remove('hidden');
  historyDetail.innerHTML = '<p style="color:#718096;">加载中...</p>';
  try {
    const resp = await fetch(`/api/summaries/${encodeURIComponent(filename)}`);
    const data = await resp.json();
    if (data.error) {
      historyDetail.innerHTML = '<p style="color:#e53e3e;">' + escapeHtml(data.error) + '</p>';
      return;
    }
    // Strip YAML frontmatter (between --- delimiters)
    let content = data.content || '';
    const fmMatch = content.match(/^---\n[\s\S]*?\n---\n/);
    if (fmMatch) {
      content = content.slice(fmMatch[0].length);
    }
    historyDetail.innerHTML = renderMarkdown(content);
  } catch (e) {
    historyDetail.innerHTML = '<p style="color:#e53e3e;">加载失败: ' + escapeHtml(e.message) + '</p>';
  }
}

// Event listeners
btnEmailRun.addEventListener('click', runCombinedFlow);

// Init
loadLists();
