/* The prototype's visual shell, backed exclusively by Action Gate HTTP contracts.
 * No mock evaluator, generated traffic, external scripts or persisted credentials.
 */
'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const json = v => esc(JSON.stringify(v, null, 2));
  const main = $('#main');
  const S = {identity: null, me: null, epoch: 0, route: 0, release: null, services: [],
    paused: false, requestVersion: 0, page: null, summary: null, filters: {decision: '', outcome: ''}};
  const notice = (message, error = false) => {
    $('#notice').textContent = message || '';
    $('#notice').hidden = !message;
    $('#notice').className = error ? 'error' : '';
  };
  async function api(method, path, body) {
    const epoch = S.epoch;
    const headers = {Accept: 'application/json'};
    if (S.identity) {
      headers['X-Action-Gate-Principal'] = S.identity.principal;
      headers['X-Action-Gate-Token'] = S.identity.token;
    }
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let response;
    try {
      response = await fetch(path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body),
        cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(45000)});
    } catch (cause) {
      throw new Error('The backend did not respond. Check the local server and reconnect. A timed-out action may have completed; inspect Requests before retrying.');
    }
    const data = await response.json();
    if (epoch !== S.epoch) throw new Error('Connection changed; discarded the previous response.');
    if (!response.ok) {
      const error = new Error(`HTTP ${response.status} · ${data.error || 'request_failed'}${data.message || data.detail ? ' · ' + (data.message || data.detail) : ''}`);
      error.data = data;
      error.status = response.status;
      throw error;
    }
    return data;
  }
  async function refreshRelease() {
    const r = await api('GET', '/v1/config/release');
    S.release = r;
    $('#liveChip').textContent = 'Generation ' + (r.activationGeneration ?? '—');
    $('#liveChip').title = 'Active release ' + (r.release || '');
    return r;
  }
  function heading(title, description, extra = '') {
    return `<div class="page-head"><div><p class="eyebrow">Local demonstration · live backend</p><h1 class="page-title">${esc(title)}</h1><p>${esc(description)}</p></div>${extra}</div>`;
  }
  function badge(decision) {
    const cls = ['allow', 'redact', 'block'].includes(decision) ? decision : 'monitor';
    return `<span class="st ${cls}">${esc(decision || 'unknown')}</span>`;
  }
  function time(value) {
    return value ? new Date(value).toLocaleString('en-GB', {timeZone: 'Europe/Warsaw'}) : '—';
  }
  function protectedPage(title) {
    main.innerHTML = heading(title, 'Connect with a configured local identity to load backend data.') +
      '<div class="panel"><h2>Connect to Action Gate</h2><p>Use the Principal and Token fields above. The server verifies the role and access scope.</p><p>No request data or policy state is loaded before authentication. Credentials are forgotten on reload.</p></div>';
  }
  function resetSession() {
    S.epoch++; S.identity = null; S.me = null; S.page = null; S.summary = null;
    S.paused = false; S.requestVersion++;
    window.ControlPolicy.reset();
    $('#disconnect').hidden = true;
    $('#connectionStatus').textContent = 'Not connected · credentials stay in memory';
  }
  $('#connectionForm').addEventListener('submit', async event => {
    event.preventDefault();
    const principal = $('#principal').value.trim(), token = $('#token').value;
    resetSession(); notice('');
    const epoch = S.epoch;
    S.identity = {principal, token};
    $('#token').value = '';
    $('#connect').disabled = true;
    main.innerHTML = '<p>Verifying identity…</p>';
    try {
      S.me = await api('GET', '/v1/me');
      $('#connectionStatus').textContent = `${S.me.principalId} · ${S.me.role} · credentials in memory`;
      $('#disconnect').hidden = false;
      await refreshRelease();
      await route();
    } catch (error) {
      if (epoch === S.epoch) { resetSession(); protectedPage('Connection unavailable'); notice(error.message, true); }
    } finally { if (epoch === S.epoch || !S.identity) $('#connect').disabled = false; }
  });
  $('#disconnect').onclick = () => { resetSession(); $('#connect').disabled = false; $('#token').value = ''; notice('Disconnected. Credentials and loaded data cleared.'); route(); };
  $('#themeBtn').onclick = () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; };
  $('#liveChip').onclick = () => { location.hash = '#/builder'; };

  function listQuery(window, cursor) {
    const q = new URLSearchParams({...window, limit: '30'});
    for (const [key, value] of Object.entries(S.filters)) if (value) q.set(key, value);
    if (cursor) q.set('cursor', cursor);
    return q.toString();
  }
  async function loadRequests(append = false) {
    if (!S.me || !$('#requestRows')) return;
    const version = ++S.requestVersion, epoch = S.epoch, routeVersion = S.route;
    const window = append ? S.page.window : {since: new Date(Date.now() - 86400000).toISOString(), until: new Date().toISOString()};
    const cursor = append ? S.page.nextCursor : null;
    if (append && !cursor) return;
    $('#requestState').textContent = 'Loading backend records…';
    try {
      const [page, summary] = await Promise.all([
        api('GET', '/v1/invocations?' + listQuery(window, cursor)),
        append ? Promise.resolve(S.summary) : api('GET', '/v1/summary?' + new URLSearchParams(window)),
      ]);
      if (version !== S.requestVersion || routeVersion !== S.route || epoch !== S.epoch || !$('#requestRows')) return;
      if (append) page.invocations = S.page.invocations.concat(page.invocations);
      S.page = page; S.summary = summary;
      drawRequests();
    } catch (error) {
      if (version !== S.requestVersion || routeVersion !== S.route || epoch !== S.epoch) return;
      $('#requestState').textContent = 'Refresh failed. Previously loaded rows may be stale.';
      notice(error.message, true);
    }
  }
  function drawRequests() {
    const p = S.page, r = S.summary, i = r.invocations;
    const metrics = [['Total', i.total], ['Input allowed', i.allowed], ['Input redacted', i.redacted], ['Input blocked', i.blocked],
      ['Output withheld', r.disclosure.withheld], ['Latency p95', r.latency.total.p95 == null ? '—' : r.latency.total.p95 + ' ms']];
    $('#requestSummary').innerHTML = metrics.map(([label, value]) => `<div class="sum static"><span class="v">${esc(value)}</span><span class="l">${esc(label)}</span></div>`).join('');
    $('#requestState').textContent = `${p.invocations.length} loaded · scope: ${p.scope} · ${time(p.window.since)} – ${time(p.window.until)} Warsaw · summary covers all decisions in this window`;
    $('#runtimeState').textContent = `Semantic mode: ${r.semanticMode} ${r.semanticMode === 'baseline' ? '(heuristic, not a trained model)' : ''} · storage: ${r.storage.repository} · shared UTC budget: ${r.budget.usedTokens} used / ${r.budget.limitTokens} tokens (${r.budget.period})`;
    $('#requestRows').innerHTML = p.invocations.length ? p.invocations.map(row => `<tr>
      <td><a href="#/requests/${encodeURIComponent(row.invocationId)}">${esc(time(row.createdAt))}</a></td>
      <td>${esc(row.principalId)}</td><td>${esc(row.service)}<br><span class="muted">${esc(row.action)}</span></td>
      <td>${badge(row.decision)}</td><td>${esc(row.actionOutcome)}</td><td>${esc(row.disclosure)}</td>
      <td>${esc(row.latencyMs)} ms${row.dryRun ? '<br><span class="tag">Dry run</span>' : ''}</td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">No invocations in this window. Run a synthetic request to create a real record.</td></tr>';
    $('#loadMore').disabled = !p.nextCursor;
  }
  async function renderRequests() {
    main.innerHTML = heading('Requests', 'Persisted invocations and sanitized audit. Polls every 5 seconds while this page is visible.',
      '<a class="btn primary" href="#/invoke">Run synthetic request</a>') +
      '<div id="requestSummary" class="summary"></div><div id="runtimeState" class="note-box"></div>' +
      `<div class="filters"><label>Input decision <select id="decisionFilter"><option value="">All</option>${['allow','redact','block'].map(v => `<option ${S.filters.decision === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
      <label>Action outcome <select id="outcomeFilter"><option value="">All</option>${['succeeded','not_started','failed','unknown'].map(v => `<option ${S.filters.outcome === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
      <span class="spacer"></span><button class="btn small" id="refreshRequests">Refresh</button><button class="btn small" id="pauseRequests">${S.paused ? 'Resume polling' : 'Pause polling'}</button></div>
      <p id="requestState" class="status-line">Loading…</p><div class="table-wrap"><table><thead><tr><th>Time (Warsaw)</th><th>Principal</th><th>Target</th><th>Input decision</th><th>Action outcome</th><th>Disclosure</th><th>Latency</th></tr></thead><tbody id="requestRows"></tbody></table></div>
      <div class="toolbar"><button class="btn" id="loadMore" disabled>Load more</button><span class="muted">Loading older records pauses polling to keep the page window stable.</span></div>`;
    $('#decisionFilter').onchange = e => { S.filters.decision = e.target.value; loadRequests(); };
    $('#outcomeFilter').onchange = e => { S.filters.outcome = e.target.value; loadRequests(); };
    $('#refreshRequests').onclick = () => loadRequests();
    $('#pauseRequests').onclick = () => { S.paused = !S.paused; $('#pauseRequests').textContent = S.paused ? 'Resume polling' : 'Pause polling'; if (!S.paused) loadRequests(); };
    $('#loadMore').onclick = () => { S.paused = true; $('#pauseRequests').textContent = 'Resume polling'; loadRequests(true); };
    await loadRequests();
  }
  function resultHtml(r) {
    return `<div class="result-grid"><div><span class="muted">Input policy decision</span><strong>${esc(r.policy?.decision)}</strong></div>
      <div><span class="muted">Action outcome</span><strong>${esc(r.action?.outcome)}</strong></div>
      <div><span class="muted">Output disclosure</span><strong>${esc(r.output?.disclosure)}</strong></div></div>
      ${r.output?.disclosure === 'withheld' ? '<p class="unavailable">The action ran. Its answer was withheld; this does not undo the action.</p>' : ''}
      <p class="status-line">${esc((r.policy?.reasons || []).join(' · ') || 'No refusal reason')} · ${esc(r.timing?.totalMs)} ms · ${r.dryRun ? 'dry run' : 'execution'} · ${r.replayed ? 'idempotent replay' : 'new invocation'}</p>
      <h2>Disclosed output</h2><pre id="disclosedOutput">${esc(r.output?.text ?? 'No output disclosed.')}</pre>
      <details><summary>Full sanitized response</summary><pre>${json(r)}</pre></details>`;
  }
  async function renderDetail(id, token) {
    const trace = await api('GET', '/v1/invocations/' + encodeURIComponent(id));
    if (token !== S.route) return;
    main.innerHTML = '<div class="crumbs"><a href="#/requests">Requests</a> / Invocation</div>' +
      heading('Request detail', id) + resultHtml(trace.response) +
      '<section class="sec"><h2>Inspection chain · persisted events</h2>' +
      `<ol class="chain">${trace.events.map(e => `<li><span class="node">${esc(e.seq)}</span><div><strong>${esc(e.kind)}</strong><div class="muted">${esc((e.reasons || []).join(', '))}</div><details><summary>Details</summary><pre>${json(e.detail)}</pre></details></div><span>${esc(e.decision || '')}</span></li>`).join('')}</ol></section>` +
      '<p class="unavailable">Original prompts and withheld output are not stored. Replay, raw-text search, false-positive review and saving historical raw input as a test case are unavailable in this API.</p>';
  }
  async function renderServices(token) {
    const data = await api('GET', '/v1/services');
    if (token !== S.route) return;
    main.innerHTML = heading('Services', 'The actual service registry and role grants in the active release.') +
      data.services.map(s => `<section class="panel"><h2>${esc(s.id)}</h2><p>${esc(s.description)}</p><div class="table-wrap"><table><thead><tr><th>Action</th><th>Effect</th><th>Granted roles</th><th>Description</th></tr></thead><tbody>${s.actions.map(a => `<tr><td>${esc(a.id)}</td><td>${esc(a.effect)}</td><td>${esc(a.grants.join(', ') || 'No roles')}</td><td class="msg">${esc(a.description)}</td></tr>`).join('')}</tbody></table></div></section>`).join('') +
      '<p class="unavailable">Only the synthetic Document Desk adapter is installed. Importing or verifying arbitrary MCP / OpenAPI services is not supported. Role grants can be edited through the policy lifecycle.</p><a href="#/builder" class="btn">Edit policy</a>';
  }
  async function renderInvocation(token) {
    const data = await api('GET', '/v1/services');
    if (token !== S.route) return;
    S.services = data.services;
    main.innerHTML = heading('Run synthetic request', 'Calls the protected backend path. The Document Desk adapter performs no external service calls.') +
      `<form id="invokeForm" class="panel"><div class="form-grid">
      <div class="field"><label for="invokeService">Service</label><select id="invokeService">${S.services.map(s => `<option value="${esc(s.id)}">${esc(s.id)}</option>`).join('')}</select></div>
      <div class="field"><label for="invokeAction">Action</label><select id="invokeAction"></select></div>
      <div class="field"><label for="invokeDocument">Document ID</label><input id="invokeDocument" value="release-notes" required></div>
      <div class="field"><label for="invokeModel">Model</label><input id="invokeModel" value="demo-local" required></div>
      <div class="field wide"><label for="invokeText">Comment / input text (synthetic data only)</label><textarea id="invokeText" placeholder="Used by documents.comment; optional for reads"></textarea></div></div>
      <div class="toolbar"><label><input id="invokeDryRun" type="checkbox"> Dry run (no target dispatch; semantic evaluation still uses budget)</label></div>
      <div class="toolbar"><button class="btn primary" id="runInvocation">Run request</button><button type="button" id="poisonedPreset" class="btn">Poisoned document</button><button type="button" id="piiPreset" class="btn">PII document</button></div>
      <p class="hint">Preset documents: release-notes, handbook (synthetic PII), field-report (injection), security-notes (benign quotation). The active detector profile determines semantic behaviour.</p></form><section id="invocationResult" aria-live="polite"></section>`;
    const actions = () => { $('#invokeAction').innerHTML = S.services.find(s => s.id === $('#invokeService').value).actions.map(a => `<option value="${esc(a.id)}">${esc(a.id)} (${esc(a.effect)})</option>`).join(''); };
    actions(); $('#invokeService').onchange = actions;
    $('#poisonedPreset').onclick = () => { $('#invokeDocument').value = 'field-report'; $('#invokeAction').value = 'documents.read'; };
    $('#piiPreset').onclick = () => { $('#invokeDocument').value = 'handbook'; $('#invokeAction').value = 'documents.read'; };
    $('#invokeForm').onsubmit = async event => {
      event.preventDefault(); notice('');
      const button = $('#runInvocation'), result = $('#invocationResult'), epoch = S.epoch;
      const body = {idempotencyKey: 'console-' + crypto.randomUUID(), service: $('#invokeService').value,
        action: $('#invokeAction').value, model: $('#invokeModel').value,
        input: {documentId: $('#invokeDocument').value, text: $('#invokeText').value}, dryRun: $('#invokeDryRun').checked};
      button.disabled = true;
      result.textContent = 'Running protected invocation…';
      try {
        let response;
        try { response = await api('POST', '/v1/invocations', body); }
        catch (error) { if (!error.data?.invocationId) throw error; response = error.data; }
        if (epoch !== S.epoch || !result.isConnected) return;
        result.innerHTML = resultHtml(response) + `<a class="btn" href="#/requests/${encodeURIComponent(response.invocationId)}">Open persisted trace</a>`;
      } catch (error) {
        if (epoch === S.epoch && result.isConnected) { result.textContent = 'Request failed. Idempotency key: ' + body.idempotencyKey; notice(error.message, true); }
      } finally { button.disabled = false; }
    };
  }
  async function route() {
    const token = ++S.route;
    const parts = location.hash.replace(/^#\/?/, '').split('/'), name = parts[0] || 'requests';
    document.querySelectorAll('[data-nav]').forEach(a => { if (a.dataset.nav === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    if (!S.me && name !== 'services' && name !== 'training') { protectedPage(name === 'builder' ? 'Policy builder' : 'Requests'); return; }
    main.innerHTML = '<p>Loading backend data…</p>';
    const epoch = S.epoch;
    const context = {main, api, esc, notice, refreshRelease,
      isCurrent: () => token === S.route && epoch === S.epoch,
      me: S.me, release: S.release};
    try {
      if (name === 'requests' && parts[1]) await renderDetail(decodeURIComponent(parts[1]), token);
      else if (name === 'requests') await renderRequests();
      else if (name === 'services') await renderServices(token);
      else if (name === 'invoke') await renderInvocation(token);
      else if (name === 'builder' || name === 'history') {
        if (S.me.role !== 'operator') main.innerHTML = heading('Operator access required', 'Your identity can invoke services and view its own records. Policy configuration requires the operator role.');
        else if (name === 'builder') await window.ControlPolicy.renderBuilder(context);
        else await window.ControlPolicy.renderHistory(context);
      } else if (name === 'training') main.innerHTML = heading('Training data', 'This capability is not available in the current backend.') +
        '<div class="unavailable">The backend stores semantic observations for evaluation and cache reuse. It has no training-example review or export API. No examples, labels or review counts are fabricated here.</div>';
      else main.innerHTML = heading('Page not found', 'Choose a page from the navigation.');
    } catch (error) { if (token === S.route && epoch === S.epoch) { main.innerHTML = heading('Unable to load this page', 'Check the error below, then reconnect or choose another page.'); notice(error.message, true); } }
  }
  window.addEventListener('hashchange', () => { notice(''); route(); });
  setInterval(() => { if (S.me && !S.paused && !document.hidden && $('#requestRows')) loadRequests(); }, 5000);
  const initialEpoch = S.epoch;
  refreshRelease().catch(error => { if (initialEpoch === S.epoch) notice(error.message, true); });
  route();
})();
