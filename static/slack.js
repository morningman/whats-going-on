/* Slack page logic — workspace → channel → SSE digest flow */

const workspaceSelect = document.getElementById('workspace-select');
const channelSelect = document.getElementById('channel-select');
const slackRangeSelector = document.getElementById('slack-range-selector');
const slackLangSelector = document.getElementById('slack-lang-selector');
const btnSlackRun = document.getElementById('btn-slack-run');
const slackStatus = document.getElementById('slack-status');
const slackProgressLog = document.getElementById('slack-progress-log');
const slackDigestSection = document.getElementById('slack-digest-section');
const slackDigestContent = document.getElementById('slack-digest-content');
const slackMessagesSection = document.getElementById('slack-messages-section');
const slackMsgList = document.getElementById('slack-msg-list');
const slackMsgCount = document.getElementById('slack-msg-count');

let selectedDays = 3;
let selectedLang = 'zh';
let selectedRange = null; // null = use days, 'last-week' = use date range
let lastSlackSummary = null;
let workspacesData = []; // Cached workspace/channel data

// --- Helpers ---

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
    return '<p>' + escapeHtml(text || '') + '</p>';
}

function getLastWeekRange() {
    const now = new Date();
    const dayOfWeek = now.getDay();
    const thisMonday = new Date(now);
    thisMonday.setDate(now.getDate() - ((dayOfWeek + 6) % 7));
    const lastMonday = new Date(thisMonday);
    lastMonday.setDate(thisMonday.getDate() - 7);
    const lastSunday = new Date(lastMonday);
    lastSunday.setDate(lastMonday.getDate() + 6);
    const fmt = d => d.toISOString().slice(0, 10);
    return { start: fmt(lastMonday), end: fmt(lastSunday) };
}

// --- Status ---

function showStatus(msg, type) {
    slackStatus.textContent = msg;
    slackStatus.className = `status status-${type}`;
    slackStatus.classList.remove('hidden');
}

function hideStatus() {
    slackStatus.classList.add('hidden');
}

// --- Progress Log ---

const ICON_MAP = {
    progress: '⏳',
    done: '✅',
    error: '❌',
    retry: '🔄',
};

function clearProgressLog() {
    slackProgressLog.innerHTML = '';
    slackProgressLog.classList.add('hidden');
}

function appendProgressItem(type, message) {
    slackProgressLog.classList.remove('hidden');
    const item = document.createElement('div');
    item.className = `progress-item progress-${type}`;
    const icon = ICON_MAP[type] || '📌';
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    item.innerHTML = `<span class="progress-time">${time}</span> <span class="progress-icon">${icon}</span> <span class="progress-msg">${escapeHtml(message)}</span>`;
    if (type === 'progress') {
        item.classList.add('progress-active');
    }
    slackProgressLog.appendChild(item);
    slackProgressLog.scrollTop = slackProgressLog.scrollHeight;
}

function markProgressComplete() {
    slackProgressLog.querySelectorAll('.progress-active').forEach(el => {
        el.classList.remove('progress-active');
    });
}

// --- Range / Language selectors ---

slackRangeSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    slackRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    if (btn.dataset.range === 'last-week') {
        selectedRange = 'last-week';
    } else {
        selectedRange = null;
        selectedDays = parseInt(btn.dataset.days, 10);
    }
});

slackLangSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    slackLangSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedLang = btn.dataset.lang;
});

// --- Load workspaces and channels ---

async function loadWorkspaces() {
    try {
        const resp = await fetch('/api/slack/channels');
        workspacesData = await resp.json();
        workspaceSelect.innerHTML = '<option value="">-- 选择工作区 --</option>';
        workspacesData.forEach(ws => {
            const opt = document.createElement('option');
            opt.value = ws.id;
            const status = ws.connected ? '' : ' (未配置 Token)';
            opt.textContent = `${ws.name}${status}`;
            workspaceSelect.appendChild(opt);
        });
        if (workspacesData.length === 0) {
            showStatus('请先在 Settings 页面添加 Slack 工作区', 'info');
        }
    } catch (e) {
        showStatus('加载工作区失败: ' + e.message, 'error');
    }
}

workspaceSelect.addEventListener('change', function () {
    const wsId = this.value;
    channelSelect.innerHTML = '<option value="">-- 选择频道 --</option>';
    channelSelect.disabled = true;

    if (!wsId) return;

    const ws = workspacesData.find(w => w.id === wsId);
    if (!ws) return;

    if (!ws.connected) {
        showStatus('该工作区未配置 Token，请先在 Settings 页面配置', 'info');
        return;
    }

    hideStatus();
    const channels = ws.channels || [];
    if (channels.length === 0) {
        showStatus('该工作区没有配置频道，请先在 Settings 页面添加频道', 'info');
        return;
    }

    channels.forEach(ch => {
        const opt = document.createElement('option');
        opt.value = ch.id;
        opt.textContent = `#${ch.name}`;
        channelSelect.appendChild(opt);
    });
    channelSelect.disabled = false;
});

