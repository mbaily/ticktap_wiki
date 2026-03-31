/* block_editor.js — TickTap Wiki block editor
 * Vanilla JS, no dependencies, no bundler.
 * v2: selection-based bottom toolbar, no per-card action buttons.
 */

(function () {
'use strict';

// ─── PARSER ────────────────────────────────────────────────────────────────────

const RE_HEADING    = /^(={2,6}) (.+?) \1\s*$/;
const RE_TODO       = /^(\s*)\[([ x~])\] (.*)$/;
const RE_BULLET     = /^( {2,})(\* )(.*)$/;
const RE_ORDERED    = /^( {2,})(- )(.*)$/;
const RE_TABLE_ROW  = /^[\|^]/;
const RE_HR         = /^-{4,}\s*$/;
const RE_META_OPEN  = /^~~META:\s*$/;
const RE_META_CLOSE = /^~~\s*$/;
const RE_FENCE_OPEN = /^```(.*)$/;
const RE_FENCE_CLOSE= /^```\s*$/;
const RE_IMAGE_ONLY = /^\{\{[^}]+\}\}\s*$/;

function markupToBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (i === 0 && RE_META_OPEN.test(line)) {
      const raw = [line]; i++;
      while (i < lines.length) { raw.push(lines[i]); if (RE_META_CLOSE.test(lines[i])) { i++; break; } i++; }
      blocks.push({ type: 'meta', raw: raw.join('\n'), lines: raw.slice(1, -1) }); continue;
    }
    if (RE_HR.test(line)) { blocks.push({ type: 'hr', raw: line }); i++; continue; }
    const fenceM = line.match(RE_FENCE_OPEN);
    if (fenceM) {
      const lang = fenceM[1].trim(); const raw = [line]; const codeLines = []; i++;
      while (i < lines.length) { raw.push(lines[i]); if (RE_FENCE_CLOSE.test(lines[i])) { i++; break; } codeLines.push(lines[i]); i++; }
      blocks.push({ type: 'code', lang, codeLines, raw: raw.join('\n') }); continue;
    }
    const hm = line.match(RE_HEADING);
    if (hm) { blocks.push({ type: 'heading', level: 7 - hm[1].length, text: hm[2], raw: line }); i++; continue; }
    const tm = line.match(RE_TODO);
    if (tm) { blocks.push({ type: 'todo', indent: tm[1].length, state: tm[2], text: tm[3], raw: line }); i++; continue; }
    const bm = line.match(RE_BULLET);
    if (bm) { blocks.push({ type: 'bullet', indent: bm[1].length - 2, text: bm[3], raw: line }); i++; continue; }
    const om = line.match(RE_ORDERED);
    if (om) { blocks.push({ type: 'ordered', indent: om[1].length - 2, text: om[3], raw: line }); i++; continue; }
    if (RE_TABLE_ROW.test(line)) {
      const raw = [line]; i++;
      while (i < lines.length && RE_TABLE_ROW.test(lines[i])) { raw.push(lines[i]); i++; }
      blocks.push({ type: 'table', raw: raw.join('\n'), rows: raw }); continue;
    }
    if (RE_IMAGE_ONLY.test(line)) {
      const m = line.trim().match(/^\{\{([^|}]+)(\|([^}]*))?\}\}/);
      blocks.push({ type: 'image', src: m ? m[1].trim() : '', alt: m && m[3] != null ? m[3].trim() : '', raw: line }); i++; continue;
    }
    if (line === '') { let count = 0; while (i < lines.length && lines[i] === '') { count++; i++; } blocks.push({ type: 'blank', count }); continue; }
    const paraLines = [line]; i++;
    while (i < lines.length) {
      const l = lines[i];
      if (l === '' || RE_HR.test(l) || RE_FENCE_OPEN.test(l) || RE_HEADING.test(l) || RE_TODO.test(l) || RE_BULLET.test(l) || RE_ORDERED.test(l) || RE_TABLE_ROW.test(l) || RE_META_OPEN.test(l) || RE_IMAGE_ONLY.test(l)) break;
      paraLines.push(l); i++;
    }
    blocks.push({ type: 'para', lines: paraLines, raw: paraLines.join('\n') });
  }
  return blocks;
}

// ─── SERIALIZER ────────────────────────────────────────────────────────────────

function serializeBlock(b) {
  switch (b.type) {
    case 'meta': return `~~META:\n${b.lines.join('\n')}\n~~`;
    case 'heading': { const eq = '='.repeat(7 - b.level); return `${eq} ${b.text} ${eq}`; }
    case 'para': return b.lines.join('\n');
    case 'todo': return `${' '.repeat(b.indent)}[${b.state}] ${b.text}`;
    case 'bullet': return `${' '.repeat(b.indent + 2)}* ${b.text}`;
    case 'ordered': return `${' '.repeat(b.indent + 2)}- ${b.text}`;
    case 'hr': return '----';
    case 'code': return `\`\`\`${b.lang}\n${b.codeLines.join('\n')}\n\`\`\``;
    case 'table': return b.rows.join('\n');
    case 'image': return `{{${b.src}${b.alt ? '|' + b.alt : ''}}}`;
    case 'blank': return '\n'.repeat(b.count - 1);
    default: return b.raw || '';
  }
}
function blocksToMarkup(blocks) { return blocks.map(serializeBlock).join('\n'); }

// ─── UNDO STACK ────────────────────────────────────────────────────────────────

function makeUndoStack(maxSize) {
  maxSize = maxSize || 100;
  let stack = [], pos = -1, debounceTimer = null;
  function push(markup) { stack = stack.slice(0, pos + 1); if (stack.length > 0 && stack[stack.length - 1] === markup) return; stack.push(markup); if (stack.length > maxSize) stack.shift(); pos = stack.length - 1; }
  function current() { return pos >= 0 ? stack[pos] : null; }
  function canUndo() { return pos > 0; }
  function canRedo() { return pos < stack.length - 1; }
  function undo() { if (pos > 0) { pos--; return stack[pos]; } return null; }
  function redo() { if (pos < stack.length - 1) { pos++; return stack[pos]; } return null; }
  function pushDebounced(callback, delay) { clearTimeout(debounceTimer); debounceTimer = setTimeout(callback, delay || 800); }
  function cancelDebounce() { clearTimeout(debounceTimer); }
  return { push, current, canUndo, canRedo, undo, redo, pushDebounced, cancelDebounce };
}

