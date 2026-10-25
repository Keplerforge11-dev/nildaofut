/* NildãoFut — ranking de palpites, grupos e comentários.
 * Fala com o Supabase (gratuito). A chave abaixo é a chave PÚBLICA (anon): pode ficar no código.
 * Quem protege os dados são as regras do banco (supabase/schema.sql), não esta chave.
 * A chave service_role NUNCA entra aqui: ela só existe como Secret no GitHub. */
(function () {
  'use strict';

  var SUPABASE_URL = 'https://djtqnswhjbixwavbbndx.supabase.co';
  var SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRqdHFuc3doamJpeHdhdmJibmR4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTI4NTQ0NjksImV4cCI6MjEwODQzMDQ2OX0.QjDH16uog7D0bCYEfsDlZTHVAtvdByYgCSd1blO4QxM';
  var TZ = 'America/Sao_Paulo';
  var DAY = 86400000;

  var ERRS = {
    nao_logado: 'Escolha um apelido primeiro.',
    sem_apelido: 'Escolha um apelido primeiro.',
    apelido_tamanho: 'O apelido precisa ter de 3 a 16 letras.',
    apelido_invalido: 'Não use os sinais < > & nem aspas no apelido.',
    apelido_em_uso: 'Esse apelido já é de outra pessoa. Escolha outro.',
    grupo_nome: 'O nome do grupo precisa ter de 2 a 30 letras.',
    limite_grupos: 'Você já criou 10 grupos. Esse é o máximo.',
    tente_de_novo: 'Não deu certo agora. Toque de novo.',
    codigo_invalido: 'Não achei esse código. Confira as 6 letras.',
    removido: 'O dono do grupo tirou você deste grupo.',
    grupo_cheio: 'Esse grupo já está cheio (100 pessoas).',
    dono_nao_sai: 'O dono não pode sair. Se quiser, apague o grupo.',
    sem_permissao: 'Você não pode fazer isso.',
    nao_e_membro: 'Você não está neste grupo.',
    comentario_tamanho: 'A mensagem precisa ter de 1 a 300 letras.',
    muito_rapido: 'Calma! Muitas mensagens seguidas. Espere um minuto.',
    placar_invalido: 'Placar inválido.',
    jogo_nao_encontrado: 'Este jogo ainda não está liberado para palpite. Tente de novo mais tarde.',
    jogo_fechado: 'O jogo já começou: palpite fechado.'
  };

  var S = {
    box: null, champ: {}, sb: null, booted: false, loading: true, fatal: false,
    uid: null, nick: '',
    view: 'hub',            // hub | create | join | group
    hub: 'groups',          // groups | bets
    gtab: 'ranking',        // ranking | comments
    betTab: 'open',         // open | done
    days: 7,
    groups: null, group: null, ranking: null, comments: null,
    games: null, mine: null, preds: {}, draft: {}, cardErr: {},
    form: { nick: '', gname: '', code: '', comment: '' },
    err: '', info: '', busy: false, seq: 0
  };

  // ---------- utilidades ----------
  function esc(x) {
    return String(x == null ? '' : x).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function errText(e) {
    var m = e && e.message ? String(e.message) : '';
    if (ERRS[m]) return ERRS[m];
    if (/schema cache|does not exist|PGRST20|permission denied/i.test(m)) return 'O ranking ainda está sendo preparado. Tente de novo mais tarde.';
    if (/anonymous/i.test(m)) return 'Não consegui criar o seu acesso agora. Tente de novo mais tarde.';
    return 'Não deu certo. Confira a internet e tente de novo.';
  }
  function champName(id) { return S.champ[id] || id; }
  function dayKey(d) { return d.toLocaleDateString('en-CA', { timeZone: TZ }); }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }
  function fmtTime(d) {
    var hh = '00', mm = '00';
    new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(d).forEach(function (p) {
      if (p.type === 'hour') hh = p.value;
      if (p.type === 'minute') mm = p.value;
    });
    return pad2(+hh) + 'h' + mm;
  }
  function dayLabel(d) {
    var k = dayKey(d), now = Date.now();
    var txt = d.toLocaleDateString('pt-BR', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' });
    txt = txt.charAt(0).toUpperCase() + txt.slice(1);
    var badge = k === dayKey(new Date(now)) ? 'HOJE' : k === dayKey(new Date(now + DAY)) ? 'AMANHÃ' : k === dayKey(new Date(now - DAY)) ? 'ONTEM' : '';
    return { text: txt, badge: badge };
  }
  function ago(iso) {
    var d = new Date(iso), s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return 'agora há pouco';
    if (s < 3600) return 'há ' + Math.floor(s / 60) + ' min';
    if (s < 86400) return 'há ' + Math.floor(s / 3600) + ' h';
    return d.toLocaleDateString('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit' }) + ' às ' + fmtTime(d);
  }
  function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }

  // ---------- Supabase ----------
  function client() {
    if (S.sb) return S.sb;
    if (!window.supabase || !window.supabase.createClient) return null;
    S.sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false, storageKey: 'nf-auth' }
    });
    return S.sb;
  }
  async function call(fn, args) {
    var r = await S.sb.rpc(fn, args || {});
    if (r.error) throw r.error;
    return r.data;
  }
  async function loadProfile() {
    var r = await S.sb.from('profiles').select('nickname').eq('id', S.uid).maybeSingle();
    if (r.error) throw r.error;
    S.nick = r.data ? r.data.nickname : '';
  }
  async function loadGroups() { S.groups = await call('my_groups'); }
  async function loadRanking() { S.ranking = await call('group_ranking', { p_group: S.group.id }); }
  async function loadComments() { S.comments = await call('group_comments', { p_group: S.group.id, p_limit: 100 }); }
  async function loadBets() {
    var from = new Date(Date.now() - 6 * 3600000).toISOString();
    var to = new Date(Date.now() + 35 * DAY).toISOString();
    var res = await Promise.all([
      S.sb.from('games').select('key,champ,home,away,kickoff,home_goals,away_goals').gte('kickoff', from).lt('kickoff', to).order('kickoff').limit(300),
      S.sb.rpc('my_predictions')
    ]);
    if (res[0].error) throw res[0].error;
    if (res[1].error) throw res[1].error;
    S.games = res[0].data || [];
    S.mine = res[1].data || [];
    S.preds = {};
    S.mine.forEach(function (p) { S.preds[p.game_key] = { h: p.my_h, a: p.my_a }; });
  }

  async function refresh() {
    var my = ++S.seq;
    if (S.uid && S.nick) {
      try {
        if (S.view === 'hub' && S.hub === 'groups') await loadGroups();
        else if (S.view === 'hub' && S.hub === 'bets') await loadBets();
        else if (S.view === 'group' && S.group) await (S.gtab === 'ranking' ? loadRanking() : loadComments());
      } catch (e) { S.err = errText(e); }
    }
    if (my === S.seq) draw();
  }

  async function boot() {
    var sb = client();
    if (!sb) { S.fatal = true; S.loading = false; draw(); return; }
    draw();
    try {
      var r = await sb.auth.getSession();
      var user = r.data && r.data.session && r.data.session.user;
      if (user) { S.uid = user.id; await loadProfile(); }
    } catch (e) { S.err = errText(e); }
    S.loading = false;
    await refresh();
    setInterval(poll, 30000);
  }
  // mensagens novas aparecem sozinhas enquanto a aba de comentários está aberta
  function poll() {
    if (!S.box || !S.box.isConnected || S.box.closest('[hidden]') || document.hidden) return;
    if (S.view !== 'group' || S.gtab !== 'comments' || S.busy) return;
    var a = document.activeElement;
    if (a && a.id === 'nfComment') return;
    refresh();
  }

  // ---------- telas (HTML) ----------
  function flash() {
    return (S.err ? '<p class="err" role="alert">' + esc(S.err) + '</p>' : '') + (S.info ? '<p class="okmsg" role="status">' + esc(S.info) + '</p>' : '');
  }
  function head(title, lead) {
    return '<div><h1>' + esc(title) + '</h1>' + (lead ? '<p class="lead">' + lead + '</p>' : '') + '</div>';
  }
  function seg(items, active, act) {
    return '<div class="seg" role="group">' + items.map(function (i) {
      return '<button type="button" data-act="' + act + '" data-v="' + i[0] + '" aria-pressed="' + (i[0] === active) + '">' + esc(i[1]) + '</button>';
    }).join('') + '</div>';
  }
  function loadingBox(txt) { return '<div class="empty"><p>' + esc(txt || 'Carregando…') + '</p></div>'; }
  function dis() { return S.busy ? ' disabled' : ''; }

  function viewWelcome() {
    return '<div class="mascot"><img src="nildao.png" alt="Nildão, o personagem do app" width="84"><div class="bubble"><b>Vamos palpitar!</b><span>Escolha um apelido para o pessoal te reconhecer. Não precisa de senha.</span></div></div>' +
      head('Primeiro acesso') +
      '<form class="stack" data-form="nick" novalidate><div class="field"><label for="nfNick">Seu apelido</label>' +
      '<input class="input" id="nfNick" name="nick" maxlength="16" autocomplete="off" autocapitalize="words" value="' + esc(S.form.nick) + '">' +
      '<p class="help">De 3 a 16 letras. Não pode ser igual ao apelido de outra pessoa.</p></div>' + flash() +
      '<button class="cta" type="submit"' + dis() + '>Começar</button></form>' +
      '<p class="note">Seu cadastro fica guardado neste aparelho, sem senha. Se você apagar os dados do app ou trocar de celular, vai precisar de um apelido novo.</p>';
  }

  function viewHub() {
    var h = head('Palpites', 'Olá, <b>' + esc(S.nick) + '</b>!') + seg([['groups', 'Meus grupos'], ['bets', 'Meus palpites']], S.hub, 'hub') + flash();
    return h + (S.hub === 'groups' ? viewGroups() : viewBets());
  }

  function viewGroups() {
    var html = '';
    if (S.groups === null) html = loadingBox();
    else if (!S.groups.length) html = '<div class="empty"><p>Você ainda não está em nenhum grupo. Crie um para a família ou entre com o código que alguém te passou.</p></div>';
    else html = '<div class="stack">' + S.groups.map(function (g) {
      return '<article class="game"><div class="team">' + esc(g.name) + '</div>' +
        '<div class="where-main">' + (g.is_owner ? '<span class="chip free">Dono</span>' : '') + '<span class="chip">' + plural(g.members, 'pessoa', 'pessoas') + '</span></div>' +
        (g.pts == null ? '' : '<div class="mypos">Você está em <b>' + g.pos + 'º lugar</b> · ' + plural(g.pts, 'ponto', 'pontos') + '</div>') +
        '<button class="cta" type="button" data-act="open-group" data-id="' + esc(g.id) + '">Abrir grupo</button></article>';
    }).join('') + '</div>';
    return html + '<button class="cta" type="button" data-act="go-create">Criar grupo</button><button class="cta ghost" type="button" data-act="go-join">Entrar com código</button>';
  }

  function viewCreate() {
    return '<button class="cta ghost mini" type="button" data-act="back-hub">‹ Meus grupos</button>' +
      head('Criar grupo', 'Dê um nome ao grupo. Depois você passa o código para a família e os amigos.') +
      '<form class="stack" data-form="create" novalidate><div class="field"><label for="nfGname">Nome do grupo</label>' +
      '<input class="input" id="nfGname" name="gname" maxlength="30" autocomplete="off" placeholder="Ex.: Família do Nildão" value="' + esc(S.form.gname) + '"></div>' + flash() +
      '<button class="cta" type="submit"' + dis() + '>Criar grupo</button></form>';
  }

  function viewJoin() {
    return '<button class="cta ghost mini" type="button" data-act="back-hub">‹ Meus grupos</button>' +
      head('Entrar com código', 'Peça ao dono do grupo o código de 6 letras e digite aqui.') +
      '<form class="stack" data-form="join" novalidate><div class="field"><label for="nfCode">Código do grupo</label>' +
      '<input class="input code" id="nfCode" name="code" maxlength="6" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="ABCDEF" value="' + esc(S.form.code) + '"></div>' + flash() +
      '<button class="cta" type="submit"' + dis() + '>Entrar no grupo</button></form>';
  }

  function inviteLink(g) {
    var site = new URL('./', location.href).href;
    var txt = 'Vem palpitar comigo no NildãoFut! Entre no grupo "' + g.name + '" com o código ' + g.code + '. Abra o app aqui: ' + site;
    return 'https://wa.me/?text=' + encodeURIComponent(txt);
  }

  function viewGroup() {
    var g = S.group;
    var html = '<button class="cta ghost mini" type="button" data-act="back-hub">‹ Meus grupos</button>' + head(g.name) + flash() +
      '<div class="game codebox"><div class="where-label">CÓDIGO DO GRUPO</div><div class="codebig" aria-label="Código: ' + esc(g.code.split('').join(' ')) + '">' + esc(g.code) + '</div>' +
      '<a class="cta" href="' + esc(inviteLink(g)) + '" target="_blank" rel="noopener">Convidar pelo WhatsApp</a></div>' +
      seg([['ranking', 'Ranking'], ['comments', 'Comentários']], S.gtab, 'gtab');
    html += S.gtab === 'ranking' ? viewRanking() : viewComments();
    html += g.is_owner
      ? '<button class="cta ghost danger" type="button" data-act="delete-group">Apagar este grupo</button>'
      : '<button class="cta ghost danger" type="button" data-act="leave">Sair do grupo</button>';
    return html;
  }

  function viewRanking() {
    if (S.ranking === null) return loadingBox();
    var me = S.group.is_owner;
    return '<button class="cta ghost" type="button" data-act="refresh"' + dis() + '>Atualizar ranking</button>' +
      '<ol class="table">' + S.ranking.map(function (r) {
        return '<li class="trow' + (r.is_me ? ' mine' : '') + '"><span class="pos">' + r.pos + 'º</span><div class="tname"><div class="team' + (r.is_me ? ' mine' : '') + '">' + esc(r.nick) + (r.is_me ? ' (você)' : '') + '</div>' +
          '<div class="tsub">' + plural(r.exatos, 'placar exato', 'placares exatos') + '</div>' +
          (r.is_owner ? '<span class="chip free">Dono</span>' : '') +
          (me && !r.is_owner ? '<button class="cta ghost mini danger" type="button" data-act="remove" data-u="' + esc(r.uid) + '"' + dis() + '>Tirar do grupo</button>' : '') +
          '</div><div class="pts"><b>' + r.pts + '</b><span>pontos</span></div></li>';
      }).join('') + '</ol>' +
      '<p class="note">Placar exato vale 5 pontos. Acertar quem ganha (ou o empate) vale 3. Errar vale 0. Seus palpites valem em todos os seus grupos.</p>';
  }

  function viewComments() {
    var list = S.comments === null ? loadingBox() : !S.comments.length
      ? '<div class="empty"><p>Ainda não tem mensagens. Escreva a primeira!</p></div>'
      : '<div class="stack">' + S.comments.map(function (c) {
        var can = c.is_me || S.group.is_owner;
        return '<article class="game"><div class="cmt-head"><span class="team' + (c.is_me ? ' mine' : '') + '">' + esc(c.nick) + '</span>' + (c.is_owner ? '<span class="chip free">Dono</span>' : '') +
          '<span class="champ">' + esc(ago(c.created_at)) + '</span></div><div class="cmt-body">' + esc(c.body) + '</div>' +
          (can ? '<button class="cta ghost mini" type="button" data-act="del-comment" data-id="' + esc(c.id) + '"' + dis() + '>Apagar mensagem</button>' : '') + '</article>';
      }).join('') + '</div>';
    return '<form class="stack" data-form="comment" novalidate><div class="field"><label for="nfComment">Escreva uma mensagem</label>' +
      '<textarea class="input" id="nfComment" name="comment" maxlength="300" rows="3" placeholder="Ex.: Hoje o Santos ganha!">' + esc(S.form.comment) + '</textarea></div>' +
      '<button class="cta" type="submit"' + dis() + '>Enviar mensagem</button></form>' +
      '<button class="cta ghost" type="button" data-act="refresh"' + dis() + '>Atualizar mensagens</button>' + list;
  }

  // ----- palpites -----
  function draftOf(key) {
    var d = S.draft[key], s = S.preds[key];
    return d || (s ? { h: s.h, a: s.a } : { h: 0, a: 0 });
  }
  function teamRow(key, side, name, val) {
    var k = esc(key), n = esc(name);
    return '<div class="bet-row"><div class="team">' + n + '</div><div class="step">' +
      '<button type="button" class="stepbtn" data-act="step" data-k="' + k + '" data-s="' + side + '" data-d="-1" aria-label="Menos um gol para ' + n + '">−</button>' +
      '<output class="stepval" aria-label="Gols de ' + n + '">' + val + '</output>' +
      '<button type="button" class="stepbtn" data-act="step" data-k="' + k + '" data-s="' + side + '" data-d="1" aria-label="Mais um gol para ' + n + '">+</button></div></div>';
  }
  function betCard(g) {
    var d = draftOf(g.key), s = S.preds[g.key], same = !!s && s.h === d.h && s.a === d.a, k = esc(g.key);
    return '<article class="game" data-card="' + k + '"><div class="row"><div class="champ">' + esc(champName(g.champ)) + '</div><div class="time">' + fmtTime(new Date(g.kickoff)) + '</div></div>' +
      teamRow(g.key, 'h', g.home, d.h) + '<div class="vs">contra</div>' + teamRow(g.key, 'a', g.away, d.a) +
      '<p class="help">O palpite fecha na hora do jogo.</p>' +
      (S.cardErr[g.key] ? '<p class="err" role="alert">' + esc(S.cardErr[g.key]) + '</p>' : '') +
      '<button class="cta' + (same ? ' ghost' : '') + '" type="button" data-act="save-bet" data-k="' + k + '"' + (same ? ' aria-disabled="true"' : '') + '>' + (same ? 'Palpite salvo ✓' : 'Salvar palpite') + '</button></article>';
  }
  function doneCard(p) {
    var d = new Date(p.kickoff), has = p.res_h != null && p.res_a != null;
    var chip = p.pts === 5 ? '<span class="chip free">Placar exato! +5 pontos</span>'
      : p.pts === 3 ? '<span class="chip">Acertou! +3 pontos</span>'
      : p.pts === 0 ? '<span class="chip plain">Errou: 0 pontos</span>'
      : '<span class="chip plain">Aguardando o resultado</span>';
    return '<article class="game"><div class="when">' + esc(dayLabel(d).text) + ' · ' + fmtTime(d) + '</div>' +
      '<div class="team">' + esc(p.home) + ' x ' + esc(p.away) + '</div><div class="champ">' + esc(champName(p.champ)) + '</div>' +
      '<div class="mypos">Seu palpite: <b>' + p.my_h + ' x ' + p.my_a + '</b></div>' +
      '<div class="mypos">Resultado: <b>' + (has ? p.res_h + ' x ' + p.res_a : 'ainda não saiu') + '</b></div>' +
      '<div class="where-main">' + chip + '</div></article>';
  }

  function viewBets() {
    var html = seg([['open', 'Para palpitar'], ['done', 'Resultados']], S.betTab, 'bettab');
    if (S.games === null) return html + loadingBox();
    if (S.betTab === 'done') {
      var done = (S.mine || []).filter(function (p) { return new Date(p.kickoff).getTime() <= Date.now(); });
      var total = done.reduce(function (t, p) { return t + (p.pts || 0); }, 0);
      return html + '<p class="lead">Você tem <b>' + plural(total, 'ponto', 'pontos') + '</b> no total.</p>' +
        (done.length ? '<div class="stack">' + done.map(doneCard).join('') + '</div>' : '<div class="empty"><p>Você ainda não tem jogos encerrados com palpite.</p></div>');
    }
    var now = Date.now(), cut = now + S.days * DAY;
    var all = S.games.filter(function (g) { return new Date(g.kickoff).getTime() > now; });
    var shown = all.filter(function (g) { return new Date(g.kickoff).getTime() < cut; });
    html += '<p class="lead">Escolha o placar e toque em Salvar. Seu palpite vale em todos os seus grupos.</p>';
    if (!all.length) return html + '<div class="empty"><p>Ainda não há jogos liberados para palpite. Eles aparecem aqui sozinhos, pouco depois de a tabela ser atualizada.</p></div>';
    if (!shown.length) html += '<div class="empty"><p>Nenhum jogo nos próximos ' + S.days + ' dias.</p></div>';
    var last = null;
    shown.forEach(function (g) {
      var d = new Date(g.kickoff), k = dayKey(d);
      if (k !== last) {
        if (last !== null) html += '</section>';
        var l = dayLabel(d);
        html += '<section class="day"><div class="day-head">' + (l.badge ? '<span class="badge">' + l.badge + '</span>' : '') + '<span class="day-name">' + esc(l.text) + '</span></div>';
        last = k;
      }
      html += betCard(g);
    });
    if (last !== null) html += '</section>';
    if (all.length > shown.length) html += '<button class="cta ghost" type="button" data-act="more-days">Ver mais 7 dias</button>';
    return html;
  }

  function draw() {
    if (!S.box) return;
    var html;
    if (S.fatal) html = '<div class="empty"><p>Não consegui abrir o ranking agora. Confira a internet e abra o app de novo.</p></div>';
    else if (S.loading) html = head('Palpites') + loadingBox();
    else if (!S.uid || !S.nick) html = viewWelcome();
    else if (S.view === 'create') html = viewCreate();
    else if (S.view === 'join') html = viewJoin();
    else if (S.view === 'group' && S.group) html = viewGroup();
    else html = viewHub();
    S.box.innerHTML = html;
  }

  // ---------- ações ----------
  function go(view) {
    S.view = view; S.err = ''; S.info = '';
    window.scrollTo(0, 0);
  }
  async function run(fn) {
    if (S.busy) return;
    S.busy = true; S.err = ''; S.info = '';
    draw();
    try { await fn(); } catch (e) { S.err = errText(e); }
    S.busy = false;
    draw();
  }
  function openGroup(g, info) {
    S.group = { id: g.id, name: g.name, code: g.code, is_owner: !!g.is_owner };
    S.gtab = 'ranking'; S.ranking = null; S.comments = null;
    go('group');
    S.info = info || '';
    refresh();
  }
  function cardFor(key) {
    var cards = S.box.querySelectorAll('[data-card]');
    for (var i = 0; i < cards.length; i++) if (cards[i].getAttribute('data-card') === key) return cards[i];
    return null;
  }
  function redrawCard(key, focusSel) {
    var card = cardFor(key), g = (S.games || []).filter(function (x) { return x.key === key; })[0];
    if (!card || !g) return;
    card.outerHTML = betCard(g);
    if (focusSel) {
      var c = cardFor(key), b = c && c.querySelector(focusSel);
      if (b) b.focus();
    }
  }

  async function onAction(act, el) {
    var v = el.getAttribute('data-v');
    if (act === 'hub') { S.hub = v; S.err = ''; S.info = ''; draw(); refresh(); }
    else if (act === 'bettab') { S.betTab = v; draw(); }
    else if (act === 'gtab') { S.gtab = v; S.err = ''; S.info = ''; draw(); refresh(); }
    else if (act === 'go-create') { go('create'); draw(); }
    else if (act === 'go-join') { go('join'); draw(); }
    else if (act === 'back-hub') { go('hub'); draw(); refresh(); }
    else if (act === 'refresh') { S.err = ''; S.info = ''; refresh(); }
    else if (act === 'more-days') { S.days += 7; draw(); }
    else if (act === 'open-group') {
      var g = (S.groups || []).filter(function (x) { return x.id === el.getAttribute('data-id'); })[0];
      if (g) openGroup(g);
    }
    else if (act === 'step') {
      var key = el.getAttribute('data-k'), side = el.getAttribute('data-s'), delta = +el.getAttribute('data-d');
      var d = Object.assign({}, draftOf(key));
      d[side] = Math.max(0, Math.min(20, d[side] + delta));
      S.draft[key] = d;
      delete S.cardErr[key];
      redrawCard(key, '[data-act="step"][data-s="' + side + '"][data-d="' + delta + '"]');
    }
    else if (act === 'save-bet') {
      if (el.getAttribute('aria-disabled') === 'true') return;
      var k = el.getAttribute('data-k'), dd = draftOf(k);
      el.disabled = true;
      try {
        await call('save_prediction', { p_game: k, p_home: dd.h, p_away: dd.a });
        S.preds[k] = { h: dd.h, a: dd.a };
        delete S.draft[k]; delete S.cardErr[k];
      } catch (e) {
        S.cardErr[k] = errText(e);
        if (e && e.message === 'jogo_fechado') { await loadBets().catch(function () {}); draw(); return; }
      }
      redrawCard(k, '[data-act="save-bet"]');
    }
    else if (act === 'remove') {
      var u = el.getAttribute('data-u'), r = (S.ranking || []).filter(function (x) { return x.uid === u; })[0];
      if (!r || !window.confirm('Tirar ' + r.nick + ' do grupo?')) return;
      run(async function () { await call('remove_member', { p_group: S.group.id, p_user: u }); await loadRanking(); S.info = r.nick + ' saiu do grupo.'; });
    }
    else if (act === 'leave') {
      if (!window.confirm('Sair do grupo "' + S.group.name + '"?')) return;
      run(async function () { await call('leave_group', { p_group: S.group.id }); go('hub'); S.groups = null; refresh(); });
    }
    else if (act === 'delete-group') {
      if (!window.confirm('Apagar o grupo "' + S.group.name + '" para todos? Isso não pode ser desfeito.')) return;
      run(async function () { await call('delete_group', { p_group: S.group.id }); go('hub'); S.groups = null; refresh(); });
    }
    else if (act === 'del-comment') {
      if (!window.confirm('Apagar esta mensagem?')) return;
      run(async function () { await call('delete_comment', { p_comment: +el.getAttribute('data-id') }); await loadComments(); });
    }
  }

  async function onSubmit(name) {
    if (name === 'nick') {
      var nick = S.form.nick.trim();
      if (nick.length < 3 || nick.length > 16) { S.err = ERRS.apelido_tamanho; draw(); return; }
      run(async function () {
        if (!S.uid) {
          var r = await S.sb.auth.signInAnonymously();
          if (r.error) throw r.error;
          S.uid = r.data.user.id;
        }
        S.nick = await call('set_nickname', { p_nick: nick });
        S.hub = 'groups'; S.view = 'hub'; S.groups = null;
        refresh();
      });
    } else if (name === 'create') {
      var gname = S.form.gname.trim();
      if (gname.length < 2 || gname.length > 30) { S.err = ERRS.grupo_nome; draw(); return; }
      run(async function () {
        var g = await call('create_group', { p_name: gname });
        S.form.gname = '';
        openGroup({ id: g.id, name: g.name, code: g.code, is_owner: true }, 'Grupo criado! Passe o código para quem você quer chamar.');
      });
    } else if (name === 'join') {
      var code = S.form.code.trim().toUpperCase();
      if (code.length !== 6) { S.err = ERRS.codigo_invalido; draw(); return; }
      run(async function () {
        var g = await call('join_group', { p_code: code });
        S.form.code = '';
        openGroup({ id: g.id, name: g.name, code: g.code, is_owner: false }, 'Você entrou no grupo!');
      });
    } else if (name === 'comment') {
      var text = S.form.comment.trim();
      if (!text) { S.err = ERRS.comentario_tamanho; draw(); return; }
      run(async function () {
        await call('post_comment', { p_group: S.group.id, p_body: text });
        S.form.comment = '';
        await loadComments();
      });
    }
  }

  function bind(box) {
    if (box.__nfBound) return;
    box.__nfBound = true;
    box.addEventListener('click', function (e) {
      var el = e.target.closest('[data-act]');
      if (el && box.contains(el)) onAction(el.getAttribute('data-act'), el);
    });
    box.addEventListener('submit', function (e) {
      var f = e.target.closest('[data-form]');
      if (!f) return;
      e.preventDefault();
      onSubmit(f.getAttribute('data-form'));
    });
    box.addEventListener('input', function (e) {
      var t = e.target;
      if (t.id === 'nfNick') S.form.nick = t.value;
      else if (t.id === 'nfGname') S.form.gname = t.value;
      else if (t.id === 'nfComment') S.form.comment = t.value;
      else if (t.id === 'nfCode') { t.value = t.value.replace(/[^A-Za-z]/g, '').toUpperCase(); S.form.code = t.value; }
    });
  }

  // chamado pelo index.html toda vez que a aba "Palpites" abre
  function render(box, opts) {
    S.box = box;
    if (opts && opts.champName) S.champ = opts.champName;
    bind(box);
    if (!S.booted) { S.booted = true; boot(); return; }
    draw();
    refresh();
  }

  window.NFPool = { render: render };
})();
