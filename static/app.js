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

// --- Markdown rendering helper ---

function renderMarkdown(text) {
  let html = escapeHtml(text || '');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
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

// Event listeners
btnEmailRun.addEventListener('click', runCombinedFlow);

// Init
loadLists();
