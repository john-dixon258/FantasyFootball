const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const PAGE_SIZE = 15;
const STORAGE_KEY = 'touchline:shortlist:v1';
const number = new Intl.NumberFormat('en-GB');
const date = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short' });
const urlState = new URLSearchParams(location.search);
const state = {
  players: [],
  knownPlayers: new Map(),
  saved: new Set(),
  selected: [],
  mode: urlState.get('view') === 'saved' ? 'saved' : 'all',
  position: ['GK', 'DEF', 'MID', 'FWD'].includes(urlState.get('position')?.toUpperCase())
    ? urlState.get('position').toUpperCase() : '',
  page: 1,
  ready: false,
  requestId: 0,
  controller: null,
  comparisonController: null,
  filters: {},
};

function escape(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function icon(name, extra = '') {
  return `<svg class="icon ${extra}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
}

function format(value, decimals = 0) {
  return value == null ? '—' : Number(value).toLocaleString('en-GB', {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
}

function price(value) { return value == null ? '—' : `£${format(value, 1)}m`; }
function normalize(value) { return String(value ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }

function clubAvatar(player) {
  const palettes = [
    ['#e7ebe1', '#5f7650'], ['#ede4dd', '#93674a'], ['#e1e9ed', '#5d7c8d'],
    ['#eee5e7', '#976977'], ['#e7e4ed', '#7b6a94'], ['#eeeacb', '#847b48'],
  ];
  const [background, ink] = palettes[(player.team_id || 0) % palettes.length];
  const initials = (player.team_name || `Club ${player.team_id}`).split(/\s+/).map((part) => part[0]).slice(0, 3).join('');
  return `<span class="club-avatar" aria-hidden="true" style="--club-bg:${background};--club-ink:${ink}">${escape(initials)}</span>`;
}

let toastTimer;
function toast(message) {
  const element = $('#toast');
  clearTimeout(toastTimer);
  const openDialog = $('dialog[open]');
  (openDialog || document.body).append(element);
  element.classList.toggle('in-dialog', Boolean(openDialog));
  element.textContent = message;
  element.hidden = false;
  toastTimer = setTimeout(() => { element.hidden = true; }, 4200);
}

async function api(path, signal) {
  const response = await fetch(path, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) {
    let message = `The request returned ${response.status}. Please try again.`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (Array.isArray(payload.detail)) message = payload.detail.map((item) => item.msg).join(' ');
    } catch { /* Keep the HTTP error when the server returns a non-JSON error page. */ }
    throw new Error(message);
  }
  return response.json();
}

function readFilters() {
  const maximum = Number($('#price-filter').value);
  return {
    position: state.position,
    team: $('#team-filter').value,
    max_price: maximum < Number($('#price-filter').max) ? String(maximum) : '',
    min_minutes: $('#minutes-filter').value,
    sort_by: $('#sort-select').value,
  };
}

function syncUrl() {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(state.filters)) {
    if (value && !(key === 'min_minutes' && value === '0') && !(key === 'sort_by' && value === 'points')) params.set(key, value);
  }
  const search = $('#player-search').value.trim();
  if (search) params.set('q', search);
  if (state.mode === 'saved') params.set('view', 'saved');
  const query = params.toString();
  history.replaceState(null, '', `${location.pathname}${query ? `?${query}` : ''}`);
}

function updatePrice() {
  const range = $('#price-filter');
  const value = Number(range.value);
  $('#price-output').textContent = value === Number(range.max) ? 'Any price' : price(value);
  range.style.setProperty('--range-fill', `${value / Number(range.max) * 100}%`);
}

function setBusy(busy) {
  $('#table-panel').setAttribute('aria-busy', String(busy));
  $('#filter-form button[type="submit"]').disabled = busy;
  $('#refresh-data').disabled = busy;
  $('#export-csv').disabled = busy || !state.ready;
}

function showTableState(title, message, { loading = false, retry = false, saved = false } = {}) {
  $('#player-rows').replaceChildren();
  $('#table-footer').hidden = true;
  $('#table-state').hidden = false;
  $('#table-state').innerHTML = `${loading ? '<div class="loading-spinner"></div>' : icon(saved ? 'star' : 'search')}
    <h3>${escape(title)}</h3><p>${escape(message)}</p>
    ${retry ? '<button class="primary-button" id="retry-data" type="button">Try again</button>' : ''}`;
  $('#retry-data')?.addEventListener('click', initialize);
}

function visiblePlayers() {
  const search = normalize($('#player-search').value.trim());
  return state.players.filter((player) => (
    (state.mode !== 'saved' || state.saved.has(player.player_id))
    && (!search || normalize(`${player.name} ${player.team_name || ''}`).includes(search))
  ));
}

function renderActiveFilters() {
  const chips = [];
  if (state.filters.position) chips.push(state.filters.position);
  if (state.filters.team) chips.push(state.filters.team);
  if (state.filters.max_price) chips.push(`Up to ${price(state.filters.max_price)}`);
  if (Number(state.filters.min_minutes) > 0) chips.push(`${number.format(state.filters.min_minutes)}+ minutes`);
  $('#active-filters').innerHTML = chips.map((chip) => `<span class="filter-chip">${escape(chip)}</span>`).join('');
  $('#active-filters').hidden = chips.length === 0;
}

function renderTable() {
  const focused = document.activeElement?.closest('[data-player][data-action]');
  const focusTarget = focused ? { action: focused.dataset.action, player: focused.dataset.player } : null;
  const players = visiblePlayers();
  $('#result-count').textContent = number.format(players.length);
  $('#results-title').textContent = state.mode === 'saved' ? 'Your shortlist' : 'All players';
  $('#explorer-title').innerHTML = `${state.mode === 'saved' ? 'Your scouting board' : 'The player room'}<span class="heading-dot">.</span>`;
  $('#breadcrumb-current').textContent = state.mode === 'saved' ? 'MY SHORTLIST' : 'PLAYER EXPLORER';
  $('#export-csv').disabled = players.length === 0 || !state.ready;
  $$('.column-sort').forEach((button) => {
    const active = button.dataset.sort === state.filters.sort_by;
    const column = button.closest('th');
    if (active) column.setAttribute('aria-sort', button.dataset.sort === 'price' ? 'ascending' : 'descending');
    else column.removeAttribute('aria-sort');
    button.querySelector('span').textContent = active ? (button.dataset.sort === 'price' ? '↑' : '↓') : '↗';
  });
  if (!players.length) {
    showTableState(
      state.mode === 'saved' && !state.saved.size ? 'Your next great pick belongs here.' : 'No players in this view.',
      state.mode === 'saved' && !state.saved.size
        ? 'Star players in the explorer to build your own scouting board. They will be waiting here when you come back.'
        : 'Try a different club, increase your budget, or clear the search and filters.',
      { saved: state.mode === 'saved' },
    );
    return;
  }
  const pages = Math.ceil(players.length / PAGE_SIZE);
  state.page = Math.max(1, Math.min(state.page, pages));
  const first = (state.page - 1) * PAGE_SIZE;
  const rows = players.slice(first, first + PAGE_SIZE);
  const maxPoints = Math.max(1, ...players.map((player) => player.total_points));
  $('#table-state').hidden = true;
  $('#table-footer').hidden = false;
  $('#player-rows').innerHTML = rows.map((player) => {
    const saved = state.saved.has(player.player_id);
    const selected = state.selected.includes(player.player_id);
    const noId = player.player_id == null;
    return `<tr class="${selected ? 'selected' : ''}">
      <td class="save-cell"><button class="star-button ${saved ? 'saved' : ''}" data-action="save" data-player="${player.player_id}" type="button" aria-label="${saved ? 'Remove' : 'Save'} ${escape(player.name)} ${saved ? 'from' : 'to'} shortlist" aria-pressed="${saved}" ${noId ? 'disabled title="This record has no player ID"' : ''}>${icon('star')}</button></td>
      <td class="player-cell"><button class="player-link" data-action="detail" data-player="${player.player_id}" data-name="${escape(player.name)}" type="button">${clubAvatar(player)}<span><span class="player-name">${escape(player.name)}</span><span class="player-club"><span class="mobile-position">${escape(player.position)} · </span>${escape(player.team_name || `Club ${player.team_id}`)}</span></span></button></td>
      <td><span class="position-badge ${player.position.toLowerCase()}">${escape(player.position)}</span></td>
      <td class="price-value">${price(player.price)}</td>
      <td><span class="points-value">${format(player.total_points)}</span><div class="points-track" aria-hidden="true"><span style="width:${Math.max(0, player.total_points) / maxPoints * 100}%"></span></div></td>
      <td>${format(player.points_per_million, 2)}</td>
      <td>${format(player.minutes)}</td>
      <td><span class="next-opponent">${player.next_opponent ? '<span class="opponent-dot" aria-hidden="true"></span>' : ''}${escape(player.next_opponent || '—')}</span></td>
      <td class="compare-cell"><input type="checkbox" class="compare-check" data-action="compare" data-player="${player.player_id}" aria-label="Compare ${escape(player.name)}" ${selected ? 'checked' : ''} ${noId ? 'disabled title="This record has no player ID"' : ''}></td>
    </tr>`;
  }).join('');
  $('#pagination-summary').textContent = `Showing ${number.format(first + 1)}–${number.format(first + rows.length)} of ${number.format(players.length)} players`;
  $('#page-label').textContent = `${state.page} / ${pages}`;
  $('#previous-page').disabled = state.page === 1;
  $('#next-page').disabled = state.page === pages;
  if (focusTarget) $(`[data-action="${focusTarget.action}"][data-player="${focusTarget.player}"]`)?.focus({ preventScroll: true });
}

function renderNavigation() {
  $('#saved-nav-count').textContent = state.saved.size;
  $('#compare-nav-count').textContent = state.selected.length;
  $('#clear-saved').hidden = state.mode !== 'saved' || state.saved.size === 0;
  for (const [id, active] of [['nav-explorer', state.mode === 'all'], ['nav-saved', state.mode === 'saved']]) {
    const button = $(`#${id}`);
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  $('#compare-tray').hidden = state.selected.length === 0;
  document.body.classList.toggle('has-selection', state.selected.length > 0);
  $('#open-compare').disabled = state.selected.length !== 2;
  $('#compare-slots').innerHTML = [0, 1].map((index) => {
    const player = state.knownPlayers.get(state.selected[index]);
    if (!player) return '<div class="compare-slot empty">Select another player</div>';
    return `<div class="compare-slot">${clubAvatar(player)}<span class="slot-name">${escape(player.name)}</span><button type="button" class="icon-button" data-remove-player="${player.player_id}" aria-label="Remove ${escape(player.name)} from comparison">${icon('close', 'small')}</button></div>`;
  }).join('');
}

function toggleSaved(id) {
  if (!Number.isInteger(id) || id <= 0) return;
  if (state.saved.has(id)) state.saved.delete(id);
  else state.saved.add(id);
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...state.saved])); }
  catch { toast('Your shortlist works for this visit, but this browser could not save it for later.'); }
  renderNavigation();
  renderTable();
}