// --- Combined SSE flow ---

function runCombinedFlow() {
    const wsId = workspaceSelect.value;
    const chId = channelSelect.value;
    if (!wsId) {
        showStatus('请选择一个工作区', 'info');
        return;
    }
    if (!chId) {
        showStatus('请选择一个频道', 'info');
        return;
    }

    hideStatus();
    clearProgressLog();
    btnSlackRun.disabled = true;
    btnSlackRun.innerHTML = '<span class="spinner"></span>加载中...';
    slackMessagesSection.classList.add('hidden');
    slackDigestSection.classList.add('hidden');

    let url;
    if (selectedRange === 'last-week') {
        const range = getLastWeekRange();
        url = `/api/slack/digest/stream?workspace_id=${encodeURIComponent(wsId)}&channel_id=${encodeURIComponent(chId)}&start_date=${range.start}&end_date=${range.end}&lang=${selectedLang}`;
    } else {
        url = `/api/slack/digest/stream?workspace_id=${encodeURIComponent(wsId)}&channel_id=${encodeURIComponent(chId)}&days=${selectedDays}&lang=${selectedLang}`;
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
        } else if (event.type === 'messages_loaded') {
            markProgressComplete();
            appendProgressItem('done', '消息加载完成，开始生成摘要...');
            renderMessages(event.data);
            btnSlackRun.innerHTML = '<span class="spinner"></span>生成摘要中...';
        } else if (event.type === 'error') {
            appendProgressItem('error', event.message);
            markProgressComplete();
            showStatus(event.message, 'error');
            es.close();
            resetButton();
        } else if (event.type === 'done') {
            markProgressComplete();
            appendProgressItem('done', '摘要生成成功！');
            es.close();
            let dateRangeLabel;
            if (selectedRange === 'last-week') {
                const range = getLastWeekRange();
                dateRangeLabel = `${range.start} ~ ${range.end}`;
            } else {
                const endDate = new Date();
                const startDate = new Date();
                startDate.setDate(endDate.getDate() - (selectedDays - 1));
                dateRangeLabel = `${startDate.toISOString().slice(0, 10)} ~ ${endDate.toISOString().slice(0, 10)}`;
            }
            renderDigest(event.data, dateRangeLabel);
            lastSlackSummary = event.data.summary || '';
            showPushButtons();
            showStatus('加载完成，摘要已生成！', 'success');
            resetButton();
        }
    };

    es.onerror = function () {
        es.close();
        markProgressComplete();
        appendProgressItem('error', '连接中断，请重试');
        showStatus('连接中断', 'error');
        resetButton();
    };
}

function resetButton() {
    btnSlackRun.disabled = false;
    btnSlackRun.textContent = '加载并生成摘要';
}

// --- Rendering ---

function renderMessages(data) {
    const messages = data.messages || [];
    slackMsgCount.textContent = messages.length;
    slackMessagesSection.classList.remove('hidden');

    if (messages.length === 0) {
        slackMsgList.innerHTML = '<p class="gh-empty">该时间范围内没有消息</p>';
        return;
    }

    slackMsgList.innerHTML = messages.map(msg => renderMessageItem(msg)).join('');
}

function renderMessageItem(msg) {
    const text = escapeHtml(msg.text || '').replace(/\n/g, '<br>');
    const reactions = (msg.reactions || []).map(r => `<span class="gh-label">${escapeHtml(r)}</span>`).join(' ');
    const threadBadge = msg.thread_reply_count > 0
        ? `<span class="gh-label" style="background:#e9d8fd;color:#553c9a;">💬 ${msg.thread_reply_count} replies</span>`
        : '';
    const time = msg.datetime ? new Date(msg.datetime).toLocaleString('zh-CN', { hour12: false }) : '';

    let repliesHtml = '';
    if (msg.replies_preview && msg.replies_preview.length > 0) {
        repliesHtml = '<div class="slack-thread-replies">' +
            msg.replies_preview.map(r =>
                `<div class="slack-reply">
                    <span class="slack-reply-user">↳ ${escapeHtml(r.user)}</span>
                    <span class="slack-reply-text">${escapeHtml(r.text || '').replace(/\n/g, '<br>')}</span>
                </div>`
            ).join('') +
            '</div>';
    }

    return `
    <div class="gh-item">
      <div class="gh-item-header">
        <span class="gh-state">💬</span>
        <span class="gh-item-title" style="font-weight:600;">${escapeHtml(msg.user)}</span>
        ${threadBadge}
      </div>
      <div class="slack-msg-text">${text}</div>
      ${repliesHtml}
      <div class="gh-item-meta">
        <span>🕐 ${time}</span>
        ${reactions}
      </div>
    </div>
  `;
}

