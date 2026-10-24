const $ = (id) => document.getElementById(id);
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
let recordsKey, actionsKey, transcriptKey;
const recordNodes = new Map();
const toolNames = { check_calendar_emails: 'Check emails & calendar', open_door: 'Open door', send_elevator: 'Send elevator', elevator_auto_return: 'Automatic elevator trip', employee_approval: 'Request employee approval', employee_decision: 'Employee decision' };

function showRecords(records) {
  const key = JSON.stringify(records);
  if (key === recordsKey) return;
  recordsKey = key;
  recordNodes.clear();
  for (const [source, container, count] of [['email', 'emails', 'email-count'], ['calendar', 'calendar', 'calendar-count']]) {
    const list = records.filter(record => record.source === source);
    $(count).textContent = `${list.length} ${source === 'email' ? 'messages' : 'events'}`;
    $(container).replaceChildren(...list.map(record => {
      const card = make('article', `source-card source-${source}`);
      card.id = `record-${record.id}`;
      const meta = make('div', 'record-meta');
      const match = make('span', 'record-match', 'MATCHED IN THIS CALL');
      match.hidden = true;
      meta.append(make('span', '', source === 'email' ? 'INBOX / EXPECTED DELIVERY' : 'CALENDAR / EXPECTED VISITOR'), match);
      const footer = make('div', 'record-footer');
      footer.append(make('span', '', `${record.scheduled_time} · time ignored`), make('span', '', `Floor ${record.destination_floor}`));
      const rules = make('details', 'match-rules');
      rules.append(make('summary', '', 'Matching rules'), make('p', '', 'Both the visitor’s words and Jamie’s search must include at least one term from each group:'));
      const terms = make('ol');
      terms.append(...record.match_groups.map(group => make('li', '', group.join(' / '))));
      rules.append(terms);
      card.append(meta, make('h3', '', record.title), make('p', 'record-from', record.from), make('p', 'record-body', record.body), footer, rules);
      recordNodes.set(record.id, { card, match });
      return card;
    }));
  }
}

function sourceLinks(records) {
  const links = make('div', 'source-links');
  for (const record of records) {
    const link = make('a', '', `${record.source === 'email' ? 'Email' : 'Calendar'} · ${record.title} ↗`);
    link.href = `#record-${record.id}`;
    links.append(link);
  }
  return links;
}

