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
let selectedGhRange = null; // null = use days, 'last-week' = use start_date/end_date
let lastGhSummary = null; // Store latest digest text for Feishu push
let lastGhActivity = null; // Store latest activity data for Slack voting poll

// Helper: compute last week's Monday and Sunday (YYYY-MM-DD)
function getLastWeekRange() {
    const now = new Date();
    const dayOfWeek = now.getDay(); // 0=Sun, 1=Mon, ..., 6=Sat
    // Last week's Monday: go back to this week's Monday, then subtract 7
    const thisMonday = new Date(now);
    thisMonday.setDate(now.getDate() - ((dayOfWeek + 6) % 7));
    const lastMonday = new Date(thisMonday);
    lastMonday.setDate(thisMonday.getDate() - 7);
    const lastSunday = new Date(lastMonday);
    lastSunday.setDate(lastMonday.getDate() + 6);
    // Use local date to avoid UTC timezone shift
    const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return { start: fmt(lastMonday), end: fmt(lastSunday) };
}

// Range selector
ghRangeSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    ghRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (btn.dataset.range === 'last-week') {
        selectedGhRange = 'last-week';
    } else {
        selectedGhRange = null;
        selectedGhDays = parseInt(btn.dataset.days, 10);
    }
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

    let url;
    if (selectedGhRange === 'last-week') {
        const range = getLastWeekRange();
        url = `/api/github/digest/stream?repo_id=${encodeURIComponent(repoId)}&start_date=${range.start}&end_date=${range.end}&lang=${selectedGhLang}`;
    } else {
        url = `/api/github/digest/stream?repo_id=${encodeURIComponent(repoId)}&days=${selectedGhDays}&lang=${selectedGhLang}`;
    }
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
            lastGhActivity = event.data; // Store for Slack voting poll
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
            // Compute date range label for report header
            let dateRangeLabel;
            if (selectedGhRange === 'last-week') {
                const range = getLastWeekRange();
                dateRangeLabel = `${range.start} ~ ${range.end}`;
            } else {
                const endDate = new Date();
                const startDate = new Date();
                startDate.setDate(endDate.getDate() - (selectedGhDays - 1));
                dateRangeLabel = `${startDate.toISOString().slice(0, 10)} ~ ${endDate.toISOString().slice(0, 10)}`;
            }
            renderDigest(event.data, dateRangeLabel);
            lastGhSummary = event.data.summary || '';
            showPushButtons();
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

