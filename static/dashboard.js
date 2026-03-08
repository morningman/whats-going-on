/* Dashboard page logic — global summary across all data sources */

const dsRangeSelector = document.getElementById('ds-range-selector');
const btnGlobalSummary = document.getElementById('btn-global-summary');
const btnGlobalSummaryRefresh = document.getElementById('btn-global-summary-refresh');
const globalSummaryStatus = document.getElementById('global-summary-status');
const globalSummaryResult = document.getElementById('global-summary-result');

let selectedDays = 3;
let lastDashboardSummary = null; // Store full summary for Feishu push

// Range selector
dsRangeSelector.addEventListener('click', function (e) {
    const btn = e.target.closest('.ds-range-btn');
    if (!btn) return;
    dsRangeSelector.querySelectorAll('.ds-range-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    selectedDays = parseInt(btn.dataset.days, 10);
    loadCachedGlobalSummary();
});

function showGlobalStatus(msg, type) {
    globalSummaryStatus.textContent = msg;
    globalSummaryStatus.className = `status status-${type}`;
    globalSummaryStatus.classList.remove('hidden');
}

function hideGlobalStatus() {
    globalSummaryStatus.classList.add('hidden');
}

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

async function generateGlobalSummary(force = false) {
    btnGlobalSummary.disabled = true;
    btnGlobalSummary.innerHTML = '<span class="spinner"></span>正在生成全局摘要...';
    btnGlobalSummaryRefresh.style.display = 'none';
    hideGlobalStatus();
    globalSummaryResult.classList.add('hidden');

    try {
        const params = new URLSearchParams({ days: selectedDays });
        if (force) params.set('force', 'true');
        const resp = await fetch(`/api/daily-summary?${params}`, { method: 'POST' });
        const data = await resp.json();
        if (data.error) {
            showGlobalStatus(data.error, 'error');
            return;
        }
        renderGlobalSummary(data);
        // Collect all overview texts for Feishu push
        const allOverviews = (data.lists || []).map(l => `## ${l.name}\n${l.overview}`).join('\n\n');
        lastDashboardSummary = allOverviews;
        showPushButtons();
        showGlobalStatus('摘要生成成功！', 'success');
    } catch (e) {
        showGlobalStatus('生成摘要失败: ' + e.message, 'error');
    } finally {
        btnGlobalSummary.disabled = false;
        btnGlobalSummary.textContent = '🚀 生成全局摘要';
    }
}

async function loadCachedGlobalSummary() {
    try {
        const resp = await fetch(`/api/daily-summary?days=${selectedDays}`);
        const data = await resp.json();
        if (data.lists) {
            renderGlobalSummary(data);
        }
    } catch (e) {
        // No cached summary
    }
}

function renderGlobalSummary(data) {
    globalSummaryResult.classList.remove('hidden');
    btnGlobalSummaryRefresh.style.display = 'inline-block';

    const lists = data.lists || [];
    const dates = data.dates || [];
    const emailMeta = data.email_meta || {};
    const numDays = dates.length;

    let html = '';

    // Meta bar
    html += '<div class="daily-summary-meta">';
    if (dates.length > 0) {
        html += `<span class="meta-tag">📅 ${dates[0]} ~ ${dates[dates.length - 1]}</span>`;
    }
    if (data.total_emails !== undefined) {
        html += `<span class="meta-tag">📧 邮件 ${data.total_emails} 封</span>`;
    }
    html += `<span class="meta-tag">📋 ${lists.length} 个邮件组</span>`;
    if (data.generated_at) {
        const genTime = new Date(data.generated_at).toLocaleString('zh-CN');
        html += `<span class="meta-tag meta-time">⏱️ ${genTime}</span>`;
    }
    html += '</div>';

    // Warnings
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

    if (lists.length === 0) {
        html += '<p style="color:#718096;">无可显示的邮件组</p>';
        globalSummaryResult.innerHTML = html;
        return;
    }

    // Tabs for lists
    html += '<div class="ds-tabs">';
    html += '<div class="ds-tab-nav" role="tablist">';
    lists.forEach((list, idx) => {
        const emailCount = data.statistics?.[list.name]?.total || 0;
        const activeClass = idx === 0 ? ' active' : '';
        html += `<button class="ds-tab-btn${activeClass}" data-tab="gs-tab-${idx}" role="tab">${escapeHtml(list.name)}<span class="ds-tab-count">${emailCount}</span></button>`;
    });
    html += '</div>';

    // Tab panels
    lists.forEach((list, idx) => {
        const hiddenClass = idx === 0 ? '' : ' hidden';
        html += `<div class="ds-tab-panel${hiddenClass}" id="gs-tab-${idx}" role="tabpanel">`;

        const overviewLabel = numDays === 1 ? '📊 当日总览' : `📊 ${numDays}日总览`;
        html += '<div class="ds-overview">';
        html += `<h3 class="ds-section-label">${overviewLabel}</h3>`;
        html += `<div class="ds-overview-content digest-content">${renderMarkdown(list.overview)}</div>`;
        html += '</div>';

        const days = list.days || [];
        if (days.length > 0) {
            html += '<div class="ds-day-section">';
            html += '<h3 class="ds-section-label">📅 每日详情</h3>';
            html += '<div class="ds-day-btns">';
            days.forEach((day, dayIdx) => {
                const dayCount = data.statistics?.[list.name]?.per_day?.[day.date] || 0;
                html += `<button class="ds-day-btn" data-panel="gs-tab-${idx}" data-day="${dayIdx}">`;
                html += `<span class="ds-day-date">${day.date}</span>`;
                html += `<span class="ds-day-count">${dayCount} 封</span>`;
                html += `</button>`;
            });
            html += '</div>';

            days.forEach((day, dayIdx) => {
                html += `<div class="ds-day-detail hidden" id="gs-day-${idx}-${dayIdx}">`;
                html += `<h4>${day.date} 摘要</h4>`;
                html += `<div class="digest-content">${renderMarkdown(day.summary)}</div>`;

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
                            html += `<li class="ds-email-link-item"><a href="${escapeHtml(em.link)}" target="_blank" rel="noopener" class="ds-email-link">🔗 ${subject}</a><span class="ds-email-from">${from}</span></li>`;
                        } else {
                            html += `<li class="ds-email-link-item"><span class="ds-email-nolink">${subject}</span><span class="ds-email-from">${from}</span></li>`;
                        }
                    });
                    html += '</ul>';
                    html += '</div>';
                }

                html += '</div>';
            });
            html += '</div>';
        }

        html += '</div>';
    });

    html += '</div>';
    globalSummaryResult.innerHTML = html;
}

