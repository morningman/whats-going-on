/* GitHub page logic — single combined flow */

const repoSelect = document.getElementById('repo-select');
const ghRangeSelector = document.getElementById('gh-range-selector');
const ghLangSelector = document.getElementById('gh-lang-selector');
const btnGhRun = document.getElementById('btn-gh-run');
const ghStatus = document.getElementById('gh-status');
const ghProgressLog = document.getElementById('gh-progress-log');
const ghDigestSection = document.getElementById('gh-digest-section');
const ghDigestContent = document.getElementById('gh-digest-content');
const ghActivitySection = document.getElementById('gh-activity-section');
const ghPrList = document.getElementById('gh-pr-list');
const ghIssueList = document.getElementById('gh-issue-list');
const ghPrCount = document.getElementById('gh-pr-count');
const ghIssueCount = document.getElementById('gh-issue-count');

let selectedGhDays = 3;
let selectedGhLang = 'zh';

// Range selector
ghRangeSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    ghRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedGhDays = parseInt(btn.dataset.days, 10);
});

// Language selector
ghLangSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    ghLangSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedGhLang = btn.dataset.lang;
});

// Tab switching
ghActivitySection.addEventListener('click', function (e) {
    const tabBtn = e.target.closest('.ds-tab-btn');
    if (!tabBtn) return;
    const targetId = tabBtn.dataset.tab;
    ghActivitySection.querySelectorAll('.ds-tab-btn').forEach(b => b.classList.remove('active'));
    ghActivitySection.querySelectorAll('.ds-tab-panel').forEach(p => p.classList.add('hidden'));
    tabBtn.classList.add('active');
    document.getElementById(targetId).classList.remove('hidden');
});

// Load repos
async function loadRepos() {
    try {
        const resp = await fetch('/api/github/repos');
        const repos = await resp.json();
        repos.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.id;
            opt.textContent = `${r.name} (${r.owner}/${r.repo})`;
            repoSelect.appendChild(opt);
        });
        if (repos.length === 0) {
            showGhStatus('请先在 Settings 页面添加 GitHub 仓库', 'info');
        }
    } catch (e) {
        showGhStatus('加载仓库列表失败: ' + e.message, 'error');
    }
}

function showGhStatus(msg, type) {
    ghStatus.textContent = msg;
    ghStatus.className = `status status-${type}`;
    ghStatus.classList.remove('hidden');
}

function hideGhStatus() {
    ghStatus.classList.add('hidden');
}

// --- Progress Log ---

const ICON_MAP = {
    progress: '⏳',
    done: '✅',
    error: '❌',
    retry: '🔄',
};

function clearProgressLog() {
    ghProgressLog.innerHTML = '';
    ghProgressLog.classList.add('hidden');
}

function appendProgressItem(type, message) {
    ghProgressLog.classList.remove('hidden');
    const item = document.createElement('div');
    item.className = `progress-item progress-${type}`;
    const icon = ICON_MAP[type] || '📌';
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    item.innerHTML = `<span class="progress-time">${time}</span> <span class="progress-icon">${icon}</span> <span class="progress-msg">${escapeHtml(message)}</span>`;
    if (type === 'progress') {
        item.classList.add('progress-active');
    }
    ghProgressLog.appendChild(item);
    ghProgressLog.scrollTop = ghProgressLog.scrollHeight;
}

function markProgressComplete() {
    ghProgressLog.querySelectorAll('.progress-active').forEach(el => {
        el.classList.remove('progress-active');
    });
}

// --- Combined SSE flow: load activity → render → generate digest ---

