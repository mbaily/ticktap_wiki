/* block_editor.js — TickTap Wiki block editor
 * Vanilla JS, no dependencies, no bundler.
 * Loaded as a cacheable immutable asset via /static/block-editor-{hash}.js
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

    // ── META block ──────────────────────────────────────────────────────────
    if (i === 0 && RE_META_OPEN.test(line)) {
      const raw = [line];
      i++;
      while (i < lines.length) {
        raw.push(lines[i]);
        if (RE_META_CLOSE.test(lines[i])) { i++; break; }
        i++;
      }
      blocks.push({ type: 'meta', raw: raw.join('\n'), lines: raw.slice(1, -1) });
      continue;
    }

    // ── HR ──────────────────────────────────────────────────────────────────
    if (RE_HR.test(line)) {
      blocks.push({ type: 'hr', raw: line });
      i++; continue;
    }

    // ── Code fence ──────────────────────────────────────────────────────────
    const fenceM = line.match(RE_FENCE_OPEN);
    if (fenceM) {
      const lang = fenceM[1].trim();
      const raw = [line];
      const codeLines = [];
      i++;
      while (i < lines.length) {
        raw.push(lines[i]);
        if (RE_FENCE_CLOSE.test(lines[i])) { i++; break; }
        codeLines.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'code', lang, codeLines, raw: raw.join('\n') });
      continue;
    }

    // ── Heading ─────────────────────────────────────────────────────────────
    const hm = line.match(RE_HEADING);
    if (hm) {
      // level: ====== = h1 (6 signs → level 1), == = h5 (2 signs → level 5)
      const level = 7 - hm[1].length;
      blocks.push({ type: 'heading', level, text: hm[2], raw: line });
      i++; continue;
    }

    // ── Todo ────────────────────────────────────────────────────────────────
    const tm = line.match(RE_TODO);
    if (tm) {
      const indent = tm[1].length; // number of leading spaces (multiples of 2)
      blocks.push({ type: 'todo', indent, state: tm[2], text: tm[3], raw: line });
      i++; continue;
    }

    // ── Bullet ──────────────────────────────────────────────────────────────
    const bm = line.match(RE_BULLET);
    if (bm) {
      const indent = bm[1].length - 2; // normalize so 0 = first level
      blocks.push({ type: 'bullet', indent, text: bm[3], raw: line });
      i++; continue;
    }

    // ── Ordered ─────────────────────────────────────────────────────────────
    const om = line.match(RE_ORDERED);
    if (om) {
      const indent = om[1].length - 2;
      blocks.push({ type: 'ordered', indent, text: om[3], raw: line });
      i++; continue;
    }

    // ── Table ───────────────────────────────────────────────────────────────
    if (RE_TABLE_ROW.test(line)) {
      const raw = [line];
      i++;
      while (i < lines.length && RE_TABLE_ROW.test(lines[i])) {
        raw.push(lines[i]);
        i++;
      }
      blocks.push({ type: 'table', raw: raw.join('\n'), rows: raw });
      continue;
    }

    // ── Image-only paragraph ─────────────────────────────────────────────────
    if (RE_IMAGE_ONLY.test(line)) {
      const m = line.trim().match(/^\{\{([^|}]+)(\|([^}]*))?\}\}/);
      const src = m ? m[1].trim() : '';
      const alt = m && m[3] != null ? m[3].trim() : '';
      blocks.push({ type: 'image', src, alt, raw: line });
      i++; continue;
    }

    // ── Blank line(s) ────────────────────────────────────────────────────────
    if (line === '') {
      let count = 0;
      while (i < lines.length && lines[i] === '') { count++; i++; }
      blocks.push({ type: 'blank', count });
      continue;
    }

    // ── Paragraph (one or more non-blank lines not matching the above) ───────
    const paraLines = [line];
    i++;
    while (i < lines.length) {
      const l = lines[i];
      if (l === ''
        || RE_HR.test(l)
        || RE_FENCE_OPEN.test(l)
        || RE_HEADING.test(l)
        || RE_TODO.test(l)
        || RE_BULLET.test(l)
        || RE_ORDERED.test(l)
        || RE_TABLE_ROW.test(l)
        || RE_META_OPEN.test(l)
        || RE_IMAGE_ONLY.test(l)
      ) break;
      paraLines.push(l);
      i++;
    }
    blocks.push({ type: 'para', lines: paraLines, raw: paraLines.join('\n') });
  }

  return blocks;
}

// ─── SERIALIZER ────────────────────────────────────────────────────────────────

function serializeBlock(b) {
  switch (b.type) {
    case 'meta': {
      const inner = b.lines.join('\n');
      return `~~META:\n${inner}\n~~`;
    }
    case 'heading': {
      const eq = '='.repeat(7 - b.level);
      return `${eq} ${b.text} ${eq}`;
    }
    case 'para':
      return b.lines.join('\n');
    case 'todo': {
      const pad = ' '.repeat(b.indent);
      return `${pad}[${b.state}] ${b.text}`;
    }
    case 'bullet': {
      const pad = ' '.repeat(b.indent + 2);
      return `${pad}* ${b.text}`;
    }
    case 'ordered': {
      const pad = ' '.repeat(b.indent + 2);
      return `${pad}- ${b.text}`;
    }
    case 'hr':
      return '----';
    case 'code': {
      const fence = `\`\`\`${b.lang}`;
      return `${fence}\n${b.codeLines.join('\n')}\n\`\`\``;
    }
    case 'table':
      return b.rows.join('\n');
    case 'image': {
      const alt = b.alt ? `|${b.alt}` : '';
      return `{{${b.src}${alt}}}`;
    }
    case 'blank':
      return '\n'.repeat(b.count - 1); // join('\n') will add the first \n
    case 'raw':
      return b.raw;
    default:
      return b.raw || '';
  }
}

function blocksToMarkup(blocks) {
  return blocks.map(serializeBlock).join('\n');
}

// ─── UNDO STACK ────────────────────────────────────────────────────────────────

function makeUndoStack(maxSize) {
  maxSize = maxSize || 100;
  let stack = [];
  let pos = -1;       // index of current state
  let debounceTimer = null;

  function push(markup) {
    // Discard redo branch
    stack = stack.slice(0, pos + 1);
    stack.push(markup);
    if (stack.length > maxSize) stack.shift();
    pos = stack.length - 1;
  }

  function current() {
    return pos >= 0 ? stack[pos] : null;
  }

  function undo() {
    if (pos > 0) { pos--; return stack[pos]; }
    return null;
  }

  function redo() {
    if (pos < stack.length - 1) { pos++; return stack[pos]; }
    return null;
  }

  function pushDebounced(getMarkup, delay) {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function () {
      push(getMarkup());
    }, delay || 800);
  }

  return { push, current, undo, redo, pushDebounced };
}

// ─── DRAG & DROP (mouse + touch) ───────────────────────────────────────────────

function initDragDrop(container, getBlocks, onReorder) {
  let dragSrc = null;
  let touchClone = null;
  let touchSrcEl = null;
  let placeholder = null;

  // ── Mouse drag ──────────────────────────────────────────────────────────────
  container.addEventListener('dragstart', function (e) {
    const card = e.target.closest('.be-card');
    if (!card) return;
    const handle = e.target.closest('.be-grip');
    if (!handle) { e.preventDefault(); return; }
    dragSrc = card;
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(function () { dragSrc.classList.add('be-dragging'); }, 0);
  });

  container.addEventListener('dragend', function () {
    if (dragSrc) { dragSrc.classList.remove('be-dragging'); dragSrc = null; }
    container.querySelectorAll('.be-drag-over').forEach(function (el) {
      el.classList.remove('be-drag-over-before', 'be-drag-over-after', 'be-drag-over');
    });
    if (placeholder) { placeholder.remove(); placeholder = null; }
  });

  container.addEventListener('dragover', function (e) {
    if (!dragSrc) return;
    const card = e.target.closest('.be-card');
    if (!card || card === dragSrc) return;
    e.preventDefault();
    container.querySelectorAll('.be-drag-over-before,.be-drag-over-after').forEach(function (el) {
      el.classList.remove('be-drag-over-before', 'be-drag-over-after');
    });
    const rect = card.getBoundingClientRect();
    card.classList.add(e.clientY < rect.top + rect.height / 2 ? 'be-drag-over-before' : 'be-drag-over-after');
  });

  container.addEventListener('drop', function (e) {
    if (!dragSrc) return;
    const card = e.target.closest('.be-card');
    container.querySelectorAll('.be-drag-over-before,.be-drag-over-after').forEach(function (el) {
      el.classList.remove('be-drag-over-before', 'be-drag-over-after');
    });
    if (!card || card === dragSrc) return;
    e.preventDefault();
    const rect = card.getBoundingClientRect();
    if (e.clientY < rect.top + rect.height / 2) {
      container.insertBefore(dragSrc, card);
    } else {
      card.after(dragSrc);
    }
    _syncBlocksFromDOM(getBlocks, container, onReorder);
  });

  // ── Touch drag ──────────────────────────────────────────────────────────────
  container.addEventListener('touchstart', function (e) {
    const handle = e.target.closest('.be-grip');
    if (!handle) return;
    touchSrcEl = handle.closest('.be-card');
    if (!touchSrcEl) return;

    const t = e.touches[0];
    touchClone = touchSrcEl.cloneNode(true);
    touchClone.style.cssText = `position:fixed;z-index:9999;opacity:0.8;pointer-events:none;` +
      `width:${touchSrcEl.offsetWidth}px;left:${t.clientX - 20}px;top:${t.clientY - 20}px;`;
    document.body.appendChild(touchClone);
    touchSrcEl.classList.add('be-dragging');

    placeholder = document.createElement('div');
    placeholder.className = 'be-placeholder';
    placeholder.style.height = touchSrcEl.offsetHeight + 'px';
    touchSrcEl.after(placeholder);
  }, { passive: true });

  container.addEventListener('touchmove', function (e) {
    if (!touchSrcEl || !touchClone) return;
    e.preventDefault();
    const t = e.touches[0];
    touchClone.style.left = (t.clientX - 20) + 'px';
    touchClone.style.top  = (t.clientY - 20) + 'px';

    // Hit-test
    touchClone.style.display = 'none';
    const el = document.elementFromPoint(t.clientX, t.clientY);
    touchClone.style.display = '';
    const card = el && el.closest('.be-card');
    if (card && card !== touchSrcEl) {
      const rect = card.getBoundingClientRect();
      if (t.clientY < rect.top + rect.height / 2) {
        card.before(placeholder);
      } else {
        card.after(placeholder);
      }
    }
  }, { passive: false });

  container.addEventListener('touchend', function () {
    if (!touchSrcEl) return;
    if (placeholder) {
      placeholder.replaceWith(touchSrcEl);
      placeholder = null;
    }
    touchSrcEl.classList.remove('be-dragging');
    if (touchClone) { touchClone.remove(); touchClone = null; }
    touchSrcEl = null;
    _syncBlocksFromDOM(getBlocks, container, onReorder);
  });
}

function _syncBlocksFromDOM(getBlocks, container, onReorder) {
  const cards = Array.from(container.querySelectorAll('.be-card'));
  const oldBlocks = getBlocks();
  const newBlocks = cards.map(function (c) {
    return oldBlocks.find(function (b) { return b._id === c.dataset.id; });
  }).filter(Boolean);
  onReorder(newBlocks);
}

// ─── BLOCK ID COUNTER ──────────────────────────────────────────────────────────
let _nextId = 0;
function assignId(b) {
  if (!b._id) b._id = 'b' + (_nextId++);
  return b;
}

// ─── CARD RENDERING ────────────────────────────────────────────────────────────

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderCard(block, api) {
  const card = document.createElement('div');
  card.className = 'be-card';
  card.dataset.id = block._id;
  card.draggable = true;

  // Grip
  const grip = document.createElement('span');
  grip.className = 'be-grip';
  grip.title = 'Drag to reorder';
  grip.innerHTML = '&#8942;&#8942;'; // ⠿ approximation
  grip.setAttribute('draggable', 'true');
  card.appendChild(grip);

  // Content area
  const content = document.createElement('div');
  content.className = 'be-content';
  card.appendChild(content);

  // Right side: type badge + delete
  const right = document.createElement('div');
  right.className = 'be-right';

  const badge = document.createElement('span');
  badge.className = 'be-badge';
  badge.textContent = badgeLabel(block);
  badge.title = 'Change block type';
  badge.addEventListener('click', function (e) {
    e.stopPropagation();
    api.openTypePicker(block, card, badge);
  });
  right.appendChild(badge);

  const del = document.createElement('button');
  del.className = 'be-del';
  del.title = 'Delete block';
  del.textContent = '×';
  del.addEventListener('click', function () {
    api.deleteBlock(block);
  });
  right.appendChild(del);
  card.appendChild(right);

  fillContent(block, content, api);
  return card;
}

function badgeLabel(b) {
  switch (b.type) {
    case 'heading': return 'h' + b.level;
    case 'para':    return 'p';
    case 'todo':    return '☐';
    case 'bullet':  return '•';
    case 'ordered': return '1.';
    case 'hr':      return '—';
    case 'code':    return '</>';
    case 'table':   return '⊞';
    case 'image':   return '🖼';
    case 'meta':    return 'meta';
    case 'blank':   return '⏎';
    case 'raw':     return 'raw';
    default:        return '?';
  }
}

function fillContent(block, content, api) {
  content.innerHTML = '';
  switch (block.type) {

    case 'heading': {
      const inp = makeInput(block.text, function (v) {
        block.text = v;
        api.onChange();
      }, api);
      inp.className = 'be-heading-input be-h' + block.level;
      inp.placeholder = 'Heading text…';
      content.appendChild(inp);
      break;
    }

    case 'para': {
      block.lines.forEach(function (ln, idx) {
        content.appendChild(makeParaLine(block, idx, content, api));
      });
      break;
    }

    case 'todo': {
      const row = document.createElement('div');
      row.className = 'be-row';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.className = 'be-todo-cb';
      cb.checked = block.state === 'x';
      cb.indeterminate = block.state === '~';
      cb.addEventListener('click', function (e) {
        e.preventDefault();
        const states = ['  ', ' x', ' ~'];  // space used in display
        // cycle: ' ' → 'x' → '~' → ' '
        const cur = block.state;
        block.state = cur === ' ' ? 'x' : (cur === 'x' ? '~' : ' ');
        cb.checked = block.state === 'x';
        cb.indeterminate = block.state === '~';
        api.onChange();
        api.pushUndo();
      });
      row.appendChild(cb);

      const inp = makeInput(block.text, function (v) {
        block.text = v;
        api.onChange();
      }, api);
      inp.className = 'be-list-input';
      inp.placeholder = 'Todo text…';
      if (block.indent > 0) inp.style.paddingLeft = (block.indent * 0.75) + 'em';
      row.appendChild(inp);

      row.appendChild(makeIndentButtons(block, content, api));
      content.appendChild(row);
      break;
    }

    case 'bullet':
    case 'ordered': {
      const row = document.createElement('div');
      row.className = 'be-row';

      const bullet = document.createElement('span');
      bullet.className = 'be-list-marker';
      bullet.textContent = block.type === 'bullet' ? '•' : '–';
      if (block.indent > 0) bullet.style.paddingLeft = (block.indent * 0.75) + 'em';
      row.appendChild(bullet);

      const inp = makeInput(block.text, function (v) {
        block.text = v;
        api.onChange();
      }, api);
      inp.className = 'be-list-input';
      inp.placeholder = block.type === 'bullet' ? 'Bullet item…' : 'Ordered item…';
      row.appendChild(inp);

      row.appendChild(makeIndentButtons(block, content, api));
      content.appendChild(row);
      break;
    }

    case 'hr': {
      const hr = document.createElement('div');
      hr.className = 'be-hr-preview';
      hr.textContent = '— Horizontal rule —';
      content.appendChild(hr);
      break;
    }

    case 'code': {
      const langRow = document.createElement('div');
      langRow.className = 'be-row';
      const langLabel = document.createElement('span');
      langLabel.className = 'be-code-lang-label';
      langLabel.textContent = 'Language:';
      const langInp = document.createElement('input');
      langInp.type = 'text';
      langInp.className = 'be-code-lang';
      langInp.value = block.lang;
      langInp.placeholder = '(none)';
      langInp.addEventListener('input', function () {
        block.lang = langInp.value;
        api.onChange();
      });
      langInp.addEventListener('blur', function () { api.pushUndo(); });
      langRow.appendChild(langLabel);
      langRow.appendChild(langInp);
      content.appendChild(langRow);

      const ta = document.createElement('textarea');
      ta.className = 'be-code-area';
      ta.value = block.codeLines.join('\n');
      ta.rows = Math.max(3, block.codeLines.length + 1);
      ta.spellcheck = false;
      ta.addEventListener('input', function () {
        block.codeLines = ta.value.split('\n');
        autoGrow(ta);
        api.onChange();
      });
      ta.addEventListener('blur', function () { api.pushUndo(); });
      content.appendChild(ta);
      break;
    }

    case 'table': {
      const ta = document.createElement('textarea');
      ta.className = 'be-table-area';
      ta.value = block.rows.join('\n');
      ta.rows = Math.max(3, block.rows.length + 1);
      ta.spellcheck = false;
      ta.addEventListener('input', function () {
        block.rows = ta.value.split('\n');
        autoGrow(ta);
        api.onChange();
      });
      ta.addEventListener('blur', function () { api.pushUndo(); });
      content.appendChild(ta);
      break;
    }

    case 'image': {
      const srcRow = document.createElement('div');
      srcRow.className = 'be-row';
      const srcLabel = document.createElement('span');
      srcLabel.className = 'be-img-label';
      srcLabel.textContent = '🖼';
      const srcInp = document.createElement('input');
      srcInp.type = 'text';
      srcInp.className = 'be-img-src';
      srcInp.value = block.src;
      srcInp.placeholder = 'image.png or ns:img.png';
      const altInp = document.createElement('input');
      altInp.type = 'text';
      altInp.className = 'be-img-alt';
      altInp.value = block.alt;
      altInp.placeholder = 'Alt text';
      srcInp.addEventListener('input', function () { block.src = srcInp.value; api.onChange(); });
      srcInp.addEventListener('blur', function () { api.pushUndo(); });
      altInp.addEventListener('input', function () { block.alt = altInp.value; api.onChange(); });
      altInp.addEventListener('blur', function () { api.pushUndo(); });
      srcRow.appendChild(srcLabel);
      srcRow.appendChild(srcInp);
      srcRow.appendChild(altInp);
      content.appendChild(srcRow);
      break;
    }

    case 'meta': {
      const ta = document.createElement('textarea');
      ta.className = 'be-meta-area';
      ta.value = block.lines.join('\n');
      ta.rows = Math.max(2, block.lines.length + 1);
      ta.spellcheck = false;
      ta.addEventListener('input', function () {
        block.lines = ta.value.split('\n');
        autoGrow(ta);
        api.onChange();
      });
      ta.addEventListener('blur', function () { api.pushUndo(); });
      content.appendChild(ta);
      break;
    }

    case 'blank': {
      const sp = document.createElement('div');
      sp.className = 'be-blank-spacer';
      sp.textContent = '(blank line' + (block.count > 1 ? 's ×' + block.count : '') + ')';
      content.appendChild(sp);
      break;
    }

    case 'raw':
    default: {
      const ta = document.createElement('textarea');
      ta.className = 'be-raw-area';
      ta.value = block.raw || '';
      ta.rows = Math.max(2, (block.raw || '').split('\n').length + 1);
      ta.spellcheck = false;
      ta.addEventListener('input', function () {
        block.raw = ta.value;
        autoGrow(ta);
        api.onChange();
      });
      ta.addEventListener('blur', function () { api.pushUndo(); });
      content.appendChild(ta);
      break;
    }
  }
}

// ── Paragraph per-line inputs ────────────────────────────────────────────────

function makeParaLine(block, idx, content, api) {
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'be-para-line';
  inp.value = block.lines[idx];
  inp.placeholder = idx === 0 ? 'Paragraph text…' : '';

  inp.addEventListener('input', function () {
    block.lines[idx] = inp.value;
    api.onChange();
  });

  inp.addEventListener('blur', function () { api.pushUndo(); });

  inp.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      block.lines.splice(idx + 1, 0, '');
      // Re-render the paragraph content area
      const newLine = makeParaLine(block, idx + 1, content, api);
      inp.after(newLine);
      // Re-index all siblings
      _reindexParaLines(block, content, api);
      newLine.focus();
      api.onChange();
      api.pushUndoImmediate();
    } else if (e.key === 'Backspace' && inp.selectionStart === 0 && inp.selectionEnd === 0) {
      if (block.lines.length > 1) {
        // merge with previous line
        const prevInp = inp.previousSibling;
        block.lines.splice(idx, 1);
        _reindexParaLines(block, content, api);
        if (prevInp && prevInp.tagName === 'INPUT') {
          prevInp.focus();
          const len = prevInp.value.length;
          prevInp.setSelectionRange(len, len);
        }
        api.onChange();
        api.pushUndoImmediate();
      }
    }
  });

  return inp;
}

function _reindexParaLines(block, content, api) {
  const inputs = Array.from(content.querySelectorAll('.be-para-line'));
  inputs.forEach(function (inp, i) {
    // Replace event listeners by replacing with a fresh element
    const newInp = makeParaLine(block, i, content, api);
    newInp.value = block.lines[i];
    inp.replaceWith(newInp);
  });
}

// ── Generic single-line input ────────────────────────────────────────────────

function makeInput(initialValue, onChange, api) {
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.value = initialValue;
  inp.addEventListener('input', function () { onChange(inp.value); });
  inp.addEventListener('blur', function () { api.pushUndo(); });
  return inp;
}

// ── Indent buttons ────────────────────────────────────────────────────────────

function makeIndentButtons(block, content, api) {
  const wrap = document.createElement('span');
  wrap.className = 'be-indent-btns';

  const out = document.createElement('button');
  out.type = 'button';
  out.className = 'be-indent-btn';
  out.title = 'Outdent';
  out.textContent = '⬅';
  out.addEventListener('click', function () {
    if (block.indent >= 2) {
      block.indent -= 2;
      api.onChange();
      api.pushUndoImmediate();
      api.rerender();
    }
  });

  const inn = document.createElement('button');
  inn.type = 'button';
  inn.className = 'be-indent-btn';
  inn.title = 'Indent';
  inn.textContent = '➡';
  inn.addEventListener('click', function () {
    block.indent += 2;
    api.onChange();
    api.pushUndoImmediate();
    api.rerender();
  });

  wrap.appendChild(out);
  wrap.appendChild(inn);
  return wrap;
}

function autoGrow(ta) {
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
}

// ─── TYPE PICKER ───────────────────────────────────────────────────────────────

const TYPE_PICKER_ITEMS = [
  { type: 'para',    label: '¶ Paragraph' },
  { type: 'heading', label: 'H Heading', sub: [
    { level: 1, label: 'H1 ====== ======' },
    { level: 2, label: 'H2 ===== =====' },
    { level: 3, label: 'H3 ==== ====' },
    { level: 4, label: 'H4 === ===' },
    { level: 5, label: 'H5 == ==' },
  ]},
  { type: 'todo',    label: '☐ Todo' },
  { type: 'bullet',  label: '• Bullet' },
  { type: 'ordered', label: '1. Ordered' },
  { type: 'code',    label: '</> Code block' },
  { type: 'table',   label: '⊞ Table' },
  { type: 'hr',      label: '— Horizontal rule' },
  { type: 'image',   label: '🖼 Image' },
  { type: 'blank',   label: '⏎ Blank line' },
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

function openTypePicker(block, anchorEl, afterChoose) {
  // Remove any existing picker
  document.querySelectorAll('.be-type-picker').forEach(function (el) { el.remove(); });

  const picker = document.createElement('div');
  picker.className = 'be-type-picker';

  TYPE_PICKER_ITEMS.forEach(function (item) {
    if (item.sub) {
      const groupEl = document.createElement('div');
      groupEl.className = 'be-picker-group';
      const groupBtn = document.createElement('button');
      groupBtn.className = 'be-picker-item be-picker-group-header';
      groupBtn.textContent = item.label;
      groupEl.appendChild(groupBtn);
      const subList = document.createElement('div');
      subList.className = 'be-picker-sublist';
      item.sub.forEach(function (sub) {
        const subBtn = document.createElement('button');
        subBtn.className = 'be-picker-item be-picker-subitem';
        subBtn.textContent = sub.label;
        subBtn.addEventListener('click', function () {
          picker.remove();
          afterChoose(item.type, sub.level);
        });
        subList.appendChild(subBtn);
      });
      groupBtn.addEventListener('click', function () {
        subList.classList.toggle('be-picker-sublist-open');
      });
      groupEl.appendChild(subList);
      picker.appendChild(groupEl);
    } else {
      const btn = document.createElement('button');
      btn.className = 'be-picker-item';
      btn.textContent = item.label;
      btn.addEventListener('click', function () {
        picker.remove();
        afterChoose(item.type, null);
      });
      picker.appendChild(btn);
    }
  });

  // Position near anchor
  document.body.appendChild(picker);
  const rect = anchorEl.getBoundingClientRect();
  const pickerH = picker.offsetHeight;
  const spaceBelow = window.innerHeight - rect.bottom;
  if (spaceBelow < pickerH && rect.top > pickerH) {
    picker.style.top = (rect.top + window.scrollY - pickerH) + 'px';
  } else {
    picker.style.top = (rect.bottom + window.scrollY) + 'px';
  }
  const pickerW = picker.offsetWidth;
  let left = rect.left + window.scrollX;
  if (left + pickerW > window.innerWidth) left = window.innerWidth - pickerW - 8;
  picker.style.left = Math.max(4, left) + 'px';

  // Close on outside click
  setTimeout(function () {
    document.addEventListener('click', function closePicker(e) {
      if (!picker.contains(e.target)) {
        picker.remove();
        document.removeEventListener('click', closePicker);
      }
    });
  }, 0);
}

// ─── INSERT HANDLE ─────────────────────────────────────────────────────────────

function makeInsertHandle(insertFn) {
  const wrap = document.createElement('div');
  wrap.className = 'be-insert-handle';

  const btn = document.createElement('button');
  btn.className = 'be-insert-btn';
  btn.type = 'button';
  btn.title = 'Insert block here';
  btn.textContent = '+';
  btn.addEventListener('click', function () {
    openTypePicker(btn, btn, function (type, level) {
      insertFn(type, level);
    });
  });

  wrap.appendChild(btn);
  return wrap;
}

// ─── STYLES ───────────────────────────────────────────────────────────────────

function injectStyles() {
  if (document.getElementById('be-styles')) return;
  const style = document.createElement('style');
  style.id = 'be-styles';
  style.textContent = `
/* Block Editor Styles */
#be-root {
  max-width: 860px;
  margin: 0 auto;
  padding: 0 4px 120px;
  font-family: inherit;
}
.be-toolbar {
  position: sticky;
  top: 0;
  z-index: 200;
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: .5rem .75rem;
  background: var(--be-toolbar-bg, #ecf0f1);
  border-bottom: 1px solid var(--be-border, #ccc);
  flex-wrap: wrap;
}
.be-toolbar-title {
  font-weight: bold;
  font-size: .95rem;
  margin-right: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 40vw;
}
.be-toolbar button, .be-toolbar a.be-btn {
  padding: .3rem .65rem;
  border-radius: 4px;
  border: 1px solid #aaa;
  cursor: pointer;
  font-size: .85rem;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: .3rem;
}
.be-toolbar button.be-save {
  background: #27ae60;
  color: #fff;
  border-color: #1e8449;
  font-weight: bold;
}
.be-toolbar button.be-save:disabled { opacity: .5; cursor: default; }
.be-toolbar button.be-undo,
.be-toolbar button.be-redo { background: none; }
.be-loading {
  text-align: center;
  padding: 3rem;
  color: #888;
  font-style: italic;
}
.be-error {
  background: #fdecea;
  border: 1px solid #e74c3c;
  color: #922b21;
  border-radius: 4px;
  padding: .6rem 1rem;
  margin: 1rem 0;
}

/* Cards */
.be-insert-handle {
  text-align: center;
  height: 1.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity .15s;
}
.be-insert-handle:hover, #be-cards:hover .be-insert-handle { opacity: 1; }
.be-insert-btn {
  background: none;
  border: 1px dashed #aaa;
  border-radius: 12px;
  padding: 0 .8rem;
  cursor: pointer;
  font-size: .8rem;
  color: #888;
  height: 1.2rem;
  line-height: 1;
}
.be-insert-btn:hover { background: #eaf4ff; color: #2980b9; border-color: #2980b9; }

.be-card {
  display: flex;
  align-items: flex-start;
  gap: .4rem;
  background: var(--be-card-bg, #fff);
  border: 1px solid var(--be-card-border, #e0e0e0);
  border-radius: 5px;
  padding: .35rem .4rem;
  margin: 2px 0;
  transition: box-shadow .1s;
  min-height: 2rem;
}
.be-card:hover { box-shadow: 0 1px 4px rgba(0,0,0,.12); }
.be-card.be-dragging { opacity: .4; }
.be-card.be-drag-over-before { border-top: 2px solid #3498db; }
.be-card.be-drag-over-after  { border-bottom: 2px solid #3498db; }
.be-placeholder { border: 2px dashed #3498db; border-radius: 5px; background: rgba(52,152,219,.05); }

.be-grip {
  cursor: grab;
  color: #bbb;
  font-size: .8rem;
  line-height: 1;
  padding: .25rem .1rem 0;
  user-select: none;
  flex-shrink: 0;
}
.be-grip:active { cursor: grabbing; }

.be-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: .25rem; }
.be-row { display: flex; align-items: center; gap: .4rem; }

.be-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: .2rem;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity .15s;
}
.be-card:hover .be-right, .be-card:focus-within .be-right { opacity: 1; }
.be-badge {
  font-size: .7rem;
  background: #ecf0f1;
  border: 1px solid #ccc;
  border-radius: 3px;
  padding: .1rem .3rem;
  cursor: pointer;
  white-space: nowrap;
  color: #555;
}
.be-badge:hover { background: #d6eaf8; border-color: #2980b9; color: #1a5276; }
.be-del {
  background: none;
  border: none;
  cursor: pointer;
  color: #bbb;
  font-size: 1rem;
  line-height: 1;
  padding: 0 .1rem;
}
.be-del:hover { color: #e74c3c; }

/* Inputs */
.be-card input[type=text], .be-card textarea {
  border: 1px solid transparent;
  border-radius: 3px;
  background: transparent;
  font-family: inherit;
  font-size: 1rem;
  padding: .15rem .3rem;
  width: 100%;
  box-sizing: border-box;
  transition: border-color .1s, background .1s;
  color: inherit;
}
.be-card input[type=text]:hover,
.be-card input[type=text]:focus,
.be-card textarea:hover,
.be-card textarea:focus {
  border-color: #3498db;
  background: var(--be-input-focus-bg, rgba(52,152,219,.05));
  outline: none;
}
.be-heading-input { font-weight: bold; }
.be-h1 { font-size: 1.5rem; }
.be-h2 { font-size: 1.3rem; }
.be-h3 { font-size: 1.15rem; }
.be-h4 { font-size: 1.05rem; }
.be-h5 { font-size: .95rem; }
.be-para-line { font-size: 1rem; }
.be-list-input { flex: 1; }
.be-list-marker { font-size: 1rem; color: #888; padding: 0 .2rem; flex-shrink: 0; }
.be-indent-btns { display: flex; gap: .2rem; flex-shrink: 0; }
.be-indent-btn {
  background: none; border: 1px solid #ddd; border-radius: 3px;
  cursor: pointer; font-size: .7rem; padding: .1rem .3rem; color: #888;
}
.be-indent-btn:hover { background: #eee; color: #333; }
.be-todo-cb { flex-shrink: 0; cursor: pointer; }

.be-code-lang-label { font-size: .75rem; color: #888; white-space: nowrap; }
.be-code-lang { max-width: 120px; font-size: .85rem; }
.be-code-area, .be-table-area, .be-raw-area, .be-meta-area {
  font-family: monospace;
  font-size: .85rem;
  resize: vertical;
  min-height: 3rem;
  overflow: hidden;
}
.be-img-src { flex: 2; }
.be-img-alt { flex: 1; }
.be-img-label { flex-shrink: 0; }
.be-hr-preview { color: #aaa; font-style: italic; font-size: .85rem; padding: .2rem .3rem; }
.be-blank-spacer {
  color: #ccc;
  font-style: italic;
  font-size: .75rem;
  padding: .1rem .3rem;
  text-align: center;
}

/* Type picker */
.be-type-picker {
  position: absolute;
  background: var(--be-card-bg, #fff);
  border: 1px solid #ccc;
  border-radius: 5px;
  box-shadow: 0 4px 16px rgba(0,0,0,.18);
  z-index: 1000;
  min-width: 180px;
  padding: .25rem 0;
}
.be-picker-item {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: .35rem .8rem;
  cursor: pointer;
  font-size: .9rem;
  color: inherit;
}
.be-picker-item:hover { background: #eaf4ff; }
.be-picker-subitem { padding-left: 1.4rem; font-size: .85rem; }
.be-picker-sublist { display: none; }
.be-picker-sublist-open { display: block; }
.be-picker-group-header { font-weight: bold; }

/* Dark mode overrides — injected alongside the wiki's existing dark CSS */
@media (prefers-color-scheme: dark) {
  .be-card { --be-card-bg: #1a1a1a; --be-card-border: #333; }
  .be-toolbar { --be-toolbar-bg: #111; --be-border: #333; }
  .be-badge { background: #222; border-color: #444; color: #aaa; }
  .be-badge:hover { background: #1a3a5c; border-color: #4a8cc4; color: #8ab4f8; }
  .be-type-picker { --be-card-bg: #1a1a1a; border-color: #444; }
  .be-picker-item:hover { background: #1a3a5c; }
  .be-insert-btn:hover { background: #1a3a5c; color: #8ab4f8; border-color: #4a8cc4; }
  .be-code-area, .be-table-area, .be-raw-area, .be-meta-area { background: #141414; color: #e0e0e0; }
  .be-card input[type=text] { color: #e0e0e0; }
  .be-card input[type=text]:focus, .be-card input[type=text]:hover {
    --be-input-focus-bg: rgba(52,152,219,.08);
  }
}
`;
  document.head.appendChild(style);
}

// ─── APP ──────────────────────────────────────────────────────────────────────

function init() {
  const mountEl = document.getElementById('block-editor-root');
  if (!mountEl) return;

  const pageName = mountEl.dataset.page;
  const sectIdx  = mountEl.dataset.sect != null ? parseInt(mountEl.dataset.sect, 10) : null;
  const isSect   = sectIdx != null;

  injectStyles();

  // Build the shell
  const root = document.createElement('div');
  root.id = 'be-root';
  mountEl.appendChild(root);

  // Toolbar
  const toolbar = document.createElement('div');
  toolbar.className = 'be-toolbar';

  const cancelHref = '/wiki/' + pageName;  // anchor added after load for section mode
  const cancelBtn = document.createElement('a');
  cancelBtn.className = 'be-btn';
  cancelBtn.href = cancelHref;
  cancelBtn.textContent = '← Cancel';

  const titleEl = document.createElement('span');
  titleEl.className = 'be-toolbar-title';
  titleEl.textContent = isSect ? ('Edit section — ' + pageName) : ('Edit — ' + pageName);

  const undoBtn = document.createElement('button');
  undoBtn.className = 'be-undo';
  undoBtn.type = 'button';
  undoBtn.title = 'Undo (Ctrl+Z)';
  undoBtn.textContent = '↩ Undo';

  const redoBtn = document.createElement('button');
  redoBtn.className = 'be-redo';
  redoBtn.type = 'button';
  redoBtn.title = 'Redo (Ctrl+Shift+Z)';
  redoBtn.textContent = '↷ Redo';

  const saveBtn = document.createElement('button');
  saveBtn.className = 'be-save';
  saveBtn.type = 'button';
  saveBtn.textContent = isSect ? '💾 Save section' : '💾 Save';
  saveBtn.disabled = true;

  toolbar.appendChild(cancelBtn);
  toolbar.appendChild(titleEl);
  toolbar.appendChild(undoBtn);
  toolbar.appendChild(redoBtn);
  toolbar.appendChild(saveBtn);
  root.appendChild(toolbar);

  // Loading indicator
  const loadingEl = document.createElement('div');
  loadingEl.className = 'be-loading';
  loadingEl.textContent = 'Loading…';
  root.appendChild(loadingEl);

  // State
  let blocks = [];
  let anchor = '';
  const undo = makeUndoStack(100);

  // Cards container
  const cardsEl = document.createElement('div');
  cardsEl.id = 'be-cards';
  root.appendChild(cardsEl);

  // ── API object passed to card renderers ────────────────────────────────────
  const api = {
    onChange: function () {
      undo.pushDebounced(function () { return blocksToMarkup(blocks); }, 800);
    },
    pushUndo: function () {
      undo.push(blocksToMarkup(blocks));
      syncUndoButtons();
    },
    pushUndoImmediate: function () {
      undo.push(blocksToMarkup(blocks));
      syncUndoButtons();
    },
    deleteBlock: function (block) {
      undo.push(blocksToMarkup(blocks));
      blocks = blocks.filter(function (b) { return b._id !== block._id; });
      render();
      syncUndoButtons();
    },
    openTypePicker: function (block, anchorEl, badgeEl) {
      openTypePicker(block, badgeEl, function (type, level) {
        undo.push(blocksToMarkup(blocks));
        // Mutate the block in-place
        const idx = blocks.indexOf(block);
        if (idx < 0) return;
        const newBlock = makeDefaultBlock(type, level);
        newBlock._id = block._id; // keep same id so the card slot is replaced
        // preserve text if applicable
        if ((block.type === 'para' || block.type === 'heading') && newBlock.type === 'para') {
          newBlock.lines = (block.lines || [block.text || '']).slice();
        } else if (block.type === 'para' && newBlock.type === 'heading') {
          newBlock.text = (block.lines && block.lines[0]) || '';
        } else if ((block.type === 'todo' || block.type === 'bullet' || block.type === 'ordered') &&
                   (newBlock.type === 'todo' || newBlock.type === 'bullet' || newBlock.type === 'ordered')) {
          newBlock.text = block.text;
          newBlock.indent = block.indent;
        }
        blocks[idx] = newBlock;
        render();
        syncUndoButtons();
      });
    },
    rerender: function () { render(); },
    getBlocks: function () { return blocks; },
  };

  function render() {
    cardsEl.innerHTML = '';

    function insertHandle(insertIdx) {
      return makeInsertHandle(function (type, level) {
        undo.push(blocksToMarkup(blocks));
        const nb = makeDefaultBlock(type, level);
        blocks.splice(insertIdx, 0, nb);
        render();
        syncUndoButtons();
        // Focus first input in new card
        setTimeout(function () {
          const newCard = cardsEl.querySelector('[data-id="' + nb._id + '"]');
          if (newCard) {
            const inp = newCard.querySelector('input[type=text],textarea');
            if (inp) inp.focus();
          }
        }, 50);
      });
    }

    cardsEl.appendChild(insertHandle(0));

    blocks.forEach(function (block, idx) {
      const card = renderCard(block, api);
      cardsEl.appendChild(card);
      cardsEl.appendChild(insertHandle(idx + 1));
    });

    // Grow textareas
    cardsEl.querySelectorAll('textarea').forEach(autoGrow);
  }

  function syncUndoButtons() {
    undoBtn.disabled = undo.current() === null;
    redoBtn.disabled = false; // will no-op if nothing to redo
  }

  // ── Undo/Redo ────────────────────────────────────────────────────────────────
  undoBtn.addEventListener('click', function () {
    const markup = undo.undo();
    if (markup !== null) {
      blocks = markupToBlocks(markup).map(assignId);
      render();
    }
    syncUndoButtons();
  });
  redoBtn.addEventListener('click', function () {
    const markup = undo.redo();
    if (markup !== null) {
      blocks = markupToBlocks(markup).map(assignId);
      render();
    }
    syncUndoButtons();
  });
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      undoBtn.click();
    } else if ((e.ctrlKey || e.metaKey) && (e.key === 'Z' || (e.shiftKey && e.key === 'z'))) {
      e.preventDefault();
      redoBtn.click();
    }
  });

  // ── Save ────────────────────────────────────────────────────────────────────
  saveBtn.addEventListener('click', function () {
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving…';
    const markup = blocksToMarkup(blocks);
    const form = document.createElement('form');
    form.method = 'post';
    form.style.display = 'none';

    if (isSect) {
      form.action = '/sect/' + pageName + '/' + sectIdx;
      const anchorInput = document.createElement('input');
      anchorInput.name = 'anchor';
      anchorInput.value = anchor;
      form.appendChild(anchorInput);
    } else {
      form.action = '/edit/' + pageName;
    }

    const contentInput = document.createElement('textarea');
    contentInput.name = 'content';
    contentInput.value = markup;
    form.appendChild(contentInput);
    document.body.appendChild(form);
    form.submit();
  });

  // ── Drag/drop ────────────────────────────────────────────────────────────────
  initDragDrop(cardsEl,
    function () { return blocks; },
    function (newBlocks) {
      blocks = newBlocks;
      undo.push(blocksToMarkup(blocks));
      syncUndoButtons();
    }
  );

  // ── Load markup from server ──────────────────────────────────────────────────
  const fetchUrl = isSect
    ? '/raw-sect/' + pageName + '/' + sectIdx
    : '/raw/' + pageName;

  fetch(fetchUrl, { credentials: 'same-origin' })
    .then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function (data) {
      loadingEl.remove();
      anchor = data.anchor || '';

      // Update cancel link for section mode
      if (isSect && anchor) {
        cancelBtn.href = '/wiki/' + pageName + '#' + anchor;
      }

      blocks = markupToBlocks(data.content || '').map(assignId);
      undo.push(blocksToMarkup(blocks)); // initial snapshot
      render();
      saveBtn.disabled = false;
      syncUndoButtons();
    })
    .catch(function (err) {
      loadingEl.remove();
      const errEl = document.createElement('div');
      errEl.className = 'be-error';
      errEl.textContent = 'Failed to load page content: ' + err.message;
      root.appendChild(errEl);
    });
}

// Run after DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

})();