// ─── DRAG & DROP (mouse + touch) ───────────────────────────────────────────────

function initDragDrop(container, getBlocks, onReorder) {
  let dragSrc = null, touchClone = null, touchSrcEl = null, placeholder = null;
  container.addEventListener('dragstart', function (e) {
    const card = e.target.closest('.be-card');
    if (!card) return;
    if (!e.target.closest('.be-grip')) { e.preventDefault(); return; }
    dragSrc = card; e.dataTransfer.effectAllowed = 'move';
    setTimeout(function () { dragSrc.classList.add('be-dragging'); }, 0);
  });
  container.addEventListener('dragend', function () {
    if (dragSrc) { dragSrc.classList.remove('be-dragging'); dragSrc = null; }
    container.querySelectorAll('.be-drag-over-before,.be-drag-over-after').forEach(function (el) { el.classList.remove('be-drag-over-before', 'be-drag-over-after'); });
    if (placeholder) { placeholder.remove(); placeholder = null; }
  });
  container.addEventListener('dragover', function (e) {
    if (!dragSrc) return;
    const card = e.target.closest('.be-card');
    if (!card || card === dragSrc) return;
    e.preventDefault();
    container.querySelectorAll('.be-drag-over-before,.be-drag-over-after').forEach(function (el) { el.classList.remove('be-drag-over-before', 'be-drag-over-after'); });
    const rect = card.getBoundingClientRect();
    card.classList.add(e.clientY < rect.top + rect.height / 2 ? 'be-drag-over-before' : 'be-drag-over-after');
  });
  container.addEventListener('drop', function (e) {
    if (!dragSrc) return;
    const card = e.target.closest('.be-card');
    container.querySelectorAll('.be-drag-over-before,.be-drag-over-after').forEach(function (el) { el.classList.remove('be-drag-over-before', 'be-drag-over-after'); });
    if (!card || card === dragSrc) return;
    e.preventDefault();
    const rect = card.getBoundingClientRect();
    if (e.clientY < rect.top + rect.height / 2) container.insertBefore(dragSrc, card);
    else card.after(dragSrc);
    _syncDOM(getBlocks, container, onReorder);
  });
  // Touch
  container.addEventListener('touchstart', function (e) {
    const handle = e.target.closest('.be-grip'); if (!handle) return;
    touchSrcEl = handle.closest('.be-card'); if (!touchSrcEl) return;
    const t = e.touches[0];
    touchClone = touchSrcEl.cloneNode(true);
    touchClone.style.cssText = 'position:fixed;z-index:9999;opacity:0.8;pointer-events:none;width:' + touchSrcEl.offsetWidth + 'px;left:' + (t.clientX - 20) + 'px;top:' + (t.clientY - 20) + 'px;';
    document.body.appendChild(touchClone);
    touchSrcEl.classList.add('be-dragging');
    placeholder = document.createElement('div'); placeholder.className = 'be-placeholder';
    placeholder.style.height = touchSrcEl.offsetHeight + 'px'; touchSrcEl.after(placeholder);
  }, { passive: true });
  container.addEventListener('touchmove', function (e) {
    if (!touchSrcEl || !touchClone) return; e.preventDefault();
    const t = e.touches[0];
    touchClone.style.left = (t.clientX - 20) + 'px'; touchClone.style.top = (t.clientY - 20) + 'px';
    touchClone.style.display = 'none';
    const el = document.elementFromPoint(t.clientX, t.clientY);
    touchClone.style.display = '';
    const card = el && el.closest('.be-card');
    if (card && card !== touchSrcEl) {
      const rect = card.getBoundingClientRect();
      if (t.clientY < rect.top + rect.height / 2) card.before(placeholder); else card.after(placeholder);
    }
  }, { passive: false });
  container.addEventListener('touchend', function () {
    if (!touchSrcEl) return;
    if (placeholder) { placeholder.replaceWith(touchSrcEl); placeholder = null; }
    touchSrcEl.classList.remove('be-dragging');
    if (touchClone) { touchClone.remove(); touchClone = null; }
    touchSrcEl = null;
    _syncDOM(getBlocks, container, onReorder);
  });
}
function _syncDOM(getBlocks, container, onReorder) {
  const cards = Array.from(container.querySelectorAll('.be-card'));
  const old = getBlocks();
  onReorder(cards.map(function (c) { return old.find(function (b) { return b._id === c.dataset.id; }); }).filter(Boolean));
}

// ─── BLOCK ID ──────────────────────────────────────────────────────────────────
let _nextId = 0;
function assignId(b) { if (!b._id) b._id = 'b' + (_nextId++); return b; }

// ─── CARD RENDERING ────────────────────────────────────────────────────────────

function badgeLabel(b) {
  switch (b.type) {
    case 'heading': return 'h' + b.level; case 'para': return 'p'; case 'todo': return '☐';
    case 'bullet': return '•'; case 'ordered': return '1.'; case 'hr': return '—';
    case 'code': return '</>'; case 'table': return '⊞'; case 'image': return '🖼';
    case 'meta': return 'meta'; case 'blank': return '⏎'; default: return '?';
  }
}