function toggleCompare(id) {
  if (!Number.isInteger(id) || id <= 0) return;
  if (state.selected.includes(id)) state.selected = state.selected.filter((selected) => selected !== id);
  else if (state.selected.length < 2) state.selected.push(id);
  else toast('Two players make a head-to-head. Remove one to choose someone else.');
  renderNavigation();
  renderTable();
}

function setMode(mode) {
  state.mode = mode;
  state.page = 1;
  renderNavigation();
  if (state.ready) renderTable();
  syncUrl();
}

async function loadPlayers() {
  const requestId = ++state.requestId;
  state.controller?.abort();
  const controller = new AbortController();
  state.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 15000);
  state.filters = readFilters();
  const params = new URLSearchParams({ limit: '1000' });
  for (const [key, value] of Object.entries(state.filters)) if (value) params.set(key, value);
  setBusy(true);
  if (!state.ready) showTableState('Opening the player room', 'Reading your saved player and fixture data.', { loading: true });
  try {
    const result = await api(`/players?${params}`, controller.signal);
    if (requestId !== state.requestId) return;
    state.players = result.players;
    for (const player of result.players) if (player.player_id != null) state.knownPlayers.set(player.player_id, player);
    state.ready = true;
    state.page = 1;
    const warnings = [...result.warnings];
    if (result.count === 1000) warnings.push('This view loads up to 1,000 players. Refine your filters to narrow the results.');
    $('#filter-warnings').textContent = warnings.join(' ');
    $('#filter-warnings').hidden = warnings.length === 0;
    $('#snapshot-status').classList.remove('error');
    $('#snapshot-status span:last-child').textContent = 'Local snapshot';
    renderActiveFilters();
    renderNavigation();
    renderTable();
    syncUrl();
  } catch (error) {
    if (requestId !== state.requestId) return;
    state.ready = false;
    $('#result-count').textContent = '—';
    $('#snapshot-status').classList.add('error');
    $('#snapshot-status span:last-child').textContent = 'Data unavailable';
    showTableState('A pause in play.', error.name === 'AbortError' || error === 'timeout'
      ? 'Loading took too long. Check the server and try again.'
      : error.message || 'We could not reach your data. Check the server and try again.', { retry: true });
  } finally {
    clearTimeout(timeout);
    if (requestId === state.requestId) setBusy(false);
  }
}

