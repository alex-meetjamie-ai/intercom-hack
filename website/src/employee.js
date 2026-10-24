const $ = id => document.getElementById(id);
const element = (tag, className, text) => {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
let socket, connected = false, requests = [], submitted = null, stopped = false;
let previousPending = new Set();

function render() {
  const pending = requests.filter(request => request.status === 'pending');
  document.title = `${pending.length ? `(${pending.length}) ` : ''}Admin — Jamie`;
  $('employee-connection').textContent = connected ? '● Notifications connected' : '○ Notifications offline · reconnecting';
  $('employee-connection').classList.toggle('connected', connected);
  const visible = pending.length ? pending : requests.slice(-1);
  if (!visible.length) {
    $('employee-requests').replaceChildren(element('p', 'employee-empty', 'No visitor waiting. Keep this page open to receive approval requests.'));
    return;
  }
  $('employee-requests').replaceChildren(...visible.map(request => {
    const card = element('article', `approval-card ${request.status}`);
    const heading = element('div', 'approval-heading');
    heading.append(element('h3', '', request.name), element('span', 'approval-state', {
      pending: 'AWAITING YOUR DECISION', allowed: 'EMPLOYEE ALLOWED ENTRY', denied: 'ENTRY DENIED',
      expired: 'EXPIRED · NO ENTRY', cancelled: 'CALL ENDED · CANCELLED'
    }[request.status]));
    card.append(heading);
    if (request.heard.length) card.append(element('p', 'approval-label', 'VISITOR SAID'), element('blockquote', 'approval-words', request.heard.join(' ')));
    const evidence = element('div', 'approval-evidence');
    if (request.matched_records.length) {
      evidence.append(element('span', '', 'Matching record: '));
      for (const record of request.matched_records) {
        const link = element('a', '', record.title + ' ↗');
        link.href = `#record-${record.id}`;
        evidence.append(link);
      }
    } else evidence.textContent = request.alex_claim ? 'Visitor identifies as Alex. Your approval is still required.' : 'No matching record supplied. Review the conversation before deciding.';
    card.append(evidence);
    if (request.status === 'pending') {
      const row = element('div', 'approval-buttons');
      for (const [decision, label] of [['deny', 'Deny'], ['allow', 'Allow']]) {
        const button = element('button', `approval-button ${decision}`, label);
        button.type = 'button';
        button.disabled = !connected || submitted === request.id || Date.now() >= Date.parse(request.expires_at);
        button.addEventListener('click', () => {
          if (!connected || socket.readyState !== WebSocket.OPEN) return;
          submitted = request.id;
          $('employee-error').hidden = true;
          socket.send(JSON.stringify({type: 'decision', id: request.id, decision}));
          render();
        });
        row.append(button);
      }
      const countdown = element('span', 'approval-countdown');
      countdown.dataset.expires = request.expires_at;
      row.append(countdown);
      card.append(row);
      if (!connected) card.append(element('p', 'approval-offline', 'Waiting to reconnect. No approval has been sent.'));
      else if (submitted === request.id) card.append(element('p', 'approval-offline', 'Sending your decision…'));
    } else card.append(element('p', 'approval-result', {
      allowed: 'Approval sent to Jamie. Check the call review for the door and elevator actions.',
      denied: 'Jamie was told you denied entry. The door stays closed.',
      expired: 'Nobody confirmed within 40 seconds. The door stays closed.',
      cancelled: 'This call has ended. The request can no longer open the door.'
    }[request.status]));
    return card;
  }));
  tick();
}

function tick() {
  document.querySelectorAll('.approval-countdown').forEach(node => {
    const remaining = Math.max(0, Math.ceil((Date.parse(node.dataset.expires) - Date.now()) / 1000));
    node.textContent = remaining ? `${remaining}s to respond` : 'Request expired';
    if (!remaining) node.closest('.approval-card').querySelectorAll('button').forEach(button => { button.disabled = true; });
  });
}

async function connect() {
  if (stopped) return;
  try {
    const response = await fetch('/api/config', {cache: 'no-store'});
    if (!response.ok) throw new Error('Unavailable');
    const {token} = await response.json();
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/employee?token=${encodeURIComponent(token)}`);
    socket.onmessage = event => {
      const data = JSON.parse(event.data);
      if (data.type === 'approvals') {
        connected = true;
        requests = data.requests;
        submitted = null;
        const pending = new Set(requests.filter(request => request.status === 'pending').map(request => request.id));
        if ([...pending].some(id => !previousPending.has(id))) {
          $('employee-alert').textContent = 'Someone is at the door. Please allow or deny entry below.';
        } else if (!pending.size) $('employee-alert').textContent = '';
        previousPending = pending;
        render();
      } else if (data.type === 'error') {
        submitted = null;
        $('employee-error').textContent = data.message;
        $('employee-error').hidden = false;
        render();
      }
    };
    socket.onclose = () => {
      connected = false;
      submitted = null;
      render();
      if (!stopped) setTimeout(connect, 1500);
    };
    socket.onerror = () => socket.close();
  } catch {
    connected = false;
    render();
    if (!stopped) setTimeout(connect, 1500);
  }
}
setInterval(tick, 1000);
window.addEventListener('pagehide', () => { stopped = true; socket?.close(); });
connect();