function renderDigest(data, dateRangeLabel) {
    ghDigestSection.classList.remove('hidden');
    // Update title with date range
    const titleEl = document.getElementById('gh-digest-title');
    if (titleEl) {
        titleEl.textContent = dateRangeLabel
            ? `📊 仓库活动摘要（${dateRangeLabel}）`
            : '📊 仓库活动摘要';
    }
    ghDigestContent.innerHTML = renderMarkdown(data.summary);
    let metaHtml = '';
    if (dateRangeLabel) {
        metaHtml += `<span>📅 数据范围: ${dateRangeLabel}</span>`;
    }
    if (data.generated_at) {
        const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
        if (metaHtml) metaHtml += `<span style="margin-left:16px;">⏱️ 生成于 ${genTime}</span>`;
        else metaHtml += `<span>⏱️ 生成于 ${genTime}</span>`;
    }
    if (metaHtml) {
        ghDigestContent.innerHTML += `<p style="color:#718096;font-size:0.85rem;margin-top:12px;">${metaHtml}</p>`;
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
        const resp = await fetch('/api/summaries?type=github');
        const files = await resp.json();
        if (files.length === 0) {
            historyList.innerHTML = '<p style="color:#718096;padding:12px;">暂无历史摘要记录</p>';
            return;
        }
        historyList.innerHTML = files.map(f => {
            const sourceLabel = f.source_id;
            return `
                <div class="history-item" data-filename="${escapeHtml(f.filename)}">
                    <div class="history-item-title">🐙 ${escapeHtml(sourceLabel)}</div>
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

let lastHistorySummary = null; // Store latest history summary for Feishu push

async function viewHistorySummary(filename) {
    historyList.classList.add('hidden');
    historyContent.classList.remove('hidden');
    historyDetail.innerHTML = '<p style="color:#718096;">加载中...</p>';
    const btnHistoryFeishu = document.getElementById('btn-feishu-push-history');
    const btnHistorySlack = document.getElementById('btn-slack-push-history');
    if (btnHistoryFeishu) btnHistoryFeishu.classList.add('hidden');
    if (btnHistorySlack) btnHistorySlack.classList.add('hidden');
    lastHistorySummary = null;
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
        lastHistorySummary = content;
        if (btnHistoryFeishu) btnHistoryFeishu.classList.remove('hidden');
        if (btnHistorySlack) btnHistorySlack.classList.remove('hidden');
    } catch (e) {
        historyDetail.innerHTML = '<p style="color:#e53e3e;">加载失败: ' + escapeHtml(e.message) + '</p>';
    }
}

// --- Feishu Push ---

const btnFeishuPushGh = document.getElementById('btn-feishu-push-gh');
const btnFeishuCreateDocGh = document.getElementById('btn-feishu-create-doc-gh');
const btnSlackPushGh = document.getElementById('btn-slack-push-gh');

function showPushButtons() {
    if (btnFeishuPushGh) btnFeishuPushGh.classList.remove('hidden');
    if (btnFeishuCreateDocGh) btnFeishuCreateDocGh.classList.remove('hidden');
    if (btnSlackPushGh) btnSlackPushGh.classList.remove('hidden');
}

if (btnFeishuPushGh) {
    btnFeishuPushGh.addEventListener('click', async function () {
        if (!lastGhSummary) {
            showGhStatus('没有可推送的摘要内容', 'error');
            return;
        }
        const repoName = repoSelect.options[repoSelect.selectedIndex]?.textContent || 'GitHub 摘要';
        btnFeishuPushGh.disabled = true;
        btnFeishuPushGh.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/feishu/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastGhSummary, title: `🐙 ${repoName}` }),
            });
            const result = await resp.json();
            showGhStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGhStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnFeishuPushGh.disabled = false;
            btnFeishuPushGh.textContent = '🐦 推送到飞书';
        }
    });
}

// --- Feishu Create Doc (Bot A + Bot B combined) ---

if (btnFeishuCreateDocGh) {
    btnFeishuCreateDocGh.addEventListener('click', async function () {
        if (!lastGhSummary) {
            showGhStatus('没有可推送的摘要内容', 'error');
            return;
        }
        const repoName = repoSelect.options[repoSelect.selectedIndex]?.textContent || 'GitHub 摘要';
        const repoId = repoSelect.value || 'unknown';

        // Compute date range label
        let dateRange = '';
        if (selectedGhRange === 'last-week') {
            const range = getLastWeekRange();
            dateRange = `${range.start} ~ ${range.end}`;
        } else {
            const endDate = new Date();
            const startDate = new Date();
            startDate.setDate(endDate.getDate() - (selectedGhDays - 1));
            dateRange = `${startDate.toISOString().slice(0, 10)} ~ ${endDate.toISOString().slice(0, 10)}`;
        }

        // Sub-folder: github/{repo-id}
        const subFolder = `github/${repoId}`;

        btnFeishuCreateDocGh.disabled = true;
        btnFeishuCreateDocGh.innerHTML = '<span class="spinner"></span>创建中...';
        try {
            const resp = await fetch('/api/feishu/create-and-push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: lastGhSummary,
                    title: `🐙 ${repoName}`,
                    date_range: dateRange,
                    sub_folder: subFolder,
                }),
            });
            const result = await resp.json();
            if (result.ok && result.doc_url) {
                showGhStatus(`${result.message} 文档链接: ${result.doc_url}`, 'success');
            } else {
                showGhStatus(result.message, result.ok ? 'success' : 'error');
            }
        } catch (e) {
            showGhStatus('创建文档失败: ' + e.message, 'error');
        } finally {
            btnFeishuCreateDocGh.disabled = false;
            btnFeishuCreateDocGh.textContent = '📄 创建飞书文档';
        }
    });
}

// --- Feishu Push (history) ---

const btnFeishuPushHistory = document.getElementById('btn-feishu-push-history');
if (btnFeishuPushHistory) {
    btnFeishuPushHistory.addEventListener('click', async function () {
        if (!lastHistorySummary) {
            showGhStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnFeishuPushHistory.disabled = true;
        btnFeishuPushHistory.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/feishu/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastHistorySummary, title: '🐙 历史 GitHub 摘要' }),
            });
            const result = await resp.json();
            showGhStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGhStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnFeishuPushHistory.disabled = false;
            btnFeishuPushHistory.textContent = '🐦 推送到飞书';
        }
    });
}

// --- Slack Push ---

if (btnSlackPushGh) {
    btnSlackPushGh.addEventListener('click', async function () {
        if (!lastGhSummary) {
            showGhStatus('没有可推送的摘要内容', 'error');
            return;
        }
        const repoName = repoSelect.options[repoSelect.selectedIndex]?.textContent || 'GitHub 摘要';
        btnSlackPushGh.disabled = true;
        btnSlackPushGh.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/slack/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: lastGhSummary,
                    title: `🐙 ${repoName}`,
                    voting_items: lastGhActivity || undefined,
                }),
            });
            const result = await resp.json();
            showGhStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGhStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnSlackPushGh.disabled = false;
            btnSlackPushGh.textContent = '💬 推送到 Slack';
        }
    });
}

// --- Slack Push (history) ---

const btnSlackPushHistory = document.getElementById('btn-slack-push-history');
if (btnSlackPushHistory) {
    btnSlackPushHistory.addEventListener('click', async function () {
        if (!lastHistorySummary) {
            showGhStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnSlackPushHistory.disabled = true;
        btnSlackPushHistory.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/slack/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    content: lastHistorySummary,
                    title: '🐙 历史 GitHub 摘要',
                    voting_items: lastGhActivity || undefined,
                }),
            });
            const result = await resp.json();
            showGhStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGhStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnSlackPushHistory.disabled = false;
            btnSlackPushHistory.textContent = '💬 推送到 Slack';
        }
    });
}

// Event listeners
btnGhRun.addEventListener('click', runCombinedFlow);

// --- Batch Summarize All Repos ---

const btnGhRunAll = document.getElementById('btn-gh-run-all');
const ghBatchSection = document.getElementById('gh-batch-section');
const ghBatchContent = document.getElementById('gh-batch-content');
const ghBatchTitle = document.getElementById('gh-batch-title');
const btnFeishuPushAll = document.getElementById('btn-feishu-push-all');

let batchSummaries = {};

function getDateRangeLabel() {
    if (selectedGhRange === 'last-week') {
        const range = getLastWeekRange();
        return `${range.start} ~ ${range.end}`;
    }
    const endDate = new Date();
    const startDate = new Date();
    const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return `${fmt(startDate)} ~ ${fmt(endDate)}`;
}

function summarizeRepo(repoId, repoName) {
    return new Promise((resolve) => {
        let url;
        if (selectedGhRange === 'last-week') {
            const range = getLastWeekRange();
            url = `/api/github/digest/stream?repo_id=${encodeURIComponent(repoId)}&start_date=${range.start}&end_date=${range.end}&lang=${selectedGhLang}`;
        } else {
            url = `/api/github/digest/stream?repo_id=${encodeURIComponent(repoId)}&days=${selectedGhDays}&lang=${selectedGhLang}`;
        }
        const es = new EventSource(url);
        es.onmessage = function (e) {
            let event;
            try { event = JSON.parse(e.data); } catch { return; }
            if (event.type === 'progress' || event.type === 'retry') {
                appendProgressItem(event.type, `[${repoName}] ${event.message}`);
            } else if (event.type === 'activity_loaded') {
                markProgressComplete();
                appendProgressItem('done', `[${repoName}] 数据加载完成，生成摘要中...`);
            } else if (event.type === 'error') {
                appendProgressItem('error', `[${repoName}] ${event.message}`);
                markProgressComplete(); es.close();
                resolve({ name: repoName, summary: null });
            } else if (event.type === 'done') {
                markProgressComplete();
                appendProgressItem('done', `[${repoName}] ✅ 摘要完成`);
                es.close();
                resolve({ name: repoName, summary: event.data?.summary || '' });
            }
        };
        es.onerror = function () {
            es.close(); markProgressComplete();
            appendProgressItem('error', `[${repoName}] 连接中断`);
            resolve({ name: repoName, summary: null });
        };
    });
}

// Run tasks with concurrency limit
async function runWithConcurrency(tasks, limit) {
    const results = [];
    let idx = 0;
    async function worker() {
        while (idx < tasks.length) {
            const i = idx++;
            results[i] = await tasks[i]();
        }
    }
    const workers = Array.from({ length: Math.min(limit, tasks.length) }, () => worker());
    await Promise.all(workers);
    return results;
}

async function runBatchFlow() {
    const options = Array.from(repoSelect.options).filter(o => o.value);
    if (options.length === 0) {
        showGhStatus('没有已配置的仓库，请先在 Settings 页面添加', 'info');
        return;
    }
    hideGhStatus(); clearProgressLog();
    batchSummaries = {};
    ghBatchSection.classList.add('hidden');
    ghDigestSection.classList.add('hidden');
    btnGhRunAll.disabled = true;
    btnGhRunAll.innerHTML = '<span class="spinner"></span>生成中...';

    const dateRange = getDateRangeLabel();
    const MAX_CONCURRENT = 3;
    appendProgressItem('progress', `开始为 ${options.length} 个仓库并行生成摘要（并发 ${MAX_CONCURRENT}，${dateRange}）`);

    const tasks = options.map(opt => () => summarizeRepo(opt.value, opt.textContent));
    const results = await runWithConcurrency(tasks, MAX_CONCURRENT);

    let successCount = 0;
    results.forEach((result, i) => {
        if (result && result.summary) {
            batchSummaries[options[i].value] = { name: result.name, summary: result.summary };
            successCount++;
        }
    });

    markProgressComplete();
    appendProgressItem('done', `全部完成！成功 ${successCount}/${options.length} 个仓库`);

    if (successCount > 0) {
        ghBatchTitle.textContent = `📊 全部仓库摘要（${dateRange}）`;
        let html = '';
        for (const [repoId, data] of Object.entries(batchSummaries)) {
            html += `<div style="margin-bottom:24px; padding-bottom:16px; border-bottom:1px solid rgba(255,255,255,0.1);">`;
            html += `<h3 style="color:#667eea; margin-bottom:8px;">🐙 ${escapeHtml(data.name)}</h3>`;
            html += renderMarkdown(data.summary);
            html += `</div>`;
        }
        ghBatchContent.innerHTML = html;
        ghBatchSection.classList.remove('hidden');
        showGhStatus(`${successCount} 个仓库摘要已生成`, 'success');
    } else {
        showGhStatus('没有成功生成任何摘要', 'error');
    }
    btnGhRunAll.disabled = false;
    btnGhRunAll.textContent = '🚀 生成全部摘要';
}

if (btnGhRunAll) btnGhRunAll.addEventListener('click', runBatchFlow);

// --- Batch Push to Feishu ---
if (btnFeishuPushAll) btnFeishuPushAll.addEventListener('click', async function () {
    const keys = Object.keys(batchSummaries);
    if (keys.length === 0) { showGhStatus('没有可推送的摘要', 'error'); return; }

    const dateRange = getDateRangeLabel();

    // Merge all summaries into one markdown document
    const sections = keys.map(repoId => {
        const data = batchSummaries[repoId];
        let content = (data.summary || '').replace(/^#\s+.*\n*/m, '').trim();
        return `# ${data.name}\n\n${content}`;
    });
    const mergedContent = sections.join('\n\n---\n\n');

    btnFeishuPushAll.disabled = true;
    btnFeishuPushAll.innerHTML = '<span class="spinner"></span>推送中...';

    try {
        const resp = await fetch('/api/feishu/create-batch-docs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content: mergedContent, date_range: dateRange }),
        });
        const result = await resp.json();
        if (result.ok) {
            let msg = result.message || '';
            if (result.doc_url) {
                msg += `<br>📄 <a href="${result.doc_url}" target="_blank" style="color:#81c784;text-decoration:underline;">${escapeHtml(result.doc_title || '文档')}</a>`;
            }
            if (result.folder_url) {
                lastBatchFolderUrl = result.folder_url;
                lastBatchDateRange = dateRange;
                msg += `<br>📁 <a href="${result.folder_url}" target="_blank" style="color:#4fc3f7;text-decoration:underline;">打开文件夹</a>`;
            }
            ghStatus.innerHTML = msg;
            ghStatus.className = 'status status-success';
            ghStatus.classList.remove('hidden');
            if (lastBatchFolderUrl) btnPushToGroup.classList.remove('hidden');
        } else {
            showGhStatus(result.message || '推送失败', 'error');
        }
    } catch (e) {
        showGhStatus('推送失败: ' + e.message, 'error');
    } finally {
        btnFeishuPushAll.disabled = false;
        btnFeishuPushAll.textContent = '📄 批量推送飞书文档';
    }
});

// --- Manual push folder link to Bot B ---
let lastBatchFolderUrl = '';
let lastBatchDateRange = '';
const btnPushToGroup = document.getElementById('btn-feishu-push-to-group');

if (btnPushToGroup) btnPushToGroup.addEventListener('click', async function () {
    if (!lastBatchFolderUrl) { showGhStatus('没有文件夹链接', 'error'); return; }

    btnPushToGroup.disabled = true;
    btnPushToGroup.innerHTML = '<span class="spinner"></span>推送中...';
    try {
        const resp = await fetch('/api/feishu/push-doc-link', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: `Github 每周摘要（${lastBatchDateRange}）`,
                doc_url: lastBatchFolderUrl,
            }),
        });
        const result = await resp.json();
        if (result.ok) {
            showGhStatus('✅ 已推送到飞书群！', 'success');
        } else {
            showGhStatus('推送失败: ' + (result.message || ''), 'error');
        }
    } catch (e) {
        showGhStatus('推送失败: ' + e.message, 'error');
    } finally {
        btnPushToGroup.disabled = false;
        btnPushToGroup.textContent = '🐦 推送到飞书群';
    }
});

// Init
loadRepos();