async function initialize() {
  setBusy(true);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const [teams, dataset] = await Promise.all([api('/teams', controller.signal), api('/dataset', controller.signal)]);
    const currentTeam = $('#team-filter').value || urlState.get('team') || '';
    $('#team-filter').innerHTML = '<option value="">All clubs</option>' + teams.map((team) => `<option value="${escape(team.name)}">${escape(team.name)}</option>`).join('');
    const knownTeam = teams.find((team) => normalize(team.name) === normalize(currentTeam));
    if (knownTeam) $('#team-filter').value = knownTeam.name;
    else if (currentTeam) {
      const option = new Option(currentTeam, currentTeam, true, true);
      $('#team-filter').append(option);
    }
    $('#dataset-players').textContent = number.format(dataset.player_count);
    $('#dataset-teams').textContent = number.format(dataset.team_count);
    $('#file-saved-label').textContent = `Player file saved ${date.format(new Date(dataset.players_file_saved_at))}`;
    $('#snapshot-details').innerHTML = `<div><dt>Player file saved</dt><dd>${escape(date.format(new Date(dataset.players_file_saved_at)))}</dd></div><div><dt>Fixture file saved</dt><dd>${escape(date.format(new Date(dataset.fixtures_file_saved_at)))}</dd></div><div><dt>Times displayed in</dt><dd>${escape(Intl.DateTimeFormat().resolvedOptions().timeZone)}</dd></div>`;
    await loadPlayers();
  } catch (error) {
    state.ready = false;
    $('#snapshot-status').classList.add('error');
    $('#snapshot-status span:last-child').textContent = 'Data unavailable';
    showTableState('A pause in play.', error.name === 'AbortError' ? 'Loading took too long. Please try again.' : error.message, { retry: true });
    setBusy(false);
  } finally { clearTimeout(timeout); }
}