function showActions(actions) {
  const key = JSON.stringify(actions);
  if (key === actionsKey) return;
  actionsKey = key;
  $('action-count').textContent = `${actions.length} ACTION${actions.length === 1 ? '' : 'S'}`;
  const opened = new Set([...document.querySelectorAll('.tool-details[open]')].map(node => node.dataset.key));
  if (!actions.length) {
    const empty = make('li', 'review-empty');
    const link = make('a', '', 'Open intercom in a new tab ↗');
    link.href = '/'; link.target = '_blank'; link.rel = 'noopener';
    empty.append(make('span', '', '↗'), make('h3', '', 'No decisions yet.'), make('p', '', 'Call Jamie from the Intercom page. Searches, matched records and door requests will appear here.'), link);
    $('audit-actions').replaceChildren(empty);
  } else {
    $('audit-actions').replaceChildren(...actions.map((action, index) => {
      const evidence = action.evidence || {};
      const matches = evidence.matched_records || [];
      const noMatch = action.tool === 'check_calendar_emails' && action.ok && !matches.length;
      const item = make('li', `audit-item${!action.ok ? ' failed' : noMatch ? ' neutral' : ''}`);
      const meta = make('div', 'audit-topline');
      const time = make('time', '', action.at ? clock.format(new Date(action.at)) : '');
      if (action.at) time.dateTime = action.at;
      meta.append(make('span', '', `${String(index + 1).padStart(2, '0')} / ${toolNames[action.tool] || action.tool}`), time);
      let title = action.ok ? 'Completed' : 'Request blocked';
      if (action.tool === 'check_calendar_emails' && action.ok) title = matches.length ? `${matches.length} matching record${matches.length === 1 ? '' : 's'}` : 'No matching record';
      if (action.tool === 'employee_approval') title = 'Waiting for an employee';
      if (action.tool === 'employee_decision') title = {allowed: 'Employee allowed entry', denied: 'Employee denied entry', expired: 'No answer — request expired', cancelled: 'Call ended — request cancelled'}[evidence.approval?.status] || action.text;
      if (action.tool === 'open_door') title = action.ok ? 'Entry granted' : 'Unlock blocked';
      if (action.tool === 'send_elevator' && action.ok) title = `Elevator called to ${evidence.output?.label ?? ''}`;
      if (action.tool === 'elevator_auto_return') title = 'Elevator returned to 5';
      item.append(meta, make('h4', '', title), make('p', 'audit-summary', action.text));
      if (action.tool === 'check_calendar_emails' && typeof evidence.arguments?.query === 'string') {
        item.append(make('p', 'audit-label', 'Jamie searched for'), make('blockquote', 'audit-quote', evidence.arguments.query));
      }
      if (['check_calendar_emails', 'open_door'].includes(action.tool) && evidence.heard?.length) {
        item.append(make('p', 'audit-label', 'Visitor words checked'), make('blockquote', 'audit-quote', evidence.heard.join(' ')));
      }
      if (evidence.basis === 'employee_approval') item.append(make('p', 'audit-summary', 'An employee pressed Allow for this call.'));
      if (matches.length) item.append(sourceLinks(matches));
      if (noMatch) item.append(make('p', 'audit-summary', 'No entry approval from this lookup. Jamie can ask for more details.'));
      if (action.evidence) {
        const details = make('details', 'tool-details');
        details.dataset.key = `${action.at}-${index}`;
        details.open = opened.has(details.dataset.key);
        details.append(make('summary', '', 'Tool request & response'), make('pre', '', JSON.stringify({ tool: action.tool, arguments: evidence.arguments, is_error: !action.ok, result: evidence.output, approval: evidence.approval }, null, 2)));
        item.append(details);
      }
      return item;
    }));
  }
  const matchedIds = new Set(actions.flatMap(action => (action.evidence?.matched_records || []).map(record => record.id)));
  for (const [id, { card, match }] of recordNodes) {
    card.classList.toggle('matched', matchedIds.has(id));
    match.hidden = !matchedIds.has(id);
  }
}

function showTranscript(messages) {
  const key = JSON.stringify(messages);
  if (key === transcriptKey) return;
  transcriptKey = key;
  $('review-transcript').replaceChildren(...(messages.length ? messages.map(message => {
    const item = make('div', `review-message${message.speaker === 'You' ? ' visitor' : ''}`);
    item.append(make('h4', '', message.speaker === 'You' ? 'Visitor' : message.speaker), make('p', '', message.text));
    return item;
  }) : [make('p', 'transcript-placeholder', 'The visitor’s words and Jamie’s replies will appear here.')]));
}

async function refresh() {
  try {
    const response = await fetch('/api/admin', { cache: 'no-store' });
    if (!response.ok) throw new Error('Backend unavailable');
    const data = await response.json();
    showRecords(data.records);
    showActions(data.actions);
    showTranscript(data.transcript);
    const badge = $('review-status');
    const granted = data.actions.some(action => action.tool === 'open_door' && action.ok);
    const blocked = data.actions.some(action => action.tool === 'open_door' && !action.ok);
    badge.className = `review-status${granted ? ' granted' : blocked ? ' blocked' : ''}`;
    badge.textContent = granted ? 'Entry granted' : blocked ? 'Unlock blocked' : data.actions.length ? 'No unlock granted' : data.transcript.length ? 'Conversation started' : 'Waiting for a call';
    $('call-phase').textContent = data.call === 'idle' ? (data.transcript.length ? 'LAST CALL' : 'NOT STARTED') : data.call.toUpperCase();
    $('review-state').textContent = `Door ${data.door} · Elevator on ${data.elevator.label}${data.elevator.return_in_seconds !== null ? ` · To 5 in ${data.elevator.return_in_seconds}s` : ''}`;
    $('connection-text').textContent = 'Live updates';
    $('connection-dot').classList.add('online');
    $('load-error').hidden = true;
  } catch {
    $('connection-text').textContent = 'Reconnecting';
    $('connection-dot').classList.remove('online');
    $('load-error').hidden = false;
  } finally {
    setTimeout(refresh, 1000);
  }
}
refresh();