function renderCard(block, api) {
  const card = document.createElement('div');
  card.className = 'be-card';
  card.dataset.id = block._id;
  card.draggable = true;

  // Selection radio
  const sel = document.createElement('button');
  sel.type = 'button';
  sel.className = 'be-sel';
  sel.title = 'Select block';
  sel.addEventListener('click', function (e) {
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      block._selected = !block._selected;
    } else {
      // toggle: if this was the only selected, deselect it; otherwise select only this
      const wasOnlySelected = block._selected && api.getSelection().length === 1;
      api.deselectAll();
      block._selected = !wasOnlySelected;
    }
    api.syncSelection();
  });
  card.appendChild(sel);

  // Grip
  const grip = document.createElement('span');
  grip.className = 'be-grip';
  grip.title = 'Drag to reorder';
  grip.innerHTML = '&#8942;&#8942;';
  grip.setAttribute('draggable', 'true');
  card.appendChild(grip);

  // Quick insert below
  const qi = _quickInsertType(block);
  const qib = document.createElement('button'); qib.type = 'button';
  qib.className = 'be-quick-ins' + (qi ? '' : ' be-quick-ins-disabled');
  qib.textContent = '+';
  qib.title = qi ? 'Quick insert ' + qi.type + ' below' : 'No quick insert';
  qib.draggable = false;
  if (qi) {
    qib.addEventListener('click', function (e) {
      e.stopPropagation();
      api.quickInsertBelow(block, qi.type);
    });
  }
  card.appendChild(qib);

  // Badge (read‑only label)
  const badge = document.createElement('span');
  badge.className = 'be-badge';
  badge.textContent = badgeLabel(block);
  card.appendChild(badge);

  // Content area
  const content = document.createElement('div');
  content.className = 'be-content';
  card.appendChild(content);

  fillContent(block, content, api);

  if (block._selected) card.classList.add('be-selected');
  return card;
}

function fillContent(block, content, api) {
  content.innerHTML = '';
  switch (block.type) {
    case 'heading': {
      const inp = mkInput(block.text, function (v) { block.text = v; api.onChange(); }, api);
      inp.className = 'be-heading-input be-h' + block.level;
      inp.placeholder = 'Heading text…';
      content.appendChild(inp); break;
    }
    case 'para': {
      block.lines.forEach(function (ln, idx) { content.appendChild(makeParaLine(block, idx, content, api)); });
      break;
    }
    case 'todo': {
      const row = document.createElement('div'); row.className = 'be-row';
      if (block.indent > 0) row.style.paddingLeft = (block.indent * 0.75) + 'em';
      const cb = document.createElement('button'); cb.type = 'button'; cb.className = 'be-todo-cb';
      cb.draggable = false;
      function updateCbLabel() {
        cb.textContent = block.state === 'x' ? '☑' : (block.state === '~' ? '▣' : '☐');
      }
      updateCbLabel();
      cb.addEventListener('click', function (e) {
        e.stopPropagation();
        block.state = block.state === ' ' ? 'x' : (block.state === 'x' ? '~' : ' ');
        updateCbLabel();
        api.pushUndo();
      });
      row.appendChild(cb);
      const inp = mkInput(block.text, function (v) { block.text = v; api.onChange(); }, api);
      inp.className = 'be-list-input'; inp.placeholder = 'Todo text…';
      row.appendChild(inp); content.appendChild(row); break;
    }
    case 'bullet': case 'ordered': {
      const row = document.createElement('div'); row.className = 'be-row';
      if (block.indent > 0) row.style.paddingLeft = (block.indent * 0.75) + 'em';
      const marker = document.createElement('span'); marker.className = 'be-list-marker';
      marker.textContent = block.type === 'bullet' ? '•' : '–';
      row.appendChild(marker);
      const inp = mkInput(block.text, function (v) { block.text = v; api.onChange(); }, api);
      inp.className = 'be-list-input'; inp.placeholder = block.type === 'bullet' ? 'Bullet…' : 'Ordered…';
      row.appendChild(inp); content.appendChild(row); break;
    }
    case 'hr': {
      const d = document.createElement('div'); d.className = 'be-hr-preview'; d.textContent = '— Horizontal rule —';
      content.appendChild(d); break;
    }
    case 'code': {
      const lr = document.createElement('div'); lr.className = 'be-row';
      const ll = document.createElement('span'); ll.className = 'be-code-lang-label'; ll.textContent = 'Lang:';
      const li = document.createElement('input'); li.type = 'text'; li.className = 'be-code-lang'; li.value = block.lang; li.placeholder = '(none)';
      li.addEventListener('input', function () { block.lang = li.value; api.onChange(); });
      li.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      lr.appendChild(ll); lr.appendChild(li); content.appendChild(lr);
      const ta = document.createElement('textarea'); ta.className = 'be-code-area';
      ta.value = block.codeLines.join('\n'); ta.rows = Math.max(3, block.codeLines.length + 1); ta.spellcheck = false;
      ta.addEventListener('input', function () { block.codeLines = ta.value.split('\n'); autoGrow(ta); api.onChange(); });
      ta.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      content.appendChild(ta); break;
    }
    case 'table': {
      const ta = document.createElement('textarea'); ta.className = 'be-table-area';
      ta.value = block.rows.join('\n'); ta.rows = Math.max(3, block.rows.length + 1); ta.spellcheck = false;
      ta.addEventListener('input', function () { block.rows = ta.value.split('\n'); autoGrow(ta); api.onChange(); });
      ta.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      content.appendChild(ta); break;
    }
    case 'image': {
      const r = document.createElement('div'); r.className = 'be-row';
      const sl = document.createElement('span'); sl.className = 'be-img-label'; sl.textContent = '🖼';
      const si = document.createElement('input'); si.type = 'text'; si.className = 'be-img-src'; si.value = block.src; si.placeholder = 'image.png';
      const ai = document.createElement('input'); ai.type = 'text'; ai.className = 'be-img-alt'; ai.value = block.alt; ai.placeholder = 'Alt text';
      si.addEventListener('input', function () { block.src = si.value; api.onChange(); }); si.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      ai.addEventListener('input', function () { block.alt = ai.value; api.onChange(); }); ai.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      r.appendChild(sl); r.appendChild(si); r.appendChild(ai); content.appendChild(r); break;
    }
    case 'meta': {
      const ta = document.createElement('textarea'); ta.className = 'be-meta-area';
      ta.value = block.lines.join('\n'); ta.rows = Math.max(2, block.lines.length + 1); ta.spellcheck = false;
      ta.addEventListener('input', function () { block.lines = ta.value === '' ? [] : ta.value.split('\n'); autoGrow(ta); api.onChange(); });
      ta.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      content.appendChild(ta); break;
    }
    case 'blank': {
      const sp = document.createElement('div'); sp.className = 'be-blank-spacer';
      sp.textContent = '(blank' + (block.count > 1 ? ' ×' + block.count : '') + ')';
      content.appendChild(sp); break;
    }
    default: {
      const ta = document.createElement('textarea'); ta.className = 'be-raw-area';
      ta.value = block.raw || ''; ta.rows = Math.max(2, (block.raw || '').split('\n').length + 1); ta.spellcheck = false;
      ta.addEventListener('input', function () { block.raw = ta.value; autoGrow(ta); api.onChange(); });
      ta.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
      content.appendChild(ta); break;
    }
  }
}