function showDialog(dialog) {
  $$('dialog[open]').forEach((open) => { if (open !== dialog) open.close(); });
  if (!dialog.open) dialog.showModal();
}

function playerDetail(player) {
  if (!player) return;
  $('#player-detail-content').innerHTML = `<div class="player-identity">${clubAvatar(player)}<div><h2 id="player-detail-title">${escape(player.name)}</h2><p>${escape(player.team_name || `Club ${player.team_id}`)} · ${escape(player.position)} · ID ${escape(player.player_id ?? 'unknown')}</p></div></div>
    <div class="player-stat-grid">${[
      ['PRICE', price(player.price)], ['TOTAL POINTS', format(player.total_points)], ['MINUTES', format(player.minutes)],
      ['PTS / £m', format(player.points_per_million, 2)], ['PTS / 90', format(player.points_per_90, 2)], ['GOALS / ASSISTS', `${format(player.goals)} / ${format(player.assists)}`],
    ].map(([label, value]) => `<div class="player-stat"><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>
    <div class="player-next-fixture">NEXT OPPONENT<strong>${escape(player.next_opponent || 'No known upcoming opponent')}</strong></div>
    <button id="detail-compare" class="primary-button" type="button" ${player.player_id == null ? 'disabled' : ''}>${icon('compare')}${state.selected.includes(player.player_id) ? 'Remove from comparison' : 'Add to comparison'}</button>
    <p class="comparison-footnote">Observed statistics from your saved files. Points per 90 can be misleading with a small minutes sample.</p>`;
  $('#detail-compare').addEventListener('click', () => {
    if (state.selected.length === 2 && !state.selected.includes(player.player_id)) {
      toast('Remove a player from the head-to-head before adding another.');
      return;
    }
    toggleCompare(player.player_id);
    $('#player-dialog').close();
  });
  showDialog($('#player-dialog'));
}

async function openComparison() {
  if (state.selected.length !== 2) { toast('Tick the compare boxes beside two players to start a head-to-head.'); return; }
  state.comparisonController?.abort();
  const controller = new AbortController();
  state.comparisonController = controller;
  const timeout = setTimeout(() => controller.abort(), 15000);
  const dialog = $('#compare-dialog');
  $('#comparison-content').innerHTML = '<div class="table-state"><div class="loading-spinner"></div><p>Putting the numbers side by side…</p></div>';
  showDialog(dialog);
  try {
    const params = new URLSearchParams({ player_one: state.selected[0], player_two: state.selected[1] });
    const result = await api(`/compare?${params}`, controller.signal);
    if (!dialog.open || controller.signal.aborted) return;
    const [first, second] = result.players;
    const metrics = [
      ['Price', 'price', 1, true], ['Total points', 'total_points', 0, false], ['Minutes played', 'minutes', 0, false],
      ['Goals', 'goals', 0, false], ['Assists', 'assists', 0, false],
      ['Points per £m', 'points_per_million', 2, false], ['Points per 90', 'points_per_90', 2, false],
    ];
    $('#comparison-content').innerHTML = `<div class="comparison-players">${[first, second].map((player) => `<div class="comparison-player">${icon('shirt', 'shirt-icon')}<span class="position-badge ${player.position.toLowerCase()}">${escape(player.position)}</span><h3>${escape(player.name)}</h3><p>${escape(player.team_name || `Club ${player.team_id}`)}</p></div>`).join('')}</div>
      <div class="comparison-label">OBSERVED PERFORMANCE</div>
      ${metrics.map(([label, field, decimals, cheaper]) => {
        const a = first[field], b = second[field];
        const comparable = a != null && b != null && a !== b;
        const aHigher = comparable && (cheaper ? a < b : a > b);
        const bHigher = comparable && !aHigher;
        return `<div class="comparison-row"><span class="metric-value ${aHigher ? 'higher' : ''}">${field === 'price' ? price(a) : format(a, decimals)}</span><span class="metric-label">${label}</span><span class="metric-value ${bHigher ? 'higher' : ''}">${field === 'price' ? price(b) : format(b, decimals)}</span></div>`;
      }).join('')}
      <div class="comparison-row opponents"><span class="metric-value">${escape(first.next_opponent || '—')}</span><span class="metric-label">Next opponent</span><span class="metric-value">${escape(second.next_opponent || '—')}</span></div>
      <p class="comparison-footnote">${first.position !== second.position ? 'These players play different positions. ' : ''}Dots mark higher figures, or a lower price. More minutes means a larger sample, not a prediction. There is no overall winner or expected-points forecast here.</p>`;
  } catch (error) {
    if (!dialog.open) return;
    $('#comparison-content').innerHTML = `<div class="table-state">${icon('info')}<h3>Comparison unavailable</h3><p>${escape(error.name === 'AbortError' ? 'The comparison took too long. Close this window and try again.' : error.message)}</p></div>`;
  } finally { clearTimeout(timeout); }
}

function exportCsv() {
  const players = visiblePlayers();
  if (!players.length) return;
  const fields = ['player_id', 'name', 'team_name', 'position', 'price', 'total_points', 'minutes', 'goals', 'assists', 'points_per_million', 'points_per_90', 'next_opponent'];
  const cell = (value) => {
    let text = String(value ?? '');
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const csv = '\ufeff' + [fields, ...players.map((player) => fields.map((field) => player[field]))].map((row) => row.map(cell).join(',')).join('\r\n');
  const blobUrl = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  const anchor = document.createElement('a');
  anchor.href = blobUrl;
  anchor.download = 'touchline-shortlist.csv';
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  toast(`Exported ${number.format(players.length)} players. Your next move is ready.`);
}

function resetFilters() {
  $('#team-filter').value = '';
  $('#price-filter').value = $('#price-filter').max;
  $('#minutes-filter').value = '0';
  $('#sort-select').value = 'points';
  $('#player-search').value = '';
  state.position = '';
  updatePositionTabs();
  updatePrice();
  loadPlayers();
}

function updatePositionTabs() {
  $$('.position-tab').forEach((button) => {
    const active = button.dataset.position === state.position;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

$('#filter-form').addEventListener('submit', (event) => { event.preventDefault(); loadPlayers(); });
$('#filter-form').addEventListener('change', () => loadPlayers());
$('#price-filter').addEventListener('input', updatePrice);
$('#reset-filters').addEventListener('click', resetFilters);
$('#sort-select').addEventListener('change', loadPlayers);
$('#refresh-data').addEventListener('click', initialize);
$('#nav-explorer').addEventListener('click', () => setMode('all'));
$('#nav-saved').addEventListener('click', () => setMode('saved'));
$('#nav-compare').addEventListener('click', openComparison);
$('#open-compare').addEventListener('click', openComparison);
$('#data-guide').addEventListener('click', () => showDialog($('#guide-dialog')));
$('#export-csv').addEventListener('click', exportCsv);
$('#clear-saved').addEventListener('click', () => {
  state.saved.clear();
  try { localStorage.setItem(STORAGE_KEY, '[]'); }
  catch { toast('The shortlist was cleared for this visit, but browser storage could not be updated.'); }
  renderNavigation();
  if (state.ready) renderTable();
});
$('#clear-compare').addEventListener('click', () => {
  state.selected = [];
  renderNavigation();
  if (state.ready) renderTable();
  $('#nav-compare').focus({ preventScroll: true });
});
$('#copy-view').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(location.href); toast('View link copied. Your filters are included; saved players stay in this browser.'); }
  catch { toast('Copy the address from your browser to share these filters.'); }
});

$$('.position-tab').forEach((button) => button.addEventListener('click', () => {
  state.position = button.dataset.position;
  updatePositionTabs();
  loadPlayers();
}));
$$('.column-sort').forEach((button) => button.addEventListener('click', () => {
  $('#sort-select').value = button.dataset.sort;
  loadPlayers();
}));
$('#player-search').addEventListener('input', () => {
  state.page = 1;
  if (state.ready) renderTable();
  syncUrl();
});
$('#player-rows').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const id = Number(button.dataset.player);
  if (button.dataset.action === 'save') toggleSaved(id);
  if (button.dataset.action === 'detail') playerDetail(
    state.knownPlayers.get(id) || state.players.find((player) => player.name === button.dataset.name),
  );
});
$('#player-rows').addEventListener('change', (event) => {
  if (event.target.matches('[data-action="compare"]')) toggleCompare(Number(event.target.dataset.player));
});
$('#compare-slots').addEventListener('click', (event) => {
  const button = event.target.closest('[data-remove-player]');
  if (button) toggleCompare(Number(button.dataset.removePlayer));
});
$('#previous-page').addEventListener('click', () => { state.page--; renderTable(); });
$('#next-page').addEventListener('click', () => { state.page++; renderTable(); });
$$('.close-dialog').forEach((button) => button.addEventListener('click', () => button.closest('dialog').close()));
$$('dialog').forEach((dialog) => {
  dialog.addEventListener('click', (event) => { if (event.target === dialog && !event.target.closest('.dialog-top')) {
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  } });
  dialog.addEventListener('close', () => {
    if (dialog.contains($('#toast'))) { $('#toast').hidden = true; document.body.append($('#toast')); }
    if (dialog.id === 'compare-dialog') state.comparisonController?.abort();
  });
});

let storageWarning = false;
try {
  const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
  if (!Array.isArray(saved)) throw new Error('Invalid shortlist');
  state.saved = new Set(saved.filter((id) => Number.isInteger(id) && id > 0));
} catch { storageWarning = true; }
const initialPrice = Number(urlState.get('max_price'));
if (urlState.has('max_price') && Number.isFinite(initialPrice)) $('#price-filter').value = Math.max(0, Math.min(20, initialPrice));
if (['0', '450', '900', '1800'].includes(urlState.get('min_minutes'))) $('#minutes-filter').value = urlState.get('min_minutes');
if (['points', 'price', 'points-per-million', 'points-per-90'].includes(urlState.get('sort_by'))) $('#sort-select').value = urlState.get('sort_by');
$('#player-search').value = urlState.get('q') || '';
updatePositionTabs();
updatePrice();
renderNavigation();
initialize();
if (storageWarning) toast('This browser could not read your saved shortlist. You can still explore and select players.');
