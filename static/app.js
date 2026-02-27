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

// Init
loadLists();