// ── Paragraph per-line inputs ────────────────────────────────────────────────
let _reindexing = false;
let _rendering = false;
function makeParaLine(block, idx, content, api) {
  const inp = document.createElement('textarea'); inp.className = 'be-para-line be-autogrow';
  inp.rows = 1; inp.value = block.lines[idx]; inp.placeholder = idx === 0 ? 'Paragraph text…' : '';
  inp.addEventListener('input', function () { block.lines[idx] = inp.value; autoGrow(inp); api.onChange(); });
  inp.addEventListener('blur', function () { if (!_reindexing && !_rendering) api.pushUndo(); });
  inp.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      const caret = inp.selectionStart;
      const before = inp.value.slice(0, caret);
      const after = inp.value.slice(caret);
      block.lines[idx] = before;
      block.lines.splice(idx + 1, 0, after);
      _reindexPara(block, content, api);
      const nextInp = content.querySelectorAll('.be-para-line')[idx + 1];
      if (nextInp) { nextInp.focus(); nextInp.setSelectionRange(0, 0); }
      api.pushUndoImmediate();
    } else if (e.key === 'Backspace' && inp.selectionStart === 0 && inp.selectionEnd === 0 && idx > 0 && block.lines.length > 1) {
      e.preventDefault();
      const mergePos = block.lines[idx - 1].length;
      block.lines[idx - 1] += block.lines[idx];
      block.lines.splice(idx, 1);
      _reindexPara(block, content, api);
      const prevInp = content.querySelectorAll('.be-para-line')[idx - 1];
      if (prevInp) { prevInp.focus(); prevInp.setSelectionRange(mergePos, mergePos); }
      api.pushUndoImmediate();
    }
  });
  setTimeout(function () { autoGrow(inp); }, 0);
  return inp;
}
function _reindexPara(block, content, api) {
  _reindexing = true;
  // Remove all existing line inputs
  Array.from(content.querySelectorAll('.be-para-line')).forEach(function (el) { el.remove(); });
  // Rebuild entirely from block.lines so count always matches data
  block.lines.forEach(function (line, i) {
    const n = makeParaLine(block, i, content, api);
    content.appendChild(n);
    setTimeout(function () { autoGrow(n); }, 0);
  });
  _reindexing = false;
}
function mkInput(initialValue, onChange, api) {
  const inp = document.createElement('textarea'); inp.className = 'be-autogrow'; inp.rows = 1;
  inp.value = initialValue;
  inp.addEventListener('input', function () { onChange(inp.value); autoGrow(inp); });
  inp.addEventListener('blur', function () { if (!_rendering) api.pushUndo(); });
  setTimeout(function () { autoGrow(inp); }, 0);
  return inp;
}
function autoGrow(ta) { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }

// ─── TYPE PICKER ───────────────────────────────────────────────────────────────
const TYPE_PICKER_ITEMS = [
  { type: 'para', label: '¶ Paragraph' },
  { type: 'heading', label: 'H Heading', sub: [
    { level: 1, label: 'H1' }, { level: 2, label: 'H2' }, { level: 3, label: 'H3' }, { level: 4, label: 'H4' }, { level: 5, label: 'H5' },
  ]},
  { type: 'todo', label: '☐ Todo' }, { type: 'bullet', label: '• Bullet' }, { type: 'ordered', label: '1. Ordered' },
  { type: 'code', label: '</> Code' }, { type: 'table', label: '⊞ Table' },
  { type: 'hr', label: '— HR' }, { type: 'image', label: '🖼 Image' }, { type: 'blank', label: '⏎ Blank' },
];

function makeDefaultBlock(type, level) {
  switch (type) {
    case 'heading':  return assignId({ type: 'heading', level: level || 2, text: '' });
    case 'para':     return assignId({ type: 'para', lines: [''], raw: '' });
    case 'todo':     return assignId({ type: 'todo', indent: 0, state: ' ', text: '' });
    case 'bullet':   return assignId({ type: 'bullet', indent: 0, text: '' });
    case 'ordered':  return assignId({ type: 'ordered', indent: 0, text: '' });
    case 'hr':       return assignId({ type: 'hr', raw: '----' });
    case 'code':     return assignId({ type: 'code', lang: '', codeLines: [''], raw: '' });
    case 'table':    return assignId({ type: 'table', rows: ['^ Col 1 ^ Col 2 ^', '| Cell 1 | Cell 2 |'], raw: '' });
    case 'image':    return assignId({ type: 'image', src: '', alt: '' });
    case 'blank':    return assignId({ type: 'blank', count: 1 });
    default:         return assignId({ type: 'raw', raw: '' });
  }
}

function _quickInsertType(block) {
  if (!block) return null;
  switch (block.type) {
    case 'todo':    return { type: 'todo', label: '+ ☐' };
    case 'bullet':  return { type: 'bullet', label: '+ •' };
    case 'ordered': return { type: 'ordered', label: '+ 1.' };
    default:        return { type: 'para', label: '+ ¶' };
  }
}