// Event delegation for tabs and day buttons
globalSummaryResult.addEventListener('click', function (e) {
    const tabBtn = e.target.closest('.ds-tab-btn');
    if (tabBtn) {
        const targetId = tabBtn.dataset.tab;
        globalSummaryResult.querySelectorAll('.ds-tab-btn').forEach(b => b.classList.remove('active'));
        globalSummaryResult.querySelectorAll('.ds-tab-panel').forEach(p => p.classList.add('hidden'));
        tabBtn.classList.add('active');
        document.getElementById(targetId).classList.remove('hidden');
        return;
    }

    const dayBtn = e.target.closest('.ds-day-btn');
    if (dayBtn) {
        const panelId = dayBtn.dataset.panel;
        const dayIdx = dayBtn.dataset.day;
        const detailId = `gs-day-${panelId.split('-').pop()}-${dayIdx}`;
        const detail = document.getElementById(detailId);
        if (detail) {
            const isVisible = !detail.classList.contains('hidden');
            const panel = document.getElementById(panelId);
            panel.querySelectorAll('.ds-day-detail').forEach(d => d.classList.add('hidden'));
            panel.querySelectorAll('.ds-day-btn').forEach(b => b.classList.remove('active'));
            if (!isVisible) {
                detail.classList.remove('hidden');
                dayBtn.classList.add('active');
            }
        }
        return;
    }
});

// --- Feishu Push ---

const btnFeishuPushDashboard = document.getElementById('btn-feishu-push-dashboard');
const btnSlackPushDashboard = document.getElementById('btn-slack-push-dashboard');

function showPushButtons() {
    if (btnFeishuPushDashboard) btnFeishuPushDashboard.classList.remove('hidden');
    if (btnSlackPushDashboard) btnSlackPushDashboard.classList.remove('hidden');
}

if (btnFeishuPushDashboard) {
    btnFeishuPushDashboard.addEventListener('click', async function () {
        if (!lastDashboardSummary) {
            showGlobalStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnFeishuPushDashboard.disabled = true;
        btnFeishuPushDashboard.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/feishu/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastDashboardSummary, title: '📊 全局信息汇总' }),
            });
            const result = await resp.json();
            showGlobalStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGlobalStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnFeishuPushDashboard.disabled = false;
            btnFeishuPushDashboard.textContent = '🐦 推送到飞书';
        }
    });
}

// --- Slack Push ---

if (btnSlackPushDashboard) {
    btnSlackPushDashboard.addEventListener('click', async function () {
        if (!lastDashboardSummary) {
            showGlobalStatus('没有可推送的摘要内容', 'error');
            return;
        }
        btnSlackPushDashboard.disabled = true;
        btnSlackPushDashboard.innerHTML = '<span class="spinner"></span>推送中...';
        try {
            const resp = await fetch('/api/slack/push', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: lastDashboardSummary, title: '📊 全局信息汇总' }),
            });
            const result = await resp.json();
            showGlobalStatus(result.message, result.ok ? 'success' : 'error');
        } catch (e) {
            showGlobalStatus('推送失败: ' + e.message, 'error');
        } finally {
            btnSlackPushDashboard.disabled = false;
            btnSlackPushDashboard.textContent = '💬 推送到 Slack';
        }
    });
}

// Event listeners
btnGlobalSummary.addEventListener('click', () => generateGlobalSummary(true));
btnGlobalSummaryRefresh.addEventListener('click', () => {
    fetch(`/api/daily-summary?days=${selectedDays}`, { method: 'DELETE' }).finally(() => generateGlobalSummary(true));
});

// Init
loadCachedGlobalSummary();
