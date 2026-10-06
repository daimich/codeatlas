const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; };
async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Request failed'); return data;
}
function status(message) { $('status').textContent = message; }
function codeCard(hit, distance) {
  const card = node('article', '', 'card'); const header = node('div', '', 'card-header');
  header.append(node('strong', hit.qualified), node('span', hit.kind, 'badge'));
  card.append(header, node('div', hit.path + ':' + hit.start + '–' + hit.end + (distance ? ' · caller distance ' + distance : ''), 'citation'));
  const pre = node('pre', ''); pre.append(node('code', hit.text)); card.append(pre);
  if (['function', 'class'].includes(hit.kind)) {
    const button = node('button', 'Trace callers →', 'trace');
    button.addEventListener('click', () => trace(hit.id)); card.append(button);
  }
  return card;
}
async function trace(symbol) {
  status('Walking the call graph…');
  try {
    const result = await api('impact', {symbol, depth: 3}); $('results').replaceChildren();
    $('mode').textContent = 'Impact of ' + result.symbol.qualified;
    $('results').append(node('p', result.note, 'muted'));
    if (!result.affected.length) $('results').append(node('div', 'No callers were resolved in this snapshot.', 'empty'));
    result.affected.forEach(hit => $('results').append(codeCard(hit, hit.distance)));
    status(result.affected.length + ' reachable callers · maximum depth 3');
  } catch (error) { status(error.message); }
}
$('query-form').addEventListener('submit', async (event) => {
  event.preventDefault(); $('submit').disabled = true; status('Searching the repository…');
  try {
    const result = await api('search', {question: $('query').value, k: 8}); $('results').replaceChildren();
    $('mode').textContent = result.hits.length + ' search results';
    if (!result.hits.length) $('results').append(node('div', 'No matching code found. Try a symbol name or a phrase from a docstring.', 'empty'));
    result.hits.forEach(hit => $('results').append(codeCard(hit)));
    status(result.retrieval + ' · ' + result.latency_ms + ' ms');
  } catch (error) { status(error.message); }
  finally { $('submit').disabled = false; }
});
document.querySelectorAll('[data-query]').forEach(button => button.addEventListener('click', () => {
  $('query').value = button.dataset.query; $('query').focus();
}));
api('status').then(meta => {
  $('inventory').replaceChildren(); $('count').textContent = meta.files + ' files indexed';
  [['Source files', meta.files], ['Searchable records', meta.records], ['Resolved calls', meta.edges]].forEach(([label, value]) => {
    const row = node('div', '', 'metric'); row.append(node('span', label), node('strong', String(value))); $('inventory').append(row);
  });
  $('inventory').append(node('p', 'Python: AST symbols and call edges. Other languages: source text search.', 'muted'));
  if (!meta.files) $('inventory').append(node('p', 'Run python -m codeatlas index /path/to/repository, then restart the server.', 'muted'));
  status(meta.warnings.length ? meta.warnings.length + ' indexing warnings · see CLI status' : 'Snapshot ready.');
}).catch(error => status(error.message));
