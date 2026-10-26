/* ============================================================
   备课智能体 · 工作台逻辑（v2）
   纯原生 JS，无构建步骤。
   ============================================================ */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var h = function (s) { return window.MD.esc(s); };
  var S = {
    sys: null, courses: [], cid: 0, board: null, view: 'home',
    chat: null, task: null, timer: null, reviewAid: 0,
    planGenWeeks: null, planSel: null, genWeeks: null, genTypes: null,
    vault: null, vaultKind: '', frameworks: null, fwFilter: '',
    taskTick: 0, autoOpened: false
  };

  var ST = {
    pending: ['待生成', 'pending'], queued: ['排队中', 'review'],
    drafting: ['生成中', 'drafting'], reviewing: ['待确认', 'review'],
    review: ['待确认', 'review'], revising: ['修订中', 'revising'],
    approved: ['已定稿', 'approved'], done: ['已完成', 'done'],
    failed: ['失败', 'failed'], cancelled: ['已取消', 'cancelled'],
    interrupted: ['已中断', 'interrupted'], running: ['运行中', 'running']
  };
  var TASK_CN = { queued: '排队中', running: '运行中', done: '已完成', failed: '失败', cancelled: '已取消', interrupted: '已中断' };
  var FT = { lesson_plan: '教案', handout: '讲义', courseware: '课件', script: '逐字稿' };
  var TYPE_CN = {
    lesson_plan: '教案', handout: '讲义', courseware: '课件', script: '逐字稿', summary: '周间摘要',
    intent: '意图解析', course_map: '课程地图', revise: '文件修改', repair: '结构修复',
    week_plan: '课程地图', general: '其他'
  };
  var LOG_CN = {
    create: '新建课程', upload: '上传资料', upload_text: '粘贴资料', delete_material: '删除资料',
    parse: '解析资料', build_plan: '生成地图', edit_plan: '编辑地图', retitle: '重写周次',
    approve_plan: '批准地图', approve: '批准定稿', revise: '修订', revise_failed: '修订失败',
    reopen: '退回', reset: '重生成', restore: '版本回退', package: '打包交付', generate: '生成'
  };

  // ================= 基础工具 =================
  function api(path, opt) {
    opt = opt || {};
    var init = { method: opt.method || 'GET', headers: {} };
    if (opt.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opt.body);
    }
    return fetch(path, init).then(function (r) {
      return r.text().then(function (txt) {
        var j = null;
        try { j = JSON.parse(txt); } catch (e) { j = { ok: false, msg: txt || ('HTTP ' + r.status) }; }
        if (!r.ok || j.ok === false) {
          var msg = j.msg || ('请求失败（HTTP ' + r.status + '）');
          if (!opt.silent) toast(msg, 'err');
          var err = new Error(msg);
          err.payload = j;
          throw err;
        }
        return j;
      });
    });
  }

  function toast(msg, type) {
    var box = $('#toastBox');
    var el = document.createElement('div');
    el.className = 'toast ' + (type || '');
    el.textContent = String(msg || '');
    box.appendChild(el);
    setTimeout(function () {
      el.style.opacity = '0';
      el.style.transform = 'translateX(16px)';
      el.style.transition = '.25s';
      setTimeout(function () { el.remove(); }, 260);
    }, type === 'err' ? 5200 : 3200);
  }

  function busy(on) {
    var bar = $('#topProgress');
    if (bar) bar.classList.toggle('on', !!on);
  }

  function btnBusy(btn, on, label) {
    if (!btn) return;
    if (on) {
      if (!btn.dataset.old) btn.dataset.old = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spin"></span>' + (label || '处理中');
    } else {
      btn.disabled = false;
      if (btn.dataset.old) btn.innerHTML = btn.dataset.old;
      delete btn.dataset.old;
    }
  }

  function badge(status) {
    var x = ST[status] || [status || '—', 'pending'];
    var pulse = (status === 'running' || status === 'drafting' || status === 'revising')
      ? '<i class="pulse"></i>' : '';
    return '<span class="badge ' + x[1] + '">' + pulse + h(x[0]) + '</span>';
  }

  function fmtCost(n) { return '¥' + Number(n || 0).toFixed(4); }
  function exportBtns(a) {
    if (a.file_type === 'courseware') {
      return '<a class="btn ghost sm" href="/api/artifact/' + a.id + '/export?fmt=pptx">PPTX</a> ' +
        '<a class="btn ghost sm" href="/api/artifact/' + a.id + '/export?fmt=html">互动HTML</a>';
    }
    return '<a class="btn ghost sm" href="/api/artifact/' + a.id + '/export?fmt=docx">docx</a> ' +
      '<a class="btn ghost sm" href="/api/artifact/' + a.id + '/export?fmt=html">HTML</a> ' +
      '<a class="btn ghost sm" href="/api/artifact/' + a.id + '/export?fmt=md">Markdown</a>';
  }
  function fmtNum(n) { return Number(n || 0).toLocaleString('zh-CN'); }
  function shortTime(ts) { return ts ? String(ts).slice(5, 16) : ''; }
  function truncate(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n) + '…' : s; }

  function pageHead(title, sub, actions, gate) {
    return '<div class="page-head"><div><h1>' + h(title) +
      (gate ? '<span class="gate">' + h(gate) + '</span>' : '') + '</h1>' +
      '<div class="sub">' + sub + '</div></div><div class="spacer"></div>' +
      (actions || '') + '</div>';
  }

  function emptyBox(title, desc) {
    return '<div class="empty"><b>' + h(title) + '</b>' + h(desc) + '</div>';
  }

  function note(text, blue) {
    return '<div class="note' + (blue ? ' blue' : '') + '">' + text + '</div>';
  }

  // ================= 弹窗 =================
  function modal(opts) {
    opts = opts || {};
    $('#modalTitle').textContent = opts.title || '';
    $('#modalBody').innerHTML = opts.body || '';
    $('#modalFoot').innerHTML = opts.footer || '';
    var box = $('#modal');
    box.className = 'modal' + (opts.wide ? ' wide' : '') + (opts.slim ? ' slim' : '');
    $('#overlay').classList.remove('hide');
    if (opts.onOpen) opts.onOpen();
  }
  function closeModal() { $('#overlay').classList.add('hide'); }

  function confirmDlg(title, text, okText, onOk) {
    modal({
      title: title, slim: true,
      body: '<div class="help" style="font-size:13px;line-height:1.8">' + text + '</div>',
      footer: '<button class="btn ghost" data-act="modal-close">取消</button>' +
        '<button class="btn danger" id="confirmOk">' + h(okText || '确认') + '</button>',
      onOpen: function () {
        $('#confirmOk').onclick = function () { closeModal(); onOk(); };
      }
    });
  }

  // ================= 课程 / 看板 =================
  async function loadSys() {
    try {
      S.sys = await api('/api/system/info', { silent: true });
      var mode = S.sys.mode === 'real';
      $('#modeText').textContent = mode ? '真实模型' : '未配置模型';
      $('#modePill').classList.toggle('real', mode);
      $('#modelTag').textContent = (mode ? '模型 · ' : '需配置 · ') + (S.sys.model || '');
      $('#verText').textContent = 'v' + (S.sys.version || '2.0');
      $('#sideHint').innerHTML = mode
        ? '自动续跑已开启 · 上传上限 ' + S.sys.limits.max_upload_mb + 'MB'
        : '<span style="color:#ffd08a">尚未配置 API Key，生成不可用</span>';
    } catch (e) {
      $('#modeText').textContent = '连接失败';
    }
  }

  async function loadCourses() {
    try {
      var r = await api('/api/courses', { silent: true });
      S.courses = r.courses || [];
    } catch (e) { S.courses = []; }
  }

  async function selectCourse(cid) {
    S.cid = cid;
    localStorage.setItem('kb.cid', String(cid));
    S.chat = null; S.task = null; S.reviewAid = 0;
    S.planGenWeeks = null; S.planSel = new Set(); S.genWeeks = null; S.genTypes = null;
    if (S.timer) { clearInterval(S.timer); S.timer = null; }
    await refreshBoard();
    nav('home');
  }

  async function refreshBoard() {
    if (!S.cid) {
      S.board = null; updateShell(); renderCurrent(); return;
    }
    try {
      var b = await api('/api/course/' + S.cid + '/board', { silent: true });
      S.board = b;
      if (S.chat === null) {
        S.chat = (b.messages || []).map(function (m) { return { role: m.role, text: m.text }; });
      }
      var running = (b.tasks || []).filter(function (t) { return t.status === 'running' || t.status === 'queued'; })[0];
      if (running && !S.timer) trackTask(running.id, true);
      updateShell();
      renderCurrent();
    } catch (e) {
      toast('读取课程数据失败：' + e.message, 'err');
    }
  }

  function updateShell() {
    var b = S.board, c = b && b.course;
    if (c) {
      $('#courseName').textContent = c.name;
      $('#courseMeta').textContent = (c.semester || '—') + ' · ' + (c.weeks || 0) + ' 周' +
        (c.class_name ? ' · ' + c.class_name : '');
    } else {
      $('#courseName').textContent = '未选择课程';
      $('#courseMeta').textContent = '点击选择或新建';
    }
    var cnt = 0;
    if (b) cnt = (b.artifacts || []).filter(function (a) { return a.status === 'review' || a.status === 'revising'; }).length;
    var nc = $('#navReviewCnt');
    nc.textContent = cnt;
    nc.style.display = cnt ? 'grid' : 'none';
  }

  function nav(view) {
    S.view = view;
    var titles = {
      home: '课程工作台', materials: '资料库', plan: '课程地图', board: '生成中心',
      review: '确认中心', deliver: '交付与用量', vault: '公共资源区', frameworks: '提示词框架'
    };
    $('#crumb').textContent = titles[view] || '';
    $$('#nav button').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-view') === view); });
    $$('.view').forEach(function (v) { v.classList.toggle('on', v.id === 'v-' + view); });
    renderCurrent();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function renderCurrent() {
    if (S.view === 'home') return renderHome();
    if (S.view === 'materials') return renderMaterials();
    if (S.view === 'plan') return renderPlan();
    if (S.view === 'board') return renderBoard();
    if (S.view === 'review') return renderReview();
    if (S.view === 'deliver') return renderDeliver();
    if (S.view === 'vault') {
      if (!S.vault) await loadVault();
      return renderVault();
    }
    if (S.view === 'frameworks') {
      if (!S.frameworks) await loadFrameworks();
      return renderFrameworks();
    }
  }

  // ================= 工作台 =================
  function nextAction() {
    var b = S.board;
    if (!b) return null;
    var mats = b.materials || [], plans = b.week_plans || [], arts = b.artifacts || [];
    if (!mats.length) return { view: 'materials', label: '上传课程资料', hint: '先让智能体读懂你的教学计划与教材' };
    if (!plans.length) return { view: 'plan', label: '生成课程地图', hint: '按资料规划每周主题、学时、目标与思政点' };
    if (plans.some(function (p) { return p.status !== 'approved'; })) return { view: 'plan', label: '核对并批准课程地图', hint: '门 A：确认周次规划后再开始生成' };
    var review = arts.filter(function (a) { return a.status === 'review' || a.status === 'revising'; });
    if (review.length) return { view: 'review', label: '确认 ' + review.length + ' 份初稿', hint: '门 B：批准定稿或提出修改要求' };
    var expected = plans.length * 4;
    var approved = arts.filter(function (a) { return a.status === 'approved'; }).length;
    if (approved < expected) return { view: 'board', label: '继续生成教学包', hint: '教案 → 讲义 → 课件 / 逐字稿，按依赖链推进' };
    return { view: 'deliver', label: '打包交付教学包', hint: '全部定稿，可导出 docx / PPTX / 互动 HTML / Markdown' };
  }

  function renderHome() {
    var el = $('#v-home');
    if (!S.cid || !S.board) {
      el.innerHTML = pageHead('课程工作台', '一句话开始备课：上传资料 → 生成地图 → 逐份确认 → 打包交付。') +
        '<div class="hero"><div class="kicker">WORKFLOW SHELL</div><h2>把豆包的任务模式，装进固定的备课外壳</h2>' +
        '<div class="meta">对话总控 · 提示词框架库 · 课程知识库 · 三处确认门 · 多格式交付</div>' +
        '<div class="h-actions"><button class="btn gold" data-act="new-course">新建第一门课程</button></div></div>' +
        '<div class="grid grid-3">' +
        ['01　上传资料', '02　生成课程地图', '03　逐份确认与交付'].map(function (t, i) {
          return '<div class="card tight"><div class="card-head"><h3>' + t + '</h3></div><div class="help">' +
            ['教学计划、教材目录、课程标准、案例素材，支持 docx/xlsx/pdf/txt/csv。',
              '智能体按资料提取每周具体主题，目标可检测、思政点自然融入。',
              '教案 / 讲义 / 课件 / 逐字稿逐份门 B 确认，可对话修改，最后整包导出。'][i] +
            '</div></div>';
        }).join('') + '</div>';
      return;
    }
    var b = S.board, c = b.course, plans = b.week_plans || [], arts = b.artifacts || [];
    var expected = plans.length * 4;
    var approved = arts.filter(function (a) { return a.status === 'approved'; }).length;
    var review = arts.filter(function (a) { return a.status === 'review' || a.status === 'revising'; }).length;
    var pct = expected ? Math.min(100, Math.round(approved / expected * 100)) : 0;
    var na = nextAction();
    var usage = b.usage || {};

    var html = pageHead('课程工作台', '当前课程的全部进度、任务与对话都在这里；右侧可以直接用一句话驱动。',
      '<button class="btn ghost sm" data-act="refresh">刷新</button>' +
      (na ? '<button class="btn sm" data-act="goto" data-view="' + na.view + '">' + h(na.label) + '</button>' : ''));

    html += '<div class="hero"><div class="kicker">' + h(c.semester || '') + ' · ' + h(c.class_name || '未设置班级') + '</div>' +
      '<h2>' + h(c.name) + '</h2>' +
      '<div class="meta">' + h(c.theme || '未填写课程主题') + (c.textbook ? ' · 教材：' + h(c.textbook) : '') + '</div>' +
      '<div class="progress"><i style="width:' + pct + '%"></i></div>' +
      '<div class="progress-label"><span>已定稿 ' + approved + ' / ' + expected + ' 份</span><span>' + pct + '%</span></div>' +
      '<div class="h-stats">' +
      '<div class="h-stat"><b>' + (b.materials || []).length + '</b><span>份资料</span></div>' +
      '<div class="h-stat"><b>' + plans.length + '</b><span>周已规划</span></div>' +
      '<div class="h-stat"><b>' + review + '</b><span>份待确认</span></div>' +
      '<div class="h-stat"><b>' + fmtCost(usage.cost) + '</b><span>累计费用</span></div>' +
      '</div>' +
      (na ? '<div class="h-actions"><button class="btn gold" data-act="goto" data-view="' + na.view + '">' + h(na.label) + ' →</button></div>' : '') +
      '</div>';

    html += '<div class="quick-grid" style="margin-bottom:16px">' + [
      ['02', '资料库', '上传 / 粘贴教学资料，解析为知识库', 'materials'],
      ['03', '课程地图', '逐周核对主题、学时、目标与思政点', 'plan'],
      ['04', '生成中心', '教案 → 讲义 → 课件 / 逐字稿，可自动续跑', 'board'],
      ['05', '确认中心', '门 B 逐份批准，或对话式个别修改', 'review']
    ].map(function (x) {
      return '<button class="quick" data-act="goto" data-view="' + x[3] + '"><span class="n">' + x[0] + '</span>' +
        '<b>' + x[1] + ' <span class="arrow">↗</span></b><span>' + x[2] + '</span></button>';
    }).join('') + '</div>';

    html += '<div class="dash"><div>';
    html += '<div class="card"><div class="card-head"><h3>下一步建议</h3><span class="spacer"></span>' +
      '<span class="hint">按流程自动判断</span></div>' +
      (na ? '<div class="row"><div style="flex:1"><b style="font-family:var(--serif);font-size:16px;color:var(--deep)">' +
        h(na.label) + '</b><div class="help" style="margin-top:3px">' + h(na.hint) + '</div></div>' +
        '<button class="btn" data-act="goto" data-view="' + na.view + '">去做</button></div>'
        : '<div class="help">教学包已全部定稿，可前往「交付与用量」打包。</div>') + '</div>';

    var tasks = b.tasks || [];
    html += '<div class="card"><div class="card-head"><h3>最近任务</h3><span class="spacer"></span>' +
      '<span class="hint">生成在后台线程执行，可离开本页</span></div>';
    if (!tasks.length) html += '<div class="help">还没有生成任务。先在「课程地图」批准周次，再到「生成中心」启动。</div>';
    else {
      html += '<div class="list">' + tasks.slice(0, 4).map(function (t) {
        return '<div class="list-item"><div class="ic">' + (TASK_CN[t.status] || '?').slice(0, 1) + '</div>' +
          '<div class="bd"><b>第 ' + ((t.payload && t.payload.weeks) || []).join('、') + ' 周 · ' +
          ((t.payload && t.payload.file_types) || []).map(function (f) { return FT[f] || f; }).join('/') + '</b>' +
          '<span>' + shortTime(t.created_at) + ' · ' + h(TASK_CN[t.status] || t.status) +
          (t.message ? ' · ' + h(t.message) : '') + '</span></div>' +
          '<div class="rt">' + badge(t.status) + '</div></div>';
      }).join('') + '</div>';
    }
    html += '</div>';

    var logs = b.confirm_logs || [];
    html += '<div class="card"><div class="card-head"><h3>确认与操作记录</h3></div>';
    if (!logs.length) html += '<div class="help">暂无记录。</div>';
    else {
      html += '<div class="list">' + logs.slice(0, 6).map(function (l) {
        return '<div class="list-item"><div class="ic">·</div><div class="bd"><b>' +
          h(LOG_CN[l.action] || l.action) + '</b><span>' + shortTime(l.ts) + ' · ' + h(truncate(l.reason, 42)) +
          '</span></div></div>';
      }).join('') + '</div>';
    }
    html += '</div>';

    html += '</div><div>' + renderChatCard() + '</div></div>';
    el.innerHTML = html;
    scrollChat();
  }

  function renderChatCard() {
    var msgs = S.chat || [];
    var greeting = {
      role: 'ai',
      text: '你好，我是备课智能体。你可以直接说：「生成第 2-3 周教学包」「先生成课程地图」「生成第 2 周互动课件」「把第 2 周教案的导入换成校园案例」。'
    };
    if (!msgs.length) msgs = [greeting];
    var body = msgs.map(function (m) {
      var who = m.role === 'user' ? '你' : (m.role === 'system' ? '系统' : '备课智能体');
      return '<div class="msg ' + (m.role === 'user' ? 'user' : 'ai') + '"><div class="who">' + who +
        '</div><div class="bubble">' + h(m.text) + '</div></div>';
    }).join('');
    return '<div class="card"><div class="card-head"><h3>对话总控</h3><span class="spacer"></span>' +
      '<span class="hint">解析需求并直接执行</span></div>' +
      '<div class="chat"><div class="chat-body" id="chatBody">' + body + '</div>' +
      '<form class="chat-input" id="chatForm"><input class="input" id="chatInput" placeholder="说出你的备课需求…" autocomplete="off">' +
      '<button class="btn" type="submit">发送</button></form>' +
      '<div class="quick-prompts">' +
      ['先生成课程地图', '生成第2-3周教学包', '生成第2周互动课件', '把第2周教案的导入换成校园案例'].map(function (t) {
        return '<button type="button" data-act="chat-quick" data-text="' + h(t) + '">' + h(t) + '</button>';
      }).join('') + '</div></div></div>';
  }

  function scrollChat() {
    var c = $('#chatBody');
    if (c) c.scrollTop = c.scrollHeight;
  }

  async function sendChat(text) {
    text = (text || '').trim();
    if (!text) return;
    if (!S.cid) { toast('请先新建或选择课程', 'err'); return; }
    if (!S.chat) S.chat = [];
    S.chat.push({ role: 'user', text: text });
    S.chat.push({ role: 'ai', text: '正在处理…' });
    if (S.view === 'home') renderHome();
    var input = $('#chatInput');
    if (input) input.value = '';
    busy(true);
    try {
      var r = await api('/api/course/' + S.cid + '/chat', { method: 'POST', body: { text: text } });
      S.chat[S.chat.length - 1] = { role: 'ai', text: r.reply || '已处理。' };
      if (r.needs_key) toast('未配置 API Key：请先在 .env 填写 LLM_API_KEY 并重启服务', 'err');
      if (r.task_id) {
        toast('已启动生成任务', 'ok');
        nav('board');
        trackTask(r.task_id);
      } else if (r.plan_result && r.plan_result.ok) {
        toast('课程地图已生成，请核对（门 A）', 'ok');
        await refreshBoard();
        nav('plan');
      } else if (r.artifact_id) {
        await refreshBoard();
        nav('review');
        openArtifactModal(r.artifact_id);
      } else {
        await refreshBoard();
      }
    } catch (e) {
      S.chat[S.chat.length - 1] = { role: 'ai', text: '执行失败：' + e.message };
      if (S.view !== 'home') nav('home'); else renderHome();
    } finally {
      busy(false);
      if (S.view === 'home') renderHome();
    }
  }

  // ================= 资料库 =================
  function renderMaterials() {
    var el = $('#v-materials');
    if (!S.board) { el.innerHTML = pageHead('资料库', '请先选择课程。'); return; }
    var mats = S.board.materials || [];
    var withSum = mats.filter(function (m) { return m.summary; }).length;
    var html = pageHead('资料库', '资料越完整，生成的主题越贴合你的课程；系统以资料<strong>原文</strong>为唯一事实依据。',
      '<button class="btn ghost sm" data-act="material-parse">解析并生成摘要</button>');
    html += '<div class="grid grid-2 top">' +
      '<div class="card"><div class="card-head"><h3>上传文件</h3><span class="spacer"></span>' +
      '<span class="hint">≤ ' + (S.sys ? S.sys.limits.max_upload_mb : 20) + 'MB</span></div>' +
      '<label class="drop" id="dropZone" for="fileInput"><b>点击选择，或把文件拖到这里</b>' +
      '<span>docx / xlsx / pdf / txt / md / csv；旧版 .doc、.xls 请先另存为新格式</span>' +
      '<input type="file" id="fileInput" hidden accept=".txt,.md,.markdown,.csv,.docx,.xlsx,.pdf"></label>' +
      '<div class="file-line" id="fileLine"></div>' +
      '<div class="row" style="margin-top:10px"><button class="btn" data-act="material-upload">上传并入库</button>' +
      '<span class="help">上传后可点右上「解析并生成摘要」构建知识库</span></div></div>' +
      '<div class="card"><div class="card-head"><h3>粘贴文本</h3></div>' +
      '<label class="f">资料名称</label><input class="input" id="matName" placeholder="如：第1-16周教学计划">' +
      '<label class="f" style="margin-top:8px">内容</label><textarea class="textarea" id="matContent" rows="6" placeholder="粘贴教学计划、课程要求、教材目录…"></textarea>' +
      '<div class="row end" style="margin-top:9px"><button class="btn ghost" data-act="material-text">保存为资料</button></div></div>' +
      '</div>';
    html += '<div class="card"><div class="card-head"><h3>已入库资料</h3><span class="spacer"></span>' +
      '<span class="hint">' + mats.length + ' 份 · ' + withSum + ' 份已有摘要</span></div>';
    if (!mats.length) html += emptyBox('还没有资料', '先上传教学计划或教材目录；没有资料时智能体会提示「依据教学常识补充」，质量会下降。');
    else {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>资料</th><th>字符</th><th>摘要 / 状态</th><th style="width:140px">操作</th></tr></thead><tbody>';
      mats.forEach(function (m) {
        html += '<tr><td><div class="cell-title">' + h(m.filename) + '</div><div class="cell-sub">' + shortTime(m.created_at) + '</div></td>' +
          '<td class="mono">' + fmtNum(m.chars) + '</td>' +
          '<td>' + (m.summary ? '<span class="help">' + h(truncate(m.summary, 60)) + '</span>' : '<span class="badge pending">待解析</span>') + '</td>' +
          '<td class="actions"><button class="btn link" data-act="material-view" data-id="' + m.id + '">查看</button>' +
          '<button class="btn link" style="color:var(--danger)" data-act="material-del" data-id="' + m.id + '">删除</button></td></tr>';
      });
      html += '</tbody></table></div>';
    }
    html += '</div>';
    html += note('<b>解析顺序：</b>公共资源区（模板/方法论/思政素材）→ 课程资料原文 → 本次需求（侧重点/语气）。超长资料按份公平分配并显式标注截断，不会只取第一份。');
    el.innerHTML = html;
  }

  async function uploadFile() {
    var f = $('#fileInput') && $('#fileInput').files[0];
    if (!f) { toast('请先选择文件', 'err'); return; }
    var btn = $('[data-act="material-upload"]');
    btnBusy(btn, true, '上传中');
    var fd = new FormData();
    fd.append('file', f);
    try {
      var r = await fetch('/api/course/' + S.cid + '/material', { method: 'POST', body: fd }).then(function (x) { return x.json(); });
      if (!r.ok) throw new Error(r.msg || '上传失败');
      toast(r.msg, 'ok');
      $('#fileLine').textContent = '';
      await refreshBoard();
    } catch (e) { toast(e.message, 'err'); }
    finally { btnBusy(btn, false); }
  }

  async function parseMaterials() {
    var btn = $('[data-act="material-parse"]');
    btnBusy(btn, true, '解析中');
    try {
      var r = await api('/api/course/' + S.cid + '/parse', { method: 'POST', body: {} });
      toast(r.msg, 'ok');
      await refreshBoard();
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  async function showMaterial(id) {
    try {
      var r = await api('/api/course/' + S.cid + '/material/' + id, { silent: true });
      var m = r.material;
      modal({
        title: m.filename, wide: true,
        body: '<div class="row" style="margin-bottom:10px"><span class="badge review">' + fmtNum(m.chars) + ' 字符</span>' +
          (m.summary ? '<span class="help">摘要：' + h(m.summary) + '</span>' : '<span class="badge pending">尚未解析</span>') + '</div>' +
          '<pre style="max-height:60vh;overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:14px;white-space:pre-wrap;font-size:12.5px;line-height:1.8">' +
          h(m.content || '') + '</pre>',
        footer: '<button class="btn ghost" data-act="modal-close">关闭</button>'
      });
    } catch (e) { }
  }

  // ================= 课程地图 =================
  function renderPlan() {
    var el = $('#v-plan');
    if (!S.board) { el.innerHTML = pageHead('课程地图', '请先选择课程。'); return; }
    var c = S.board.course, plans = S.board.week_plans || [];
    var approved = plans.filter(function (p) { return p.status === 'approved'; }).length;
    var html = pageHead('课程地图', '先核对每周主题、学时、目标与思政点；批准后（门 A）才允许生成。表格修改会自动保存。',
      '<button class="btn ghost sm" data-act="plan-refresh">刷新</button>', '门 A');

    if (S.planGenWeeks === null) {
      var pendingWeeks = plans.filter(function (p) { return p.status !== 'approved'; }).map(function (p) { return p.week_no; });
      S.planGenWeeks = new Set(pendingWeeks.length ? pendingWeeks : plans.map(function (p) { return p.week_no; }));
    }
    html += '<div class="card"><div class="card-head"><h3>生成 / 重写地图</h3><span class="spacer"></span>' +
      '<span class="hint">选周次后由大模型按资料生成</span></div>' +
      '<div class="row" style="margin-bottom:8px"><label class="f" style="margin:0">选择周次</label>' +
      '<button class="btn link" data-act="plan-gen-all">全选</button>' +
      '<button class="btn link" data-act="plan-gen-none">清空</button></div>' +
      '<div class="chips" id="planGenChips">' +
      Array.from({ length: c.weeks }, function (_, i) { return i + 1; }).map(function (w) {
        var on = S.planGenWeeks.has(w);
        return '<button class="chip' + (on ? ' on' : '') + '" data-act="plan-gen-toggle" data-week="' + w + '">第' + w + '周</button>';
      }).join('') + '</div>' +
      '<div class="form-grid" style="margin-top:12px"><div><label class="f">侧重点（可选）</label>' +
      '<input class="input" id="planFocus" placeholder="如：多结合本地产业案例、突出实训"></div>' +
      '<div><label class="f">语气/风格（可选）</label><input class="input" id="planTone" placeholder="如：严谨规范 / 通俗生动"></div></div>' +
      '<div class="row end" style="margin-top:12px"><button class="btn" data-act="plan-generate">生成 / 补全选中周次</button></div>' +
      note('重新生成<strong>已批准</strong>的周次会覆盖原规划并退回待确认；只想补全新周次时，先取消选中已批准周。', true) +
      '</div>';

    html += '<div class="card"><div class="card-head"><h3>周次规划</h3><span class="spacer"></span>' +
      '<span class="hint">已批准 ' + approved + ' / ' + plans.length + ' 周</span></div>';
    if (!plans.length) {
      html += emptyBox('还没有课程地图', '选择周次后点「生成」；建议先完成资料解析，地图会从资料中提取具体主题。');
    } else {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr>' +
        '<th style="width:34px"><input type="checkbox" id="planCheckAll" title="全选未批准"></th>' +
        '<th style="width:56px">周次</th><th style="min-width:180px">主题</th><th style="width:80px">学时</th>' +
        '<th style="min-width:210px">目标（可检测）</th><th style="min-width:170px">思政点</th>' +
        '<th style="width:90px">状态</th><th style="width:170px">操作</th></tr></thead><tbody>';
      plans.forEach(function (p) {
        var sel = S.planSel.has(p.week_no);
        var locked = p.status === 'approved';
        html += '<tr><td><input type="checkbox" class="plan-check" data-week="' + p.week_no + '"' + (sel ? ' checked' : '') + '></td>' +
          '<td class="mono">第' + p.week_no + '周</td>' +
          '<td><input class="input sm plan-field" data-week="' + p.week_no + '" data-field="title" value="' + h(p.title) + '"></td>' +
          '<td><select class="select sm plan-field" data-week="' + p.week_no + '" data-field="hours">' +
          [2, 3, 4].map(function (x) { return '<option value="' + x + '"' + (Number(p.hours) === x ? ' selected' : '') + '>' + x + ' 学时</option>'; }).join('') +
          '</select></td>' +
          '<td><textarea class="textarea plan-field" style="min-height:48px;font-size:12.5px" data-week="' + p.week_no + '" data-field="objective">' + h(p.objective) + '</textarea></td>' +
          '<td><textarea class="textarea plan-field" style="min-height:48px;font-size:12.5px" data-week="' + p.week_no + '" data-field="ideo">' + h(p.ideo) + '</textarea></td>' +
          '<td>' + badge(p.status) + '</td>' +
          '<td class="actions"><button class="btn link" data-act="plan-rewrite" data-week="' + p.week_no + '">AI 重写</button>' +
          (locked ? '<button class="btn link" style="color:var(--gold)" data-act="plan-unapprove" data-week="' + p.week_no + '">退回</button>' : '') +
          '</td></tr>';
      });
      html += '</tbody></table></div>';
      html += '<div class="row" style="margin-top:12px"><span class="help" id="planSelInfo">已选 ' + S.planSel.size + ' 周</span>' +
        '<span class="spacer"></span>' +
        '<button class="btn ghost" data-act="plan-approve-selected">批准选中周次</button>' +
        '<button class="btn" data-act="plan-approve-all">批准全部</button></div>';
    }
    html += '</div>' + note('门 A 的语义：批准的是「周次规划」，不是产物。批准后到「生成中心」按依赖链生成；若修改已批准周次的主题/目标，状态会自动退回待确认。');
    el.innerHTML = html;
  }

  async function savePlanField(input) {
    var week = Number(input.dataset.week), field = input.dataset.field;
    var body = {};
    body[field] = field === 'hours' ? Number(input.value) : input.value;
    try {
      await api('/api/course/' + S.cid + '/plan/' + week, { method: 'PATCH', body: body, silent: true });
      var r = await api('/api/course/' + S.cid + '/board', { silent: true });
      S.board = r;
      updateShell();
      toast('第 ' + week + ' 周已保存', 'ok');
      if (S.view === 'plan') renderPlan();
    } catch (e) { toast(e.message, 'err'); }
  }

  async function rewriteWeek(week, btn) {
    btnBusy(btn, true, '重写中');
    try {
      var r = await api('/api/course/' + S.cid + '/plan/' + week + '/regenerate', { method: 'POST', body: { focus: '' } });
      toast(r.msg, 'ok');
      await refreshBoard();
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  async function generatePlan(btn) {
    var weeks = Array.from(S.planGenWeeks || []);
    if (!weeks.length) { toast('请选择周次', 'err'); return; }
    btnBusy(btn, true, '生成中（约 30-90 秒）');
    busy(true);
    try {
      var r = await api('/api/course/' + S.cid + '/plan', {
        method: 'POST', body: {
          weeks: weeks,
          focus: ($('#planFocus') || {}).value || '',
          tone: ($('#planTone') || {}).value || ''
        }
      });
      toast(r.msg, 'ok');
      await refreshBoard();
    } catch (e) { }
    finally { busy(false); btnBusy(btn, false); }
  }

  async function approvePlan(weeks, btn) {
    if (!weeks || !weeks.length) { toast('请先选择要批准的周次', 'err'); return; }
    btnBusy(btn, true, '批准中');
    try {
      var r = await api('/api/course/' + S.cid + '/plan/approve', { method: 'POST', body: { weeks: weeks } });
      toast(r.msg, 'ok');
      S.planSel = new Set();
      await refreshBoard();
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  // ================= 生成中心 =================
  function renderBoard() {
    var el = $('#v-board');
    if (!S.board) { el.innerHTML = pageHead('生成中心', '请先选择课程。'); return; }
    var b = S.board, plans = b.week_plans || [], arts = b.artifacts || [];
    var approvedWeeks = plans.filter(function (p) { return p.status === 'approved'; }).map(function (p) { return p.week_no; });
    if (S.genWeeks === null) S.genWeeks = new Set(approvedWeeks.slice(0, 1));
    if (S.genTypes === null) S.genTypes = new Set(['lesson_plan', 'handout', 'courseware', 'script']);
    var html = pageHead('生成中心', '按依赖链增量推进：教案 →（批准）→ 讲义 →（批准）→ 课件与逐字稿；每周教案自动衔接上周摘要。',
      '<button class="btn ghost sm" data-act="refresh">刷新</button>');

    html += '<div class="grid grid-2"><div class="card"><div class="card-head"><h3>启动生成</h3><span class="spacer"></span>' +
      '<span class="hint">可多选周次</span></div>' +
      (approvedWeeks.length ? '<div class="row" style="margin-bottom:7px"><label class="f" style="margin:0">已批准周次</label>' +
        '<button class="btn link" data-act="gen-all">全选</button><button class="btn link" data-act="gen-none">清空</button></div>' +
        '<div class="chips" id="genChips">' + approvedWeeks.map(function (w) {
          return '<button class="chip' + (S.genWeeks.has(w) ? ' on' : '') + '" data-act="gen-toggle" data-week="' + w + '">第' + w + '周</button>';
        }).join('') + '</div>'
        : '<div class="help">还没有已批准的周次。请先去「课程地图」批准（门 A）。</div>') +
      '<div class="row" style="margin:12px 0 4px;gap:14px">' +
      ['lesson_plan', 'handout', 'courseware', 'script'].map(function (f) {
        return '<label class="check"><input type="checkbox" class="gen-type" value="' + f + '"' +
          (S.genTypes.has(f) ? ' checked' : '') + '>' + FT[f] + '</label>';
      }).join('') + '</div>' +
      '<div class="form-grid" style="margin-top:8px"><div><label class="f">侧重点（可选）</label>' +
      '<input class="input" id="genFocus" placeholder="如：多放校园案例、加强实训"></div>' +
      '<div><label class="f">语气（可选）</label><input class="input" id="genTone" placeholder="如：贴近学生、口语化"></div></div>' +
      '<div class="row end" style="margin-top:12px"><span class="help" id="genCount">将处理 ' + (S.genWeeks.size * S.genTypes.size) + ' 个文件</span>' +
      '<button class="btn" data-act="gen-start">开始生成</button></div>' +
      '</div>' +
      '<div class="card"><div class="card-head"><h3>自动续跑</h3><span class="spacer"></span>' +
      '<span class="badge ' + (b.course.auto_chain ? 'approved' : 'pending') + '">' + (b.course.auto_chain ? '已开启' : '已关闭') + '</span></div>' +
      '<div class="help" style="line-height:1.9">门 B 批准教案后，系统自动排队生成讲义；批准讲义后自动生成互动课件与逐字稿。可在下方开关控制。</div>' +
      '<div class="row" style="margin-top:12px"><label class="check"><input type="checkbox" id="autoChain"' + (b.course.auto_chain ? ' checked' : '') + '> 批准后自动续跑下游</label></div>' +
      note('生成失败会自动重试 1 次；仍失败则标记失败，可在确认中心单独重试。所有生成内容均调用真实大模型，会产生费用。', true) +
      '</div></div>';

    html += '<div id="taskBox" style="margin-top:16px">' + renderTaskCard() + '</div>';

    // 周次 × 文件矩阵
    html += '<div class="card" style="margin-top:16px"><div class="card-head"><h3>周次 × 文件矩阵</h3><span class="spacer"></span>' +
      '<span class="hint">点击单元格查看与确认</span></div>';
    if (!plans.length) {
      html += emptyBox('先批准课程地图', '批准后，每周会在这里出现教案、讲义、课件、逐字稿四个格子。');
    } else {
      var by = {};
      arts.forEach(function (a) { by[a.week_no + '-' + a.file_type] = a; });
      html += '<div class="matrix"><div></div>' + ['lesson_plan', 'handout', 'courseware', 'script'].map(function (f) { return '<div class="mh">' + FT[f] + '</div>'; }).join('');
      plans.forEach(function (p) {
        html += '<div class="mw">' + p.week_no + '</div>';
        ['lesson_plan', 'handout', 'courseware', 'script'].forEach(function (f) {
          var a = by[p.week_no + '-' + f];
          if (!a) {
            html += '<div class="mcell pending"><span class="t">第' + p.week_no + '周</span><span class="s">未开始</span></div>';
            return;
          }
          var meta = a.word_count ? (fmtNum(a.word_count) + (a.file_type === 'courseware' ? ' 字符 · ' : ' 字 · ') + fmtCost(a.cost))
            : (a.status === 'failed' ? '生成失败' : (a.status === 'pending' ? '未生成' : '—'));
          html += '<button class="mcell ' + a.status + '" data-act="open-artifact" data-id="' + a.id + '">' +
            '<span class="t">' + (a.warnings ? '⚠ ' + h(truncate(a.warnings, 22)) : (a.model ? h(truncate(a.model, 20)) : '—')) + '</span>' +
            '<span class="s">' + h(ST[a.status] ? ST[a.status][0] : a.status) + '</span>' +
            '<span class="t">' + meta + '</span></button>';
        });
      });
      html += '</div>';
    }
    html += '</div>';

    // 最近任务
    var tasks = b.tasks || [];
    html += '<div class="card"><div class="card-head"><h3>任务记录</h3></div>';
    if (!tasks.length) html += '<div class="help">暂无任务。</div>';
    else {
      html += '<div class="list">' + tasks.map(function (t) {
        return '<div class="list-item"><div class="ic">' + (TASK_CN[t.status] || '?').slice(0, 1) + '</div>' +
          '<div class="bd"><b>第 ' + ((t.payload && t.payload.weeks) || []).join('、') + ' 周 · ' +
          ((t.payload && t.payload.file_types) || []).map(function (f) { return FT[f] || f; }).join(' / ') + '</b>' +
          '<span>' + shortTime(t.created_at) + ' · ' + h(t.message || '') + '</span></div>' +
          '<div class="rt">' + badge(t.status) + (t.status === 'running' || t.status === 'queued' ? '<br><button class="btn link" data-act="task-track" data-id="' + t.id + '">查看进度</button>' : '') + '</div></div>';
      }).join('') + '</div>';
    }
    html += '</div>';
    el.innerHTML = html;
  }

  function renderTaskCard() {
    var t = S.task;
    if (!t) {
      return '<div class="card"><div class="card-head"><h3>任务进度</h3><span class="spacer"></span>' +
        '<span class="hint">启动生成后在这里实时显示</span></div>' +
        '<div class="help">尚未运行任务。进度条会按「本轮要处理的文件数」计算，跳过项也会说明原因。</div></div>';
    }
    var pct = t.total ? Math.round((t.done || 0) / t.total * 100) : 0;
    var log = (t.log || []).map(function (l) {
      var cls = /失败|异常|错误/.test(l) ? 'bad' : (/完成|批准|就绪|已定稿/.test(l) ? 'ok' : '');
      return '<span class="' + cls + '">' + h(l) + '</span>';
    }).join('\n');
    return '<div class="card"><div class="task-head"><h3 style="font-family:var(--serif);color:var(--deep);font-size:16px">任务进度</h3>' +
      badge(t.status) + '<b>' + h(t.id || '') + '</b><span class="spacer"></span>' +
      '<span class="hint">' + (t.done || 0) + ' / ' + (t.total || 0) + '</span>' +
      ((t.status === 'running' || t.status === 'queued') ? '<button class="btn danger sm" data-act="task-cancel" data-id="' + h(t.id) + '">取消</button>' : '') +
      '</div><div class="progress"><i style="width:' + pct + '%"></i></div>' +
      (t.message ? '<div class="help" style="margin:6px 0 0">' + h(t.message) + '</div>' : '') +
      '<div class="log" id="taskLog" style="margin-top:12px">' + (log || '等待日志…') + '</div></div>';
  }

  async function trackTask(tid, silent) {
    S.task = { id: tid, status: 'queued', done: 0, total: 0, log: [], message: '' };
    if (S.timer) clearInterval(S.timer);
    if (!silent) nav('board');
    var tick = async function () {
      try {
        var t = await api('/api/task/' + tid, { silent: true });
        S.task = t;
        if (S.view === 'board') {
          var box = $('#taskBox');
          if (box) box.innerHTML = renderTaskCard();
        }
        if (t.status !== 'running' && t.status !== 'queued') {
          clearInterval(S.timer); S.timer = null;
          toast('任务' + (TASK_CN[t.status] || '结束') + (t.message ? '：' + t.message : ''), t.status === 'done' ? 'ok' : '');
          await refreshBoard();
          return true;
        }
        return false;
      } catch (e) {
        clearInterval(S.timer); S.timer = null;
        return true;
      }
    };
    var finished = await tick();
    if (!finished) S.timer = setInterval(tick, 1400);
  }

  async function startGenerate(btn) {
    var weeks = Array.from(S.genWeeks || []);
    var types = Array.from(S.genTypes || []);
    if (!weeks.length) { toast('请选择要生成的周次', 'err'); return; }
    if (!types.length) { toast('请至少选择一种文件', 'err'); return; }
    btnBusy(btn, true, '提交中');
    try {
      var r = await api('/api/course/' + S.cid + '/generate', {
        method: 'POST', body: {
          weeks: weeks, file_types: types,
          focus: ($('#genFocus') || {}).value || '', tone: ($('#genTone') || {}).value || ''
        }
      });
      toast('任务已启动', 'ok');
      await trackTask(r.task_id);
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  // ================= 确认中心 =================
  function renderReview() {
    var el = $('#v-review');
    if (!S.board) { el.innerHTML = pageHead('确认中心', '请先选择课程。'); return; }
    var arts = S.board.artifacts || [];
    var review = arts.filter(function (a) { return a.status === 'review' || a.status === 'revising'; });
    var approved = arts.filter(function (a) { return a.status === 'approved'; });
    var filter = S.reviewFilter || 'review';
    var list = filter === 'review' ? review : (filter === 'approved' ? approved : arts);
    var html = pageHead('确认中心', '逐份核对初稿：批准定稿（门 B）或提出修改要求；批准后下游会自动续跑。', '', '门 B');
    html += '<div class="tabs">' +
      '<button class="' + (filter === 'review' ? 'on' : '') + '" data-act="review-filter" data-filter="review">待确认<span class="n">' + review.length + '</span></button>' +
      '<button class="' + (filter === 'approved' ? 'on' : '') + '" data-act="review-filter" data-filter="approved">已定稿<span class="n">' + approved.length + '</span></button>' +
      '<button class="' + (filter === 'all' ? 'on' : '') + '" data-act="review-filter" data-filter="all">全部<span class="n">' + arts.length + '</span></button>' +
      '</div>';
    html += '<div class="review-layout"><div><div class="card"><div class="card-head"><h3>' +
      (filter === 'review' ? '待确认' : filter === 'approved' ? '已定稿' : '全部产物') + '</h3><span class="spacer"></span>' +
      '<span class="hint">' + list.length + ' 份</span></div>';
    if (!list.length) {
      html += emptyBox(filter === 'review' ? '没有待确认产物' : '暂无产物',
        filter === 'review' ? '到「生成中心」启动生成，初稿完成后会出现在这里。' : '生成并批准后，产物会保留在这里。');
    } else {
      html += '<div class="list">' + list.map(function (a) {
        var active = Number(S.reviewAid) === Number(a.id);
        return '<div class="list-item" style="cursor:pointer;' + (active ? 'background:var(--gold-soft);border-radius:8px;padding-left:8px;padding-right:8px' : '') +
          '" data-act="review-select" data-id="' + a.id + '">' +
          '<div class="ic">' + (FT[a.file_type] || '?').slice(0, 1) + '</div>' +
          '<div class="bd"><b>第 ' + a.week_no + ' 周 · ' + (FT[a.file_type] || a.file_type) + '</b>' +
          '<span>' + (a.word_count ? fmtNum(a.word_count) + (a.file_type === 'courseware' ? ' 字符 · ' : ' 字 · ') : '') + shortTime(a.updated_at) +
          (a.warnings ? ' · <span style="color:#8a5a12">⚠ 校验提示</span>' : '') + '</span></div>' +
          '<div class="rt">' + badge(a.status) + '</div></div>';
      }).join('') + '</div>';
    }
    html += '</div></div><div id="reviewDetail"><div class="card"><div class="empty"><b>选择左侧一份产物</b>查看渲染内容、校验提示、版本历史，并批准或提出修改要求。</div></div></div></div>';
    el.innerHTML = html;
    var inList = list.some(function (a) { return Number(a.id) === Number(S.reviewAid); });
    if (!inList) S.reviewAid = list.length ? list[0].id : 0;
    if (S.reviewAid) loadReviewArtifact(S.reviewAid);
  }

  async function loadReviewArtifact(aid) {
    try {
      var r = await api('/api/course/' + S.cid + '/artifact/' + aid, { silent: true });
      var box = $('#reviewDetail');
      if (box) box.innerHTML = renderArtifactPanel(r.artifact, false);
    } catch (e) { }
  }

  function renderArtifactPanel(a, inModal) {
    var canReview = a.status === 'review' || a.status === 'revising';
    var issues = a.issues || [];
    var revisions = a.revisions || [];
    var html = '<div class="card"><div class="card-head"><h3>第 ' + a.week_no + ' 周 · ' + h(FT[a.file_type] || a.file_type) + '</h3>' +
      badge(a.status) + '<span class="spacer"></span>' +
      '<span class="hint">' + h(a.model || '') + ' · v' + (a.revision || 1) + '</span></div>';
    if (a.warnings) {
      html += '<div class="note" style="margin-bottom:10px"><b>校验提示：</b>' + h(a.warnings) + '</div>';
    } else if (issues.length) {
      html += '<div class="note" style="margin-bottom:10px"><b>校验提示：</b>' + h(issues.join('；')) + '</div>';
    }
    if (a.file_type === 'courseware') {
      html += '<div class="cw-panel"><iframe src="/api/artifact/' + a.id + '/preview" title="互动课件预览"></iframe></div>' +
        '<div class="help" style="margin-top:7px">预览为可交互 HTML；「打开互动课件」可全屏演示，右侧可导出 PPTX 或下载互动 HTML。</div>';
    } else {
      html += '<div class="doc" style="max-height:' + (inModal ? '52vh' : '640px') + '">' + window.MD.render(a.content || '（内容为空）') + '</div>';
    }
    html += '<div class="row" style="margin-top:12px">';
    if (canReview) {
      html += '<button class="btn" data-act="artifact-approve" data-id="' + a.id + '">批准定稿</button>' +
        '<button class="btn gold" data-act="artifact-revise" data-id="' + a.id + '">提修改要求</button>';
    } else {
      html += '<button class="btn ghost" data-act="artifact-reopen" data-id="' + a.id + '">退回修改</button>';
    }
    html += '<button class="btn ghost" data-act="artifact-reset" data-id="' + a.id + '">重新生成</button>' +
      '<a class="btn ghost" target="_blank" href="/viewer/' + S.cid + '/' + a.id + '">打开查看页</a>' +
      (a.file_type === 'courseware'
        ? '<a class="btn ghost" target="_blank" href="/api/artifact/' + a.id + '/preview">打开互动课件</a>'
        : '<button class="btn ghost" data-act="artifact-print" data-id="' + a.id + '">打印 / PDF</button>') +
      '<span class="spacer"></span>' +
      exportBtns(a) +
      '</div>';
    if (revisions.length) {
      html += '<div style="margin-top:12px"><div class="row"><b style="font-size:12.5px;color:var(--muted)">版本历史</b>' +
        '<span class="spacer"></span><button class="btn link" data-act="artifact-versions" data-id="' + a.id + '">查看全部 ' + revisions.length + ' 个版本</button></div>' +
        '<div class="help" style="margin-top:4px">最新：v' + (a.revision || 1) + ' · 生成/修改/回退都会记录，可一键恢复。</div></div>';
    }
    html += '</div>';
    return html;
  }

  async function openArtifactModal(aid) {
    try {
      var r = await api('/api/course/' + S.cid + '/artifact/' + aid, { silent: true });
      modal({
        title: '第 ' + r.artifact.week_no + ' 周 · ' + (FT[r.artifact.file_type] || r.artifact.file_type),
        wide: true, body: renderArtifactPanel(r.artifact, true),
        footer: '<button class="btn ghost" data-act="modal-close">关闭</button>'
      });
    } catch (e) { }
  }

  function reviseModal(aid) {
    modal({
      title: '提出修改要求', slim: true,
      body: '<div class="help" style="margin-bottom:8px">像和助教说话一样提要求；修改会生成完整新版并保留结构，过程约 30-90 秒。</div>' +
        '<textarea class="textarea" id="reviseText" rows="5" placeholder="例如：导入换成校园快递站排队案例；精简讲授环节；思政点再自然一些。"></textarea>',
      footer: '<button class="btn ghost" data-act="modal-close">取消</button>' +
        '<button class="btn gold" id="reviseGo">提交并修改</button>',
      onOpen: function () {
        $('#reviseGo').onclick = async function () {
          var t = ($('#reviseText').value || '').trim();
          if (!t) { toast('请填写修改要求', 'err'); return; }
          closeModal();
          busy(true);
          var b = document.querySelector('[data-act="artifact-revise"][data-id="' + aid + '"]');
          btnBusy(b, true, '修改中');
          try {
            var r = await api('/api/artifact/' + aid + '/revise', { method: 'POST', body: { feedback: t } });
            toast(r.msg || '已修改', 'ok');
            await refreshBoard();
            if (S.view === 'review') { S.reviewAid = aid; loadReviewArtifact(aid); }
          } catch (e) { }
          finally { busy(false); btnBusy(b, false); }
        };
      }
    });
  }

  async function showVersions(aid) {
    try {
      var r = await api('/api/artifact/' + aid + '/revisions', { silent: true });
      var list = r.revisions || [];
      var body = list.length ? '<div class="list">' + list.map(function (v) {
        return '<div class="list-item"><div class="ic">v' + v.version + '</div><div class="bd"><b>' +
          h(v.feedback || v.source || '版本') + '</b><span>' + shortTime(v.created_at) + ' · ' + fmtNum(v.chars) + ' 字符</span></div>' +
          '<div class="rt"><button class="btn ghost sm" data-act="artifact-restore" data-id="' + aid + '" data-rid="' + v.id + '">恢复</button></div></div>';
      }).join('') + '</div>' : '<div class="help">暂无历史版本。</div>';
      modal({ title: '版本历史', body: body, footer: '<button class="btn ghost" data-act="modal-close">关闭</button>' });
    } catch (e) { }
  }

  async function approveArtifact(aid, btn) {
    btnBusy(btn, true, '批准中');
    try {
      var r = await api('/api/artifact/' + aid + '/approve', { method: 'POST', body: {} });
      toast(r.msg, 'ok');
      if (r.auto && r.auto.started) {
        toast('已自动续跑下游：' + (r.auto.task_id || ''), 'ok');
        await trackTask(r.auto.task_id, true);
      }
      await refreshBoard();
      if (S.view === 'review') {
        var list = (S.board.artifacts || []).filter(function (a) { return a.status === 'review'; });
        S.reviewAid = list.length ? list[0].id : 0;
        renderReview();
      }
      var overlay = $('#overlay');
      if (!overlay.classList.contains('hide')) openArtifactModal(aid);
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  // ================= 交付 =================
  function renderDeliver() {
    var el = $('#v-deliver');
    if (!S.board) { el.innerHTML = pageHead('交付与用量', '请先选择课程。'); return; }
    var b = S.board, arts = b.artifacts || [];
    var approved = arts.filter(function (a) { return a.status === 'approved'; });
    var usage = b.usage || { calls: 0, cost: 0 };
    var html = pageHead('交付与用量', '门 C：确认全部定稿后打包；每份文件也可单独导出 docx / PPTX / 互动 HTML / Markdown。', '', '门 C');
    html += '<div class="grid grid-2 top"><div class="card"><div class="card-head"><h3>整包交付</h3><span class="spacer"></span>' +
      '<span class="hint">' + approved.length + ' 份已定稿</span></div>' +
      '<div class="help" style="line-height:1.9">zip 内含《课程文件夹索引与使用说明》、manifest.json、按周归档的 docx、PPTX、互动 HTML 与 Markdown。未定稿的文件不会打包，避免误用。</div>' +
      '<div class="row" style="margin-top:14px"><button class="btn" data-act="deliver-package">打包并下载</button>' +
      '<button class="btn ghost" data-act="deliver-packages">刷新历史包</button></div>' +
      '<div id="pkgList" class="help" style="margin-top:10px">' +
      (approved.length ? '' : '还没有已定稿文件。先去「确认中心」批准至少一份（门 B）。') + '</div></div>' +
      '<div class="card"><div class="card-head"><h3>用量与费用</h3></div>' +
      '<div class="grid grid-2" style="gap:10px"><div class="stat"><div class="k">模型调用</div><div class="v">' + fmtNum(usage.calls) + '<small>次</small></div></div>' +
      '<div class="stat"><div class="k">估算费用</div><div class="v" style="color:var(--gold)">' + fmtCost(usage.cost) + '</div></div>' +
      '<div class="stat"><div class="k">输入 tokens</div><div class="v" style="font-size:20px">' + fmtNum(usage.in_tokens) + '</div></div>' +
      '<div class="stat"><div class="k">输出 tokens</div><div class="v" style="font-size:20px">' + fmtNum(usage.out_tokens) + '</div></div></div>' +
      '<div class="help" style="margin-top:9px">平均耗时 ' + (usage.avg_latency_ms || 0) + ' ms · 按内置刊例估算，实际以账号账单为准。</div></div></div>';

    // 明细表格
    html += '<div class="card"><div class="card-head"><h3>已定稿文件</h3></div>';
    if (!approved.length) html += emptyBox('暂无可导出文件', '批准后（门 B）即可在此单独下载。');
    else {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>周次</th><th>文件</th><th>字符</th><th>模型</th><th>费用</th><th style="width:210px">导出</th></tr></thead><tbody>';
      approved.forEach(function (a) {
        html += '<tr><td class="mono">第' + a.week_no + '周</td><td class="cell-title">' + h(FT[a.file_type] || a.file_type) + '</td>' +
          '<td class="mono">' + fmtNum(a.word_count) + '</td><td class="help">' + h(a.model || '') + '</td>' +
          '<td class="mono">' + fmtCost(a.cost) + '</td>' +
          '<td class="actions">' + exportBtns(a) + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }
    html += '</div>';

    // 按类型/模型
    var byType = usage.by_type || [], byModel = usage.by_model || [];
    var maxCost = Math.max.apply(null, byType.map(function (x) { return x.cost || 0; }).concat([0.0001]));
    html += '<div class="grid grid-2 top"><div class="card"><div class="card-head"><h3>按文件类型</h3></div>';
    if (!byType.length) html += '<div class="help">暂无调用记录。</div>';
    else html += byType.map(function (x) {
      return '<div style="margin:8px 0"><div class="row" style="font-size:12.5px"><span>' + h(TYPE_CN[x.file_type] || x.file_type || '其他') +
        '</span><span class="spacer"></span><span class="help">' + x.n + ' 次 · ' + fmtCost(x.cost) + '</span></div>' +
        '<div class="progress" style="height:6px;margin-top:4px"><i style="width:' + Math.max(4, Math.round((x.cost || 0) / maxCost * 100)) + '%"></i></div></div>';
    }).join('');
    html += '</div><div class="card"><div class="card-head"><h3>按模型</h3></div>';
    if (!byModel.length) html += '<div class="help">暂无调用记录。</div>';
    else html += '<div class="tbl-wrap"><table class="tbl" style="min-width:0"><thead><tr><th>模型</th><th>调用</th><th>tokens</th><th>费用</th></tr></thead><tbody>' +
      byModel.map(function (x) {
        return '<tr><td class="mono" style="font-size:11px">' + h(x.model) + '</td><td>' + x.n + '</td><td>' + fmtNum(x.tokens) + '</td><td>' + fmtCost(x.cost) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    html += '</div></div>';
    el.innerHTML = html;
    loadPackages();
  }

  async function loadPackages() {
    if (!S.cid) return;
    try {
      var r = await api('/api/course/' + S.cid + '/packages', { silent: true });
      var list = r.packages || [];
      var box = $('#pkgList');
      if (!box) return;
      box.innerHTML = list.length ? '<div class="list">' + list.map(function (p) {
        return '<div class="list-item"><div class="ic">zip</div><div class="bd"><b>' + h(p.filename) + '</b><span>' +
          shortTime(p.ts) + ' · ' + (p.size / 1024).toFixed(0) + ' KB</span></div>' +
          '<div class="rt"><a class="btn ghost sm" href="/api/course/' + S.cid + '/download">下载最新</a></div></div>';
      }).join('') + '</div>' : '<span class="help">还没有历史包。</span>';
    } catch (e) { }
  }

  async function packageCourse(btn) {
    btnBusy(btn, true, '打包中');
    try {
      var r = await api('/api/course/' + S.cid + '/package', { method: 'POST', body: {} });
      toast('已生成：' + r.filename, 'ok');
      await loadPackages();
      window.location.href = '/api/course/' + S.cid + '/download';
    } catch (e) { }
    finally { btnBusy(btn, false); }
  }

  // ================= 公共资源区 =================
  async function loadVault() {
    try { S.vault = await api('/api/vault', { silent: true }); } catch (e) { S.vault = { items: [], kinds: {} }; }
  }

  function renderVault() {
    var el = $('#v-vault');
    var d = S.vault || { items: [], kinds: {} };
    var kinds = d.kinds || {};
    var items = (d.items || []).filter(function (x) { return !S.vaultKind || x.kind === S.vaultKind; });
    var html = pageHead('公共资源区', '全校共享的「怎么写」底座：学校模板、课程标准、方法论、案例与思政素材。生成时按相关性注入，排在课程资料之前。',
      '<button class="btn sm" data-act="vault-add">添加条目</button>');
    html += '<div class="tabs"><button class="' + (!S.vaultKind ? 'on' : '') + '" data-act="vault-kind" data-kind="">全部<span class="n">' + (d.items || []).length + '</span></button>' +
      Object.keys(kinds).map(function (k) {
        var n = (d.items || []).filter(function (x) { return x.kind === k; }).length;
        return '<button class="' + (S.vaultKind === k ? 'on' : '') + '" data-act="vault-kind" data-kind="' + k + '">' + h(kinds[k]) + '<span class="n">' + n + '</span></button>';
      }).join('') + '</div>';
    if (!items.length) html += emptyBox('该分类暂无条目', '可以添加学校模板、方法论或本地案例，保存后所有课程都会共享。');
    else {
      html += '<div class="vault-grid">' + items.map(function (it) {
        return '<div class="vault-card"><div class="kind">' + h(kinds[it.kind] || it.kind) + (it.enabled ? '' : ' · 已停用') + '</div>' +
          '<h4>' + h(it.name) + '</h4><p>' + h(it.content) + '</p>' +
          '<div class="tags">' + (it.tags || '').split(/[,，\s]+/).filter(Boolean).slice(0, 6).map(function (t) { return '<span>' + h(t) + '</span>'; }).join('') + '</div>' +
          '<div class="ops"><button class="btn link" data-act="vault-edit" data-id="' + it.id + '">编辑</button>' +
          '<button class="btn link" data-act="vault-toggle" data-id="' + it.id + '">' + (it.enabled ? '停用' : '启用') + '</button>' +
          '<button class="btn link" style="color:var(--danger)" data-act="vault-del" data-id="' + it.id + '">删除</button></div></div>';
      }).join('') + '</div>';
    }
    html += note('<b>注入顺序：</b>公共资源区（按相关性 Top-' + ((S.sys && S.sys.limits) ? 3 : 3) + '）→ 课程资料原文 → 本次需求。公共库解决「按什么标准写」，课程资料解决「写什么」。');
    el.innerHTML = html;
  }

  function vaultForm(item) {
    var kinds = (S.vault && S.vault.kinds) || {};
    item = item || { kind: 'case', name: '', content: '', tags: '' };
    modal({
      title: item.id ? '编辑公共资源' : '添加公共资源', wide: true,
      body: '<div class="form-grid"><div><label class="f">分类</label><select class="select" id="vKind">' +
        Object.keys(kinds).map(function (k) { return '<option value="' + k + '"' + (item.kind === k ? ' selected' : '') + '>' + h(kinds[k]) + '</option>'; }).join('') +
        '</select></div><div><label class="f">名称</label><input class="input" id="vName" value="' + h(item.name) + '"></div></div>' +
        '<label class="f" style="margin-top:8px">标签（空格/逗号分隔）</label><input class="input" id="vTags" value="' + h(item.tags) + '">' +
        '<label class="f" style="margin-top:8px">内容</label><textarea class="textarea" id="vContent" rows="10">' + h(item.content) + '</textarea>',
      footer: '<button class="btn ghost" data-act="modal-close">取消</button><button class="btn" id="vSave">保存</button>',
      onOpen: function () {
        $('#vSave').onclick = async function () {
          var body = {
            kind: $('#vKind').value, name: $('#vName').value.trim(),
            tags: $('#vTags').value.trim(), content: $('#vContent').value.trim()
          };
          if (!body.name || !body.content) { toast('名称与内容不能为空', 'err'); return; }
          try {
            if (item.id) await api('/api/vault/' + item.id, { method: 'PATCH', body: body });
            else await api('/api/vault', { method: 'POST', body: body });
            closeModal(); toast('已保存', 'ok'); await loadVault(); renderVault();
          } catch (e) { }
        };
      }
    });
  }

  // ================= 提示词框架 =================
  async function loadFrameworks() {
    try { S.frameworks = await api('/api/frameworks', { silent: true }); } catch (e) { S.frameworks = { frameworks: [] }; }
  }

  function renderFrameworks() {
    var el = $('#v-frameworks');
    var list = (S.frameworks && S.frameworks.frameworks) || [];
    var html = pageHead('提示词框架库', '每类文件一套 8 要素框架：角色 / 任务 / 领域规范 / 结构 / 内容深度 / 风格 / 输出格式 / 校验。生成时按框架装配，而不是临时写提示词。');
    if (!list.length) html += emptyBox('框架未加载', '刷新页面或检查后端服务。');
    else html += '<div class="fw-grid">' + list.map(function (f) {
      return '<div class="fw-card" data-act="fw-open" data-id="' + f.id + '"><div class="g">' + h(f.group) + '</div>' +
        '<h4>' + h(f.name) + '</h4><p>' + h(f.desc) + '</p>' +
        '<div class="m"><span class="badge pending">' + h(f.output) + '</span>' +
        (f.gate ? '<span class="badge review">门 ' + h(f.gate) + '</span>' : '') + '</div></div>';
    }).join('') + '</div>';
    html += note('扩展方式：新增文件类型 = 新增一套 8 要素框架 + 注册到技能表 + 挂到依赖链，不改工作流引擎。框架正文可在 <code>app/frameworks.py</code> 维护。');
    el.innerHTML = html;
  }

  async function showFramework(id) {
    try {
      var r = await api('/api/frameworks/' + id, { silent: true });
      var f = r.framework;
      var secs = [['角色 Role', f.role], ['任务 Task', f.task], ['领域规范 Domain', f.domain],
        ['结构 Structure', f.structure], ['内容深度 Depth', f.depth], ['风格 Style', f.style],
        ['输出格式 Format', f.format], ['校验 Validation', f.validation]];
      modal({
        title: f.name, wide: true,
        body: '<div class="help" style="margin-bottom:6px">' + h(f.desc) + '</div>' +
          '<div class="row" style="margin-bottom:8px"><span class="badge pending">' + h(f.output) + '</span>' +
          (f.gate ? '<span class="badge review">确认门 ' + h(f.gate) + '</span>' : '') +
          '<span class="help">占位符以示例值展示，实际生成时按当前课程与周次填充</span></div>' +
          secs.map(function (x) {
            return '<div class="fw-section"><b>' + x[0] + '</b><pre>' + h(x[1]) + '</pre></div>';
          }).join(''),
        footer: '<button class="btn ghost" data-act="modal-close">关闭</button>'
      });
    } catch (e) { }
  }

  // ================= 课程弹窗 / 配置 =================
  function openCourseModal() {
    var list = S.courses || [];
    var rows = list.map(function (c) {
      return '<div class="list-item"><div class="ic">' + h((c.name || '课').slice(0, 1)) + '</div>' +
        '<div class="bd"><b>' + h(c.name) + '</b><span>' + h(c.semester || '') + ' · ' + c.weeks + ' 周 · ' +
        (c.material_cnt || 0) + ' 份资料 · ' + (c.artifact_cnt || 0) + ' 件产物</span></div>' +
        '<div class="rt"><button class="btn ' + (Number(c.id) === Number(S.cid) ? '' : 'ghost') + ' sm" data-act="course-open" data-id="' + c.id + '">' +
        (Number(c.id) === Number(S.cid) ? '当前' : '打开') + '</button> ' +
        '<button class="btn danger sm" data-act="course-delete" data-id="' + c.id + '">删除</button></div></div>';
    }).join('');
    modal({
      title: '课程', wide: true,
      body: (list.length ? '<div class="card-head" style="margin-top:0"><h3 style="font-size:14px">已有课程</h3></div><div class="list">' + rows + '</div><hr style="border:0;border-top:1px solid var(--line);margin:16px 0">' : '') +
        '<div class="card-head" style="margin-top:0"><h3 style="font-size:14px">新建课程</h3></div>' +
        '<div class="form-grid"><div><label class="f">课程名称 *</label><input class="input" id="cName" placeholder="如：新媒体产品设计与制作"></div>' +
        '<div><label class="f">学期</label><input class="input" id="cSem" value="2026-2027-1"></div>' +
        '<div><label class="f">总周数</label><input class="input" id="cWeeks" type="number" min="1" max="30" value="16"></div>' +
        '<div><label class="f">班级</label><input class="input" id="cClass" placeholder="如：网新2531"></div>' +
        '<div><label class="f">教材</label><input class="input" id="cBook" placeholder="如：短视频制作（高教社）"></div>' +
        '<div><label class="f">课程主题 / 要求</label><input class="input" id="cTheme" placeholder="如：镜头语言、脚本结构、剪辑节奏"></div></div>',
      footer: '<button class="btn ghost" data-act="modal-close">关闭</button><button class="btn" id="courseCreate">新建并打开</button>',
      onOpen: function () {
        $('#courseCreate').onclick = async function () {
          var name = ($('#cName').value || '').trim();
          if (!name) { toast('请填写课程名称', 'err'); return; }
          btnBusy(this, true, '创建中');
          try {
            var r = await api('/api/course', {
              method: 'POST', body: {
                name: name, semester: $('#cSem').value, weeks: Number($('#cWeeks').value) || 16,
                theme: $('#cTheme').value, class_name: $('#cClass').value,
                textbook: $('#cBook').value
              }
            });
            closeModal(); toast('课程已创建', 'ok');
            await loadCourses();
            await selectCourse(r.course_id);
          } catch (e) { btnBusy(this, false); }
        };
      }
    });
  }

  function openConfig() {
    var s = S.sys || {};
    var mode = s.mode === 'real';
    modal({
      title: '配置与帮助', wide: true,
      body: '<div class="row" style="margin-bottom:10px"><span class="mode-pill ' + (mode ? 'real' : '') + '" style="background:' + (mode ? 'var(--green-soft)' : 'var(--gold-soft)') + ';color:' + (mode ? 'var(--green)' : '#7a5c12') + ';border-color:var(--line)"><i class="dot"></i>' +
        (mode ? '真实模型已就绪' : '未配置 API Key') + '</span><span class="help">v' + h(s.version) + ' · ' + h(s.school) + '</span></div>' +
        '<div class="note' + (mode ? '' : '') + '">' + h(s.note) + '</div>' +
        '<div class="tbl-wrap" style="margin-top:12px"><table class="tbl"><tbody>' +
        '<tr><th style="width:120px">主模型</th><td>' + h(s.model) + '</td></tr>' +
        '<tr><th>Base URL</th><td class="mono" style="font-size:11.5px">' + h(s.base_url) + '</td></tr>' +
        '<tr><th>轻量模型</th><td>' + h(s.lite_model || '未配置（摘要等短任务走主模型）') + '</td></tr>' +
        '<tr><th>上传上限</th><td>' + (s.limits ? s.limits.max_upload_mb : 20) + ' MB / 份</td></tr>' +
        '<tr><th>模型超时</th><td>' + (s.limits && s.limits.llm_timeout ? s.limits.llm_timeout : 360) + ' 秒 / 次（可在 .env 调 LLM_TIMEOUT）</td></tr>' +
        '<tr><th>自动修复</th><td>' + (s.limits && s.limits.auto_repair ? '开启（校验不通过时自动修复结构一次）' : '关闭') + '</td></tr>' +
        '</tbody></table></div>' +
        '<div class="card-head" style="margin:16px 0 6px"><h3 style="font-size:14px">配置方法</h3></div>' +
        '<div class="help" style="line-height:2">1. 打开项目根目录 <code>.env</code>；<br>2. 填写 <code>LLM_API_KEY</code>（豆包方舟 / DeepSeek / 任意 OpenAI 兼容）；<br>3. 重启服务（关闭窗口重新运行 run.bat）；<br>4. 生成内容全部由大模型产出，未配置时不会用模板冒充。</div>' +
        '<div class="card-head" style="margin:16px 0 6px"><h3 style="font-size:14px">常见问题</h3></div>' +
        '<div class="help" style="line-height:2">· 401/403：Key 无效或未开通模型；豆包与 DeepSeek 的 Key 不通用。<br>· 404：Base URL 只填服务根地址（如 https://ark.cn-beijing.volces.com/api/v3）。<br>· 429 且提示 SetLimitExceeded：模型级「安全体验模式/用量上限」到顶，余额充足也会暂停；请到方舟控制台「开通管理/模型激活」调整或关闭。<br>· 429 且提示 RPM/TPM：短时间请求过多，等待 1–3 分钟再试。<br>· 超时：多为长文生成耗时超过上限，可把 <code>.env</code> 的 <code>LLM_TIMEOUT</code> 调到 420–600 后重启。<br>· 教案导出：A4 横向双表，页眉为学校名称；可在 .env 修改 <code>SCHOOL_NAME</code>。</div>',
      footer: '<button class="btn ghost" data-act="modal-close">关闭</button><button class="btn" onclick="location.reload()">重新检测</button>'
    });
  }

  // ================= 事件分发 =================
  var ACTIONS = {
    'modal-close': function () { closeModal(); },
    'refresh': function () { refreshBoard(); },
    'goto': function (el) { nav(el.dataset.view); },
    'new-course': function () { openCourseModal(); },
    'open-courses': function () { openCourseModal(); },
    'course-open': async function (el) { closeModal(); await selectCourse(Number(el.dataset.id)); },
    'course-delete': function (el) {
      var id = Number(el.dataset.id);
      confirmDlg('删除课程', '将删除该课程的<b>资料、课程地图、全部产物、对话与用量记录</b>，且不可恢复。确定继续？', '删除', async function () {
        try {
          await api('/api/course/' + id, { method: 'DELETE' });
          toast('课程已删除', 'ok');
          await loadCourses();
          if (Number(S.cid) === id) {
            if (S.courses.length) await selectCourse(S.courses[0].id);
            else { S.cid = 0; S.board = null; localStorage.removeItem('kb.cid'); updateShell(); renderHome(); }
          }
        } catch (e) { }
      });
    },
    'material-parse': function (el) { parseMaterials(); },
    'material-upload': function () { uploadFile(); },
    'material-text': async function (el) {
      var name = ($('#matName').value || '').trim() || ('资料' + Date.now());
      var content = ($('#matContent').value || '').trim();
      if (!content) { toast('内容为空', 'err'); return; }
      btnBusy(el, true, '保存中');
      try {
        var r = await api('/api/course/' + S.cid + '/material-text', { method: 'POST', body: { filename: name, content: content } });
        toast(r.msg, 'ok'); $('#matContent').value = ''; await refreshBoard();
      } catch (e) { }
      finally { btnBusy(el, false); }
    },
    'material-view': function (el) { showMaterial(Number(el.dataset.id)); },
    'material-del': function (el) {
      confirmDlg('删除资料', '删除后知识库将不再包含这份资料，已生成的产物不受影响。', '删除', async function () {
        try {
          await api('/api/course/' + S.cid + '/material/' + el.dataset.id, { method: 'DELETE' });
          toast('已删除', 'ok'); await refreshBoard();
        } catch (e) { }
      });
    },
    'plan-gen-toggle': function (el) {
      var w = Number(el.dataset.week);
      if (S.planGenWeeks.has(w)) S.planGenWeeks.delete(w); else S.planGenWeeks.add(w);
      el.classList.toggle('on', S.planGenWeeks.has(w));
    },
    'plan-gen-all': function () {
      S.planGenWeeks = new Set(Array.from({ length: S.board.course.weeks }, function (_, i) { return i + 1; }));
      renderPlan();
    },
    'plan-gen-none': function () { S.planGenWeeks = new Set(); renderPlan(); },
    'plan-generate': function (el) { generatePlan(el); },
    'plan-refresh': function () { refreshBoard(); },
    'plan-rewrite': function (el) { rewriteWeek(Number(el.dataset.week), el); },
    'plan-approve-selected': function (el) { approvePlan(Array.from(S.planSel), el); },
    'plan-approve-all': function (el) {
      var weeks = (S.board.week_plans || []).map(function (p) { return p.week_no; });
      approvePlan(weeks, el);
    },
    'plan-unapprove': function (el) {
      var w = Number(el.dataset.week);
      confirmDlg('退回周次', '退回后该周需要重新批准；已生成的产物不会删除。', '退回', function () {
        savePlanField({ dataset: { week: String(w), field: 'status' }, value: 'review' });
      });
    },
    'gen-toggle': function (el) {
      var w = Number(el.dataset.week);
      if (S.genWeeks.has(w)) S.genWeeks.delete(w); else S.genWeeks.add(w);
      el.classList.toggle('on', S.genWeeks.has(w));
      var c = $('#genCount'); if (c) c.textContent = '将处理 ' + (S.genWeeks.size * S.genTypes.size) + ' 个文件';
    },
    'gen-all': function (el) {
      var weeks = (S.board.week_plans || []).filter(function (p) { return p.status === 'approved'; }).map(function (p) { return p.week_no; });
      S.genWeeks = new Set(weeks); renderBoard();
    },
    'gen-none': function () { S.genWeeks = new Set(); renderBoard(); },
    'gen-start': function (el) { startGenerate(el); },
    'task-track': function (el) { trackTask(el.dataset.id); },
    'task-cancel': function (el) {
      api('/api/task/' + el.dataset.id + '/cancel', { method: 'POST', body: {} }).then(function (r) {
        toast(r.msg || '正在取消', 'ok');
      }).catch(function () { });
    },
    'review-filter': function (el) {
      S.reviewFilter = el.dataset.filter; S.reviewAid = 0; renderReview();
    },
    'review-select': function (el) {
      S.reviewAid = Number(el.dataset.id); renderReview();
    },
    'open-artifact': function (el) { openArtifactModal(Number(el.dataset.id)); },
    'artifact-approve': function (el) { approveArtifact(Number(el.dataset.id), el); },
    'artifact-revise': function (el) { reviseModal(Number(el.dataset.id)); },
    'artifact-reopen': function (el) {
      api('/api/artifact/' + el.dataset.id + '/reopen', { method: 'POST', body: { reason: '退回修改' } })
        .then(function (r) { toast(r.msg, 'ok'); refreshBoard(); }).catch(function () { });
    },
    'artifact-reset': function (el) {
      confirmDlg('重新生成', '将清空当前内容（旧内容会保留在版本历史中），之后可在生成中心重新生成。', '清空', async function () {
        try {
          var r = await api('/api/artifact/' + el.dataset.id + '/reset', { method: 'POST', body: {} });
          toast(r.msg, 'ok'); await refreshBoard();
        } catch (e) { }
      });
    },
    'artifact-versions': function (el) { showVersions(Number(el.dataset.id)); },
    'artifact-print': function (el) {
      window.open('/viewer/' + S.cid + '/' + el.dataset.id + '?print=1', '_blank');
    },
    'artifact-restore': function (el) {
      api('/api/artifact/' + el.dataset.id + '/restore/' + el.dataset.rid, { method: 'POST', body: {} })
        .then(function (r) { toast(r.msg, 'ok'); closeModal(); refreshBoard(); }).catch(function () { });
    },
    'deliver-package': function (el) { packageCourse(el); },
    'deliver-packages': function () { loadPackages(); },
    'vault-kind': function (el) { S.vaultKind = el.dataset.kind; renderVault(); },
    'vault-add': function () { vaultForm(null); },
    'vault-edit': function (el) {
      var item = (S.vault.items || []).filter(function (x) { return Number(x.id) === Number(el.dataset.id); })[0];
      if (item) vaultForm(item);
    },
    'vault-toggle': async function (el) {
      var item = (S.vault.items || []).filter(function (x) { return Number(x.id) === Number(el.dataset.id); })[0];
      if (!item) return;
      try {
        await api('/api/vault/' + item.id, { method: 'PATCH', body: { enabled: !item.enabled } });
        await loadVault(); renderVault();
      } catch (e) { }
    },
    'vault-del': function (el) {
      confirmDlg('删除公共资源', '所有课程将不再注入这条内容。确定删除？', '删除', async function () {
        try {
          await api('/api/vault/' + el.dataset.id, { method: 'DELETE' });
          await loadVault(); renderVault(); toast('已删除', 'ok');
        } catch (e) { }
      });
    },
    'fw-open': function (el) { showFramework(el.dataset.id); },
    'chat-quick': function (el) { sendChat(el.dataset.text); }
  };

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-act]');
    if (!el) return;
    var fn = ACTIONS[el.dataset.act];
    if (fn) {
      if (el.tagName === 'A') e.preventDefault();
      fn(el, e);
    }
  });

  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.classList.contains('plan-check')) {
      var w = Number(t.dataset.week);
      if (t.checked) S.planSel.add(w); else S.planSel.delete(w);
      var info = $('#planSelInfo'); if (info) info.textContent = '已选 ' + S.planSel.size + ' 周';
    }
    if (t.classList.contains('plan-field')) savePlanField(t);
    if (t.classList.contains('gen-type')) {
      if (t.checked) S.genTypes.add(t.value); else S.genTypes.delete(t.value);
      var c = $('#genCount'); if (c) c.textContent = '将处理 ' + (S.genWeeks.size * S.genTypes.size) + ' 个文件';
    }
    if (t.id === 'autoChain') {
      api('/api/course/' + S.cid, { method: 'PATCH', body: { auto_chain: t.checked } })
        .then(function () { toast(t.checked ? '已开启自动续跑' : '已关闭自动续跑', 'ok'); refreshBoard(); })
        .catch(function () { });
    }
    if (t.id === 'planCheckAll') {
      $$('.plan-check').forEach(function (c) {
        c.checked = t.checked;
        var w = Number(c.dataset.week);
        if (t.checked) S.planSel.add(w); else S.planSel.delete(w);
      });
      var info = $('#planSelInfo'); if (info) info.textContent = '已选 ' + S.planSel.size + ' 周';
    }
  });

  document.addEventListener('submit', function (e) {
    if (e.target.id === 'chatForm') {
      e.preventDefault();
      var input = $('#chatInput');
      sendChat(input ? input.value : '');
    }
  });

  document.addEventListener('click', function (e) {
    if (e.target.id === 'overlay') closeModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeModal();
  });

  // 文件选择 / 拖拽
  document.addEventListener('change', function (e) {
    if (e.target.id === 'fileInput') {
      var f = e.target.files[0];
      var line = $('#fileLine');
      if (line) line.textContent = f ? ('已选择：' + f.name + '（' + (f.size / 1024).toFixed(1) + ' KB）') : '';
    }
  });
  document.addEventListener('dragover', function (e) {
    var z = e.target.closest && e.target.closest('#dropZone');
    if (z) { e.preventDefault(); z.classList.add('over'); }
  });
  document.addEventListener('dragleave', function (e) {
    var z = e.target.closest && e.target.closest('#dropZone');
    if (z) z.classList.remove('over');
  });
  document.addEventListener('drop', function (e) {
    var z = e.target.closest && e.target.closest('#dropZone');
    if (!z) return;
    e.preventDefault(); z.classList.remove('over');
    var f = e.dataTransfer.files[0];
    if (!f) return;
    var input = $('#fileInput');
    var dt = new DataTransfer();
    dt.items.add(f);
    input.files = dt.files;
    var line = $('#fileLine');
    if (line) line.textContent = '已选择：' + f.name + '（' + (f.size / 1024).toFixed(1) + ' KB）';
    uploadFile();
  });

  // 静态按钮
  $('#courseSwitch').addEventListener('click', function () { openCourseModal(); });
  $('#btnNewCourse').addEventListener('click', function () { openCourseModal(); });
  $('#btnConfig').addEventListener('click', function () { openConfig(); });
  $('#modalClose').addEventListener('click', function () { closeModal(); });
  $$('#nav button').forEach(function (b) {
    b.addEventListener('click', function () { nav(b.getAttribute('data-view')); });
  });

  // ================= 启动 =================
  (async function init() {
    await Promise.all([loadSys(), loadCourses()]);
    var saved = Number(localStorage.getItem('kb.cid') || 0);
    var exists = S.courses.some(function (c) { return Number(c.id) === saved; });
    if (saved && exists) await selectCourse(saved);
    else if (S.courses.length) await selectCourse(S.courses[0].id);
    else { updateShell(); nav('home'); }
  })();
})();