function runCombinedFlow() {
    const repoId = repoSelect.value;
    if (!repoId) {
        showGhStatus('请选择一个仓库', 'info');
        return;
    }

    hideGhStatus();
    clearProgressLog();
    btnGhRun.disabled = true;
    btnGhRun.innerHTML = '<span class="spinner"></span>加载中...';
    ghActivitySection.classList.add('hidden');
    ghDigestSection.classList.add('hidden');

    const url = `/api/github/digest/stream?repo_id=${encodeURIComponent(repoId)}&days=${selectedGhDays}&lang=${selectedGhLang}`;
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
        } else if (event.type === 'activity_loaded') {
            // Activity data fetched — render it immediately
            markProgressComplete();
            appendProgressItem('done', '活动数据加载完成，开始生成摘要...');
            renderActivity(event.data);
            btnGhRun.innerHTML = '<span class="spinner"></span>生成摘要中...';
        } else if (event.type === 'error') {
            appendProgressItem('error', event.message);
            markProgressComplete();
            showGhStatus(event.message, 'error');
            es.close();
            resetButton();
        } else if (event.type === 'done') {
            markProgressComplete();
            appendProgressItem('done', '摘要生成成功！');
            es.close();
            renderDigest(event.data);
            showGhStatus('加载完成，摘要已生成！', 'success');
            resetButton();
        }
    };

    es.onerror = function () {
        es.close();
        markProgressComplete();
        appendProgressItem('error', '连接中断，请重试');
        showGhStatus('连接中断', 'error');
        resetButton();
    };
}

function resetButton() {
    btnGhRun.disabled = false;
    btnGhRun.textContent = '加载并生成摘要';
}

// --- Rendering ---

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

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

function timeAgo(dateStr) {
    const now = new Date();
    const date = new Date(dateStr);
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
}

function renderActivity(data) {
    const prs = data.pulls || [];
    const issues = data.issues || [];

    ghPrCount.textContent = prs.length;
    ghIssueCount.textContent = issues.length;
    ghActivitySection.classList.remove('hidden');

    if (prs.length === 0) {
        ghPrList.innerHTML = '<p class="gh-empty">最近没有 Pull Request 活动</p>';
    } else {
        ghPrList.innerHTML = prs.map(pr => renderPrItem(pr)).join('');
    }

    if (issues.length === 0) {
        ghIssueList.innerHTML = '<p class="gh-empty">最近没有 Issue 活动</p>';
    } else {
        ghIssueList.innerHTML = issues.map(issue => renderIssueItem(issue)).join('');
    }
}

function renderPrItem(pr) {
    const stateIcon = pr.merged ? '🟣' : pr.state === 'open' ? '🟢' : '🔴';
    const stateText = pr.merged ? 'Merged' : pr.state === 'open' ? 'Open' : 'Closed';
    const labels = pr.labels.map(l => `<span class="gh-label">${escapeHtml(l)}</span>`).join('');
    const draft = pr.draft ? '<span class="gh-draft">Draft</span>' : '';

    return `
    <div class="gh-item">
      <div class="gh-item-header">
        <span class="gh-state">${stateIcon}</span>
        <a href="${escapeHtml(pr.html_url)}" target="_blank" rel="noopener" class="gh-item-title">
          #${pr.number} ${escapeHtml(pr.title)}
        </a>
        ${draft}
      </div>
      <div class="gh-item-meta">
        <span>👤 ${escapeHtml(pr.user)}</span>
        <span>${stateText}</span>
        <span>Updated ${timeAgo(pr.updated_at)}</span>
        ${labels}
      </div>
    </div>
  `;
}

function renderIssueItem(issue) {
    const stateIcon = issue.state === 'open' ? '🟢' : '🔴';
    const stateText = issue.state === 'open' ? 'Open' : 'Closed';
    const labels = issue.labels.map(l => `<span class="gh-label">${escapeHtml(l)}</span>`).join('');

    return `
    <div class="gh-item">
      <div class="gh-item-header">
        <span class="gh-state">${stateIcon}</span>
        <a href="${escapeHtml(issue.html_url)}" target="_blank" rel="noopener" class="gh-item-title">
          #${issue.number} ${escapeHtml(issue.title)}
        </a>
      </div>
      <div class="gh-item-meta">
        <span>👤 ${escapeHtml(issue.user)}</span>
        <span>${stateText}</span>
        <span>💬 ${issue.comments} comments</span>
        <span>Updated ${timeAgo(issue.updated_at)}</span>
        ${labels}
      </div>
    </div>
  `;
}

function renderDigest(data) {
    ghDigestSection.classList.remove('hidden');
    ghDigestContent.innerHTML = renderMarkdown(data.summary);
    if (data.generated_at) {
        const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
        ghDigestContent.innerHTML += `<p style="color:#718096;font-size:0.85rem;margin-top:12px;">⏱️ 生成于 ${genTime}</p>`;
    }
}

// Event listeners
btnGhRun.addEventListener('click', runCombinedFlow);

// Init
loadRepos();