function openTypePicker(anchorEl, afterChoose, quickBlock) {
  document.querySelectorAll('.be-type-picker').forEach(function (el) { el.remove(); });
  const picker = document.createElement('div'); picker.className = 'be-type-picker';

  TYPE_PICKER_ITEMS.forEach(function (item) {
    if (item.sub) {
      const g = document.createElement('div'); g.className = 'be-picker-group';
      const gh = document.createElement('button'); gh.className = 'be-picker-item be-picker-group-header'; gh.textContent = item.label;
      g.appendChild(gh);
      const sl = document.createElement('div'); sl.className = 'be-picker-sublist';
      item.sub.forEach(function (sub) {
        const sb = document.createElement('button'); sb.className = 'be-picker-item be-picker-subitem'; sb.textContent = sub.label;
        sb.addEventListener('click', function () { picker.remove(); afterChoose(item.type, sub.level); });
        sl.appendChild(sb);
      });
      gh.addEventListener('click', function () { sl.classList.toggle('be-picker-sublist-open'); });
      g.appendChild(sl); picker.appendChild(g);
    } else {
      const btn = document.createElement('button'); btn.className = 'be-picker-item'; btn.textContent = item.label;
      btn.addEventListener('click', function () { picker.remove(); afterChoose(item.type, null); });
      picker.appendChild(btn);
    }
  });

  // Quick-insert item at the bottom
  var quick = _quickInsertType(quickBlock);
  if (quick) {
    var sep = document.createElement('div'); sep.className = 'be-picker-sep';
    picker.appendChild(sep);
    var qb = document.createElement('button'); qb.className = 'be-picker-item be-picker-quick';
    qb.textContent = quick.label;
    qb.addEventListener('click', function () { picker.remove(); afterChoose(quick.type, null); });
    picker.appendChild(qb);
  }

  document.body.appendChild(picker);
  const rect = anchorEl.getBoundingClientRect();
  picker.style.left = Math.max(4, Math.min(rect.left + window.scrollX, window.innerWidth - picker.offsetWidth - 8)) + 'px';
  picker.style.top = (rect.top + window.scrollY - picker.offsetHeight - 4) + 'px';
  setTimeout(function () {
    document.addEventListener('click', function cp(e) { if (!picker.contains(e.target)) { picker.remove(); document.removeEventListener('click', cp); } });
  }, 0);
}

