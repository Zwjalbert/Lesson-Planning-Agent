/* 极简 Markdown 渲染器（无依赖，先转义再解析，避免 XSS） */
(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function inline(s) {
    var t = esc(s);
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    t = t.replace(/\*\*([^*]+?)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(?<!\*)\*([^*\n]+?)\*(?!\*)/g, '<em>$1</em>');
    return t;
  }

  function splitRow(line) {
    var s = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    var cells = [], buf = '', escaped = false;
    for (var i = 0; i < s.length; i++) {
      var ch = s[i];
      if (ch === '\\' && s[i + 1] === '|') { buf += '|'; i++; continue; }
      if (ch === '|' && !escaped) { cells.push(buf.trim()); buf = ''; continue; }
      buf += ch;
    }
    cells.push(buf.trim());
    return cells;
  }

  function isSep(line) {
    return /^\s*\|?[\s:\-|]+\|?\s*$/.test(line) && line.indexOf('-') !== -1;
  }

  function render(src) {
    var text = String(src == null ? '' : src).replace(/\r\n?/g, '\n');
    var lines = text.split('\n');
    var out = [], i = 0, list = null, para = [];

    function closeList() {
      if (list) { out.push('</' + list + '>'); list = null; }
    }
    function flushPara() {
      if (para.length) {
        out.push('<p>' + para.map(inline).join('<br>') + '</p>');
        para = [];
      }
    }

    while (i < lines.length) {
      var raw = lines[i], line = raw.replace(/\s+$/, '');

      if (/^\s*```/.test(line)) {
        flushPara(); closeList();
        var code = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        out.push('<pre><code>' + esc(code.join('\n')) + '</code></pre>');
        continue;
      }

      if (!line.trim()) { flushPara(); closeList(); i++; continue; }

      var h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        flushPara(); closeList();
        var lv = h[1].length;
        out.push('<h' + lv + '>' + inline(h[2]) + '</h' + lv + '>');
        i++; continue;
      }

      if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) {
        flushPara(); closeList(); out.push('<hr>'); i++; continue;
      }

      if (/^\s*\|/.test(line) && (i + 1 < lines.length && (isSep(lines[i + 1]) || /^\s*\|/.test(lines[i + 1])))) {
        flushPara(); closeList();
        var head = splitRow(line), rows = [];
        i += (i + 1 < lines.length && isSep(lines[i + 1])) ? 2 : 1;
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          if (!isSep(lines[i])) rows.push(splitRow(lines[i]));
          i++;
        }
        var html = '<div class="tbl-wrap"><table class="' + (head.length === 2 ? 'cols-2' : '') + '"><thead><tr>';
        head.forEach(function (c) { html += '<th>' + inline(c) + '</th>'; });
        html += '</tr></thead><tbody>';
        rows.forEach(function (r) {
          html += '<tr>';
          for (var c = 0; c < head.length; c++) html += '<td>' + inline(r[c] || '') + '</td>';
          html += '</tr>';
        });
        html += '</tbody></table></div>';
        out.push(html);
        continue;
      }

      if (/^\s*[-*•]\s+/.test(line)) {
        flushPara();
        if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; }
        out.push('<li>' + inline(line.replace(/^\s*[-*•]\s+/, '')) + '</li>');
        i++; continue;
      }
      if (/^\s*\d+[.、]\s+/.test(line)) {
        flushPara();
        if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; }
        out.push('<li>' + inline(line.replace(/^\s*\d+[.、]\s+/, '')) + '</li>');
        i++; continue;
      }

      if (/^\s*>\s?/.test(line)) {
        flushPara(); closeList();
        out.push('<blockquote>' + inline(line.replace(/^\s*>\s?/, '')) + '</blockquote>');
        i++; continue;
      }

      closeList();
      para.push(line.replace(/^#+\s*/, ''));
      i++;
    }
    flushPara(); closeList();
    return out.join('\n');
  }

  window.MD = { render: render, esc: esc };
})();