function renderDigest(data, dateRangeLabel) {
    slackDigestSection.classList.remove('hidden');
    const titleEl = document.getElementById('slack-digest-title');
    if (titleEl) {
        const chName = channelSelect.options[channelSelect.selectedIndex]?.textContent || '';
        titleEl.textContent = dateRangeLabel
            ? `📊 ${chName} 讨论摘要（${dateRangeLabel}）`
            : `📊 ${chName} 讨论摘要`;
    }
    slackDigestContent.innerHTML = renderMarkdown(data.summary);
    let metaHtml = '';
    if (dateRangeLabel) {
        metaHtml += `<span>📅 数据范围: ${dateRangeLabel}</span>`;
    }
    if (data.generated_at) {
        const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
        if (metaHtml) metaHtml += `<span style="margin-left:16px;">⏱️ 生成于 ${genTime}</span>`;
        else metaHtml += `<span>⏱️ 生成于 ${genTime}</span>`;
    }
    if (data.stats) {
        const s = data.stats;
        metaHtml += `<span style="margin-left:16px;">💬 ${s.total_messages || 0} 条消息</span>`;
    }
    if (metaHtml) {
        slackDigestContent.innerHTML += `<p style="color:#718096;font-size:0.85rem;margin-top:12px;">${metaHtml}</p>`;
    }
}

// --- Feishu Push ---

const btnFeishuPush = document.getElementById('btn-feishu-push-slack');
const btnSlackPush = document.getElementById('btn-slack-push-slack');

function showPushButtons() {
    if (btnFeishuPush) btnFeishuPush.classList.remove('hidden');
    if (btnSlackPush) btnSlackPush.classList.remove('hidden');
}

if (btnFeishuPush) {
    btnFeishuPush.addEventListener('click', async function () {
        if (!lastSlackSummary) {
            showStatus('没有可推送的摘要内容', 'error');
            return;
        }
        const chName = channelSelect.options[channelSelect.selectedIndex]?.textContent || 'Slack 摘要';
        btnFeishuPush.disabled = true;
        btnFeishuPush.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/feishu/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastSlackSummary, title: `💬 ${chName}` }),
            });
            const result = await resp.json();
            showStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnFeishuPush.disabled = false;
            btnFeishuPush.textContent = '🐦 推送到飞书';
        }
    });
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
        const resp = await fetch('/api/summaries?type=slack');
        const files = await resp.json();
        if (files.length === 0) {
            historyList.innerHTML = '<p style="color:#718096;padding:12px;">暂无历史摘要记录</p>';
            return;
        }
        historyList.innerHTML = files.map(f => {
            const sourceLabel = f.source_id;
            return `
                <div class="history-item" data-filename="${escapeHtml(f.filename)}">
                    <div class="history-item-title">💬 ${escapeHtml(sourceLabel)}</div>
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

let lastHistorySummary = null;

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

// --- Feishu Push (history) ---

const btnFeishuPushHistory = document.getElementById('btn-feishu-push-history');
if (btnFeishuPushHistory) {
    btnFeishuPushHistory.addEventListener('click', async function () {
        if (!lastHistorySummary) {
            showStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnFeishuPushHistory.disabled = true;
        btnFeishuPushHistory.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/feishu/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastHistorySummary, title: '💬 历史 Slack 摘要' }),
            });
            const result = await resp.json();
            showStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnFeishuPushHistory.disabled = false;
            btnFeishuPushHistory.textContent = '🐦 推送到飞书';
        }
    });
}

// --- Slack Push ---

if (btnSlackPush) {
    btnSlackPush.addEventListener('click', async function () {
        if (!lastSlackSummary) {
            showStatus('没有可推送的摘要内容', 'error');
            return;
        }
        const chName = channelSelect.options[channelSelect.selectedIndex]?.textContent || 'Slack 摘要';
        btnSlackPush.disabled = true;
        btnSlackPush.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/slack/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastSlackSummary, title: `💬 ${chName}` }),
            });
            const result = await resp.json();
            showStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnSlackPush.disabled = false;
            btnSlackPush.textContent = '💬 推送到 Slack';
        }
    });
}

// --- Slack Push (history) ---

const btnSlackPushHistory = document.getElementById('btn-slack-push-history');
if (btnSlackPushHistory) {
    btnSlackPushHistory.addEventListener('click', async function () {
        if (!lastHistorySummary) {
            showStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnSlackPushHistory.disabled = true;
        btnSlackPushHistory.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/slack/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastHistorySummary, title: '💬 历史 Slack 摘要' }),
            });
            const result = await resp.json();
            showStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnSlackPushHistory.disabled = false;
            btnSlackPushHistory.textContent = '💬 推送到 Slack';
        }
    });
}

// --- Event listeners ---
btnSlackRun.addEventListener('click', runCombinedFlow);

// --- Init ---
loadWorkspaces();