// ─── STYLES ───────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('be-styles')) return;
  const style = document.createElement('style'); style.id = 'be-styles';
  style.textContent = `
#be-root { max-width: 860px; margin: 0 auto; padding: 0 4px 80px; font-family: inherit; }
.be-toolbar {
  position: sticky; top: 0; z-index: 200; display: flex; align-items: center;
  gap: .5rem; padding: .5rem .75rem; background: var(--be-toolbar-bg, #ecf0f1);
  border-bottom: 1px solid var(--be-border, #ccc); flex-wrap: wrap;
}
.be-toolbar-title { font-weight: bold; font-size: .95rem; margin-right: auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40vw; }
.be-toolbar button, .be-toolbar a.be-btn {
  padding: .3rem .65rem; border-radius: 4px; border: 1px solid #aaa; cursor: pointer;
  font-size: .85rem; text-decoration: none; display: inline-flex; align-items: center; gap: .3rem;
}
.be-toolbar button.be-save { background: #27ae60; color: #fff; border-color: #1e8449; font-weight: bold; }
.be-toolbar button.be-save:disabled { opacity: .5; cursor: default; }
.be-toolbar button.be-undo, .be-toolbar button.be-redo { background: none; }
.be-loading { text-align: center; padding: 3rem; color: #888; font-style: italic; }
.be-error { background: #fdecea; border: 1px solid #e74c3c; color: #922b21; border-radius: 4px; padding: .6rem 1rem; margin: 1rem 0; }

/* Cards */
.be-card {
  display: flex; align-items: flex-start; gap: .35rem;
  background: var(--be-card-bg, #fff); border: 1px solid var(--be-card-border, #e0e0e0);
  border-radius: 5px; padding: .35rem .4rem; margin: 2px 0;
  transition: box-shadow .1s, border-color .15s; min-height: 2rem;
}
.be-card:hover { box-shadow: 0 1px 4px rgba(0,0,0,.12); }
.be-card.be-selected { border-color: #3498db; background: rgba(52,152,219,.06); box-shadow: inset 3px 0 0 #3498db; }
.be-card.be-dragging { opacity: .4; }
.be-card.be-drag-over-before { border-top: 2px solid #3498db; }
.be-card.be-drag-over-after { border-bottom: 2px solid #3498db; }
.be-placeholder { border: 2px dashed #3498db; border-radius: 5px; background: rgba(52,152,219,.05); }

/* Selection radio button */
.be-sel {
  width: 1.1rem; height: 1.1rem; border-radius: 50%; border: 2px solid #bbb;
  background: none; cursor: pointer; flex-shrink: 0; padding: 0; margin-top: .2rem;
  transition: border-color .1s, background .1s;
}
.be-sel:hover { border-color: #3498db; }
.be-selected .be-sel { border-color: #3498db; background: #3498db; }

.be-grip { cursor: grab; color: #bbb; font-size: .8rem; line-height: 1; padding: .25rem .1rem 0; user-select: none; flex-shrink: 0; }
.be-grip:active { cursor: grabbing; }
.be-badge { font-size: .65rem; background: #ecf0f1; border: 1px solid #ccc; border-radius: 3px; padding: .05rem .25rem; color: #777; flex-shrink: 0; white-space: nowrap; margin-top: .15rem; }
.be-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: .25rem; }
.be-row { display: flex; align-items: center; gap: .4rem; }

/* Inputs — override global textarea styles from wiki CSS */
.be-card textarea {
  border: 1px solid transparent !important; border-radius: 3px; background: transparent !important;
  font-family: inherit !important; font-size: 1rem; padding: .15rem .3rem !important; width: 100%;
  box-sizing: border-box; transition: border-color .1s, background .1s; color: inherit;
  overflow: hidden !important; resize: none;
}
.be-autogrow {
  min-height: 1.6em; line-height: 1.5;
}
.be-card textarea:hover,
.be-card textarea:focus {
  border-color: #3498db; background: var(--be-input-focus-bg, rgba(52,152,219,.05)); outline: none;
}
.be-heading-input { font-weight: bold; }
.be-h1 { font-size: 1.5rem; } .be-h2 { font-size: 1.3rem; } .be-h3 { font-size: 1.15rem; }
.be-h4 { font-size: 1.05rem; } .be-h5 { font-size: .95rem; }
.be-para-line { font-size: 1rem; }
.be-list-input { flex: 1; }
.be-list-marker { font-size: 1rem; color: #888; padding: 0 .2rem; flex-shrink: 0; }
.be-todo-cb {
  flex-shrink: 0; cursor: pointer; background: none; border: none;
  font-size: 1.1rem; line-height: 1; padding: 0; color: inherit;
}
.be-code-lang-label { font-size: .75rem; color: #888; white-space: nowrap; }
.be-code-lang { max-width: 120px; font-size: .85rem; }
.be-code-area, .be-table-area, .be-raw-area, .be-meta-area { font-family: monospace; font-size: .85rem; resize: vertical; min-height: 3rem; overflow: hidden; }
.be-img-src { flex: 2; } .be-img-alt { flex: 1; } .be-img-label { flex-shrink: 0; }
.be-hr-preview { color: #aaa; font-style: italic; font-size: .85rem; padding: .2rem .3rem; }
.be-blank-spacer { color: #ccc; font-style: italic; font-size: .75rem; padding: .1rem .3rem; text-align: center; }

/* Bottom toolbar */
.be-bottom-bar {
  position: fixed; bottom: 0; left: 0; right: 0; z-index: 300;
  display: flex; align-items: center; justify-content: center;
  gap: .3rem; padding: .45rem .5rem;
  background: var(--be-bar-bg, #2c3e50); color: #fff;
  box-shadow: 0 -2px 8px rgba(0,0,0,.25); flex-wrap: wrap;
}
.be-bottom-bar button {
  padding: .3rem .55rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.25);
  cursor: pointer; font-size: .82rem; background: rgba(255,255,255,.1); color: #fff;
  display: inline-flex; align-items: center; gap: .25rem; white-space: nowrap;
}
.be-bottom-bar button:hover:not(:disabled) { background: rgba(255,255,255,.2); }
.be-bottom-bar button:disabled { opacity: .35; cursor: default; }
.be-bottom-bar .be-bar-count { font-size: .8rem; color: rgba(255,255,255,.7); margin-right: .3rem; }

/* Type picker */
.be-type-picker {
  position: absolute; background: var(--be-card-bg, #fff); border: 1px solid #ccc;
  border-radius: 5px; box-shadow: 0 4px 16px rgba(0,0,0,.18); z-index: 1000; min-width: 160px; padding: .25rem 0;
}
.be-picker-item { display: block; width: 100%; text-align: left; background: none; border: none; padding: .35rem .8rem; cursor: pointer; font-size: .9rem; color: inherit; }
.be-picker-item:hover { background: #eaf4ff; }
.be-picker-subitem { padding-left: 1.4rem; font-size: .85rem; }
.be-picker-sublist { display: none; } .be-picker-sublist-open { display: block; }
.be-picker-group-header { font-weight: bold; }
.be-picker-quick { font-weight: bold; background: rgba(52,152,219,.08) !important; }
.be-picker-sep { height: 1px; background: #ddd; margin: .2rem .6rem; }

/* Quick insert below button */
.be-quick-ins {
  flex-shrink: 0; width: 1.4rem; height: 1.4rem; border-radius: 50%;
  border: 1px solid #ccc; background: none; cursor: pointer;
  font-size: .85rem; line-height: 1; padding: 0; color: #999;
  display: flex; align-items: center; justify-content: center; margin-top: .1rem;
}
.be-quick-ins:hover { border-color: #27ae60; color: #27ae60; background: rgba(39,174,96,.08); }
.be-quick-ins-disabled { opacity: .2; cursor: default; pointer-events: none; }

/* Mobile grip size */
@media (max-width: 700px) {
  .be-grip { font-size: 1.6rem; padding: .4rem .3rem 0; }
  .be-quick-ins { width: 1.9rem; height: 1.9rem; font-size: 1.1rem; }
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
  .be-card { --be-card-bg: #1a1a1a; --be-card-border: #333; }
  .be-card.be-selected { background: rgba(52,152,219,.1); }
  .be-toolbar { --be-toolbar-bg: #111; --be-border: #333; }
  .be-badge { background: #222; border-color: #444; color: #aaa; }
  .be-bottom-bar { --be-bar-bg: #111; }
  .be-type-picker { --be-card-bg: #1a1a1a; border-color: #444; }
  .be-picker-item:hover { background: #1a3a5c; }
  .be-code-area, .be-table-area, .be-raw-area, .be-meta-area { background: #141414; color: #e0e0e0; }
  .be-card textarea { color: #e0e0e0; }
  .be-card textarea:focus, .be-card textarea:hover { --be-input-focus-bg: rgba(52,152,219,.08); }
  .be-sel { border-color: #555; }
  .be-sel:hover { border-color: #8ab4f8; }
  .be-selected .be-sel { border-color: #8ab4f8; background: #8ab4f8; }
}
`;
  document.head.appendChild(style);
}

// ─── APP ──────────────────────────────────────────────────────────────────────

function init() {
  const mountEl = document.getElementById('block-editor-root');
  if (!mountEl) return;
  const pageName = mountEl.dataset.page;
  const sectIdx = mountEl.dataset.sect != null ? parseInt(mountEl.dataset.sect, 10) : null;
  const isSect = sectIdx != null;
  injectStyles();

  const root = document.createElement('div'); root.id = 'be-root'; mountEl.appendChild(root);

  // Top toolbar
  const toolbar = document.createElement('div'); toolbar.className = 'be-toolbar';
  const cancelBtn = document.createElement('a'); cancelBtn.className = 'be-btn'; cancelBtn.href = '/wiki/' + pageName; cancelBtn.textContent = '← Cancel';
  const titleEl = document.createElement('span'); titleEl.className = 'be-toolbar-title';
  titleEl.textContent = isSect ? ('Edit section — ' + pageName) : ('Edit — ' + pageName);
  const undoBtn = document.createElement('button'); undoBtn.className = 'be-undo'; undoBtn.type = 'button'; undoBtn.title = 'Undo (Ctrl+Z)'; undoBtn.textContent = '↩';
  const redoBtn = document.createElement('button'); redoBtn.className = 'be-redo'; redoBtn.type = 'button'; redoBtn.title = 'Redo (Ctrl+Shift+Z)'; redoBtn.textContent = '↷';
  const saveBtn = document.createElement('button'); saveBtn.className = 'be-save'; saveBtn.type = 'button';
  saveBtn.textContent = isSect ? '💾 Save section' : '💾 Save'; saveBtn.disabled = true;
  toolbar.appendChild(cancelBtn); toolbar.appendChild(titleEl); toolbar.appendChild(undoBtn); toolbar.appendChild(redoBtn); toolbar.appendChild(saveBtn);
  root.appendChild(toolbar);

  const loadingEl = document.createElement('div'); loadingEl.className = 'be-loading'; loadingEl.textContent = 'Loading…'; root.appendChild(loadingEl);

  let blocks = [], anchor = '', initialMarkup = '';
  const undo = makeUndoStack(100);
  const cardsEl = document.createElement('div'); cardsEl.id = 'be-cards'; root.appendChild(cardsEl);

  // ── Bottom bar ────────────────────────────────────────────────────────────
  const bar = document.createElement('div'); bar.className = 'be-bottom-bar';
  const barCount = document.createElement('span'); barCount.className = 'be-bar-count'; barCount.textContent = '0 selected';
  const btnInsAbove = document.createElement('button'); btnInsAbove.textContent = '⬆'; btnInsAbove.title = 'Insert above';
  const btnInsBelow = document.createElement('button'); btnInsBelow.textContent = '⬇'; btnInsBelow.title = 'Insert below';
  const btnType = document.createElement('button'); btnType.textContent = '⟳'; btnType.title = 'Change type';
  const btnIndentL = document.createElement('button'); btnIndentL.textContent = '⬅'; btnIndentL.title = 'Outdent';
  const btnIndentR = document.createElement('button'); btnIndentR.textContent = '➡'; btnIndentR.title = 'Indent';
  const btnDel = document.createElement('button'); btnDel.textContent = '🗑'; btnDel.title = 'Delete';
  const btnSelAll = document.createElement('button'); btnSelAll.textContent = '☑'; btnSelAll.title = 'Select all';
  const btnSelNone = document.createElement('button'); btnSelNone.textContent = '☐'; btnSelNone.title = 'Deselect all';
  const btnRestore = document.createElement('button'); btnRestore.textContent = '↺'; btnRestore.title = 'Restore original content (undo all edits this session)';
  bar.appendChild(barCount);
  bar.appendChild(btnInsAbove); bar.appendChild(btnInsBelow);
  bar.appendChild(btnType); bar.appendChild(btnIndentL); bar.appendChild(btnIndentR);
  bar.appendChild(btnDel); bar.appendChild(btnSelAll); bar.appendChild(btnSelNone);
  bar.appendChild(btnRestore);
  document.body.appendChild(bar);

  // ── API ─────────────────────────────────────────────────────────────────────
  const api = {
    onChange: function () { undo.pushDebounced(function () { push_and_sync(); }, 800); },
    pushUndo: function () { push_and_sync(); },
    pushUndoImmediate: function () { push_and_sync(); },
    getSelection: function () { return blocks.filter(function (b) { return b._selected; }); },
    deselectAll: function () { blocks.forEach(function (b) { b._selected = false; }); },
    syncSelection: syncSelection,
    rerender: function () { render(); },
    quickInsertBelow: function (block, type) {
      const idx = blocks.indexOf(block);
      if (idx < 0) return;
      undo.push(blocksToMarkup(blocks));
      const nb = makeDefaultBlock(type);
      if (block.indent != null && nb.indent != null) nb.indent = block.indent;
      api.deselectAll();
      nb._selected = true;
      blocks.splice(idx + 1, 0, nb);
      render(); syncUndoButtons();
      setTimeout(function () {
        const nc = cardsEl.querySelector('[data-id="' + nb._id + '"]');
        if (nc) { const inp = nc.querySelector('textarea'); if (inp) inp.focus(); }
      }, 50);
    },
  };

  function push_and_sync() { undo.push(blocksToMarkup(blocks)); syncUndoButtons(); }

  function syncSelection() {
    const sel = api.getSelection();
    const n = sel.length;
    barCount.textContent = n + ' selected';
    btnInsAbove.disabled = n !== 1;
    btnInsBelow.disabled = n !== 1;
    btnType.disabled = n === 0;
    btnDel.disabled = n === 0;
    const hasIndent = sel.some(function (b) { return b.type === 'todo' || b.type === 'bullet' || b.type === 'ordered'; });
    btnIndentL.disabled = !hasIndent;
    btnIndentR.disabled = !hasIndent;
    // Update card visual state
    cardsEl.querySelectorAll('.be-card').forEach(function (card) {
      const b = blocks.find(function (bl) { return bl._id === card.dataset.id; });
      if (b && b._selected) card.classList.add('be-selected');
      else card.classList.remove('be-selected');
    });
  }

  // ── Bottom bar actions ─────────────────────────────────────────────────────
  function doInsert(above) {
    const sel = api.getSelection();
    if (sel.length !== 1) return;
    const ref = sel[0];
    const idx = blocks.indexOf(ref);
    if (idx < 0) return;
    openTypePicker(above ? btnInsAbove : btnInsBelow, function (type, level) {
      undo.push(blocksToMarkup(blocks));
      const nb = makeDefaultBlock(type, level);
      if (!above && ref.indent != null && nb.indent != null) nb.indent = ref.indent;
      api.deselectAll();
      nb._selected = true;
      blocks.splice(above ? idx : idx + 1, 0, nb);
      render(); syncUndoButtons();
      setTimeout(function () {
        const nc = cardsEl.querySelector('[data-id="' + nb._id + '"]');
        if (nc) { const inp = nc.querySelector('textarea'); if (inp) inp.focus(); }
      }, 50);
    }, ref);
  }
  btnInsAbove.addEventListener('click', function () { doInsert(true); });
  btnInsBelow.addEventListener('click', function () { doInsert(false); });

  btnType.addEventListener('click', function () {
    const sel = api.getSelection();
    if (sel.length === 0) return;
    openTypePicker(btnType, function (type, level) {
      undo.push(blocksToMarkup(blocks));
      sel.forEach(function (block) {
        const idx = blocks.indexOf(block);
        if (idx < 0) return;
        const nb = makeDefaultBlock(type, level); nb._id = block._id; nb._selected = true;
        if ((block.type === 'para' || block.type === 'heading') && nb.type === 'para') nb.lines = (block.lines || [block.text || '']).slice();
        else if ((block.type === 'para' || block.type === 'heading') && nb.type === 'heading') nb.text = block.type === 'heading' ? block.text : (block.lines && block.lines[0]) || '';
        else if (['todo','bullet','ordered'].indexOf(block.type) >= 0 && ['todo','bullet','ordered'].indexOf(nb.type) >= 0) { nb.text = block.text; nb.indent = block.indent; }
        blocks[idx] = nb;
      });
      render(); syncUndoButtons();
    });
  });

  btnDel.addEventListener('click', function () {
    const sel = api.getSelection();
    if (sel.length === 0) return;
    undo.push(blocksToMarkup(blocks));
    const ids = new Set(sel.map(function (b) { return b._id; }));
    blocks = blocks.filter(function (b) { return !ids.has(b._id); });
    render(); syncUndoButtons();
  });

  btnIndentL.addEventListener('click', function () {
    undo.push(blocksToMarkup(blocks));
    api.getSelection().forEach(function (b) { if (b.indent >= 2) b.indent -= 2; });
    render(); syncUndoButtons();
  });
  btnIndentR.addEventListener('click', function () {
    undo.push(blocksToMarkup(blocks));
    api.getSelection().forEach(function (b) { if (b.indent != null) b.indent += 2; });
    render(); syncUndoButtons();
  });

  btnSelAll.addEventListener('click', function () { blocks.forEach(function (b) { b._selected = true; }); syncSelection(); });
  btnSelNone.addEventListener('click', function () { api.deselectAll(); syncSelection(); });
  btnRestore.addEventListener('click', function () {
    if (!confirm('Restore page to the state when you opened this editor?')) return;
    undo.push(blocksToMarkup(blocks));           // checkpoint: pre-restore state
    blocks = markupToBlocks(initialMarkup).map(assignId);
    undo.push(blocksToMarkup(blocks));           // record restored state as current
    render(); syncUndoButtons();
  });

  function render() {
    _rendering = true;
    cardsEl.innerHTML = '';
    _rendering = false;
    blocks.forEach(function (block) { cardsEl.appendChild(renderCard(block, api)); });
    cardsEl.querySelectorAll('textarea').forEach(autoGrow);
    syncSelection();
  }

  function syncUndoButtons() { undoBtn.disabled = !undo.canUndo(); redoBtn.disabled = !undo.canRedo(); }

  undoBtn.addEventListener('click', function () { undo.cancelDebounce(); const m = undo.undo(); if (m !== null) { blocks = markupToBlocks(m).map(assignId); render(); } syncUndoButtons(); });
  redoBtn.addEventListener('click', function () { undo.cancelDebounce(); const m = undo.redo(); if (m !== null) { blocks = markupToBlocks(m).map(assignId); render(); } syncUndoButtons(); });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undoBtn.click(); }
    else if ((e.ctrlKey || e.metaKey) && (e.key === 'Z' || (e.shiftKey && e.key === 'z'))) { e.preventDefault(); redoBtn.click(); }
  });

  saveBtn.addEventListener('click', function () {
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    const markup = blocksToMarkup(blocks);
    const form = document.createElement('form'); form.method = 'post'; form.style.display = 'none';
    if (isSect) {
      form.action = '/sect/' + pageName + '/' + sectIdx;
      const ai = document.createElement('input'); ai.name = 'anchor'; ai.value = anchor; form.appendChild(ai);
    } else { form.action = '/edit/' + pageName; }
    const ci = document.createElement('textarea'); ci.name = 'content'; ci.value = markup; form.appendChild(ci);
    document.body.appendChild(form); form.submit();
  });

  initDragDrop(cardsEl, function () { return blocks; }, function (nb) { blocks = nb; undo.push(blocksToMarkup(blocks)); syncUndoButtons(); });

  const fetchUrl = isSect ? '/raw-sect/' + pageName + '/' + sectIdx : '/raw/' + pageName;
  fetch(fetchUrl, { credentials: 'same-origin' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(function (data) {
      loadingEl.remove(); anchor = data.anchor || '';
      if (isSect && anchor) cancelBtn.href = '/wiki/' + pageName + '#' + anchor;
      initialMarkup = data.content || '';
      blocks = markupToBlocks(initialMarkup).map(assignId);
      undo.push(blocksToMarkup(blocks)); render(); saveBtn.disabled = false; syncUndoButtons();
    })
    .catch(function (err) { loadingEl.remove(); const e = document.createElement('div'); e.className = 'be-error'; e.textContent = 'Load failed: ' + err.message; root.appendChild(e); });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();

})();
