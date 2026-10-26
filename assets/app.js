/* PL Watch ・ ネタバレなし観戦ノート（フロントエンド）
 * data/ 以下の JSON を読んで描画するだけ。スコア等はそもそもデータに含まれない。 */
(() => {
  "use strict";

  const LS_KEY = "plwatch.v1";
  const PREF_KEYS = ["lock", "oppDefault", "showResult", "showStats", "showVideos", "showNames"];
  const PREF_DEFAULTS = { lock: true, oppDefault: false, showResult: true, showStats: true, showVideos: true, showNames: true };
  const state = {
    teams: [],
    teamId: null,
    fixtures: [],
    roster: new Map(),
    squadHistory: {},
    matchCache: new Map(),
    selected: null,       // eventId
    showOpp: false,
    prefs: load(),
  };

  // ---------------------------------------------------------------- storage
  function normalizePrefs(p) {
    const out = { team: p.team || null, watched: p.watched || {} };
    for (const k of PREF_KEYS) out[k] = (k in p && p[k] !== undefined && p[k] !== null) ? !!p[k] : PREF_DEFAULTS[k];
    return out;
  }
  function load() {
    try { return normalizePrefs(JSON.parse(localStorage.getItem(LS_KEY) || "{}")); }
    catch { return normalizePrefs({}); }
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state.prefs)); } catch { /* private mode など */ }
    cloud.scheduleSave();
  }
  function applyDisplayPrefs() {
    document.body.classList.toggle("hide-names", !state.prefs.showNames);
  }

  // ---------------------------------------------------------------- クラウド同期（Firebase: Google ログイン + Firestore）
  const cloud = {
    user: null, db: null, auth: null, ready: false, timer: null, loading: false,
    init() {
      try {
        if (!window.firebase || !window.PLW_FIREBASE) return;
        firebase.initializeApp(window.PLW_FIREBASE);
        this.auth = firebase.auth();
        this.db = firebase.firestore();
        this.ready = true;
        this.auth.onAuthStateChanged(async user => {
          this.user = user || null;
          renderAuth();
          if (user) await this.pullAndMerge();
        });
        this.auth.getRedirectResult().catch(e => console.warn("redirect result", e));
      } catch (e) { console.warn("firebase init failed", e); }
    },
    async signIn() {
      if (!this.ready) { toast("ログイン機能を読み込めませんでした"); return; }
      const provider = new firebase.auth.GoogleAuthProvider();
      try { await this.auth.signInWithPopup(provider); }
      catch (e) {
        if (/popup/i.test(e.code || "")) { try { await this.auth.signInWithRedirect(provider); } catch (e2) { toast("ログインできませんでした"); } }
        else if (!/cancelled|closed/i.test(e.code || "")) { console.warn(e); toast("ログインできませんでした: " + (e.code || "")); }
      }
    },
    async signOut() { if (this.ready) await this.auth.signOut(); toast("ログアウトしました（記録はこの端末に残ります）"); },
    docRef() { return this.db.collection("users").doc(this.user.uid); },
    // ログイン直後: クラウドの記録と端末の記録を合わせる（観た試合は和集合、設定はクラウド優先）
    async pullAndMerge() {
      if (!this.user) return;
      this.loading = true;
      try {
        const snap = await this.docRef().get();
        const c = snap.exists ? (snap.data() || {}) : {};
        const merged = { ...state.prefs };
        const watched = { ...(state.prefs.watched || {}) };
        for (const [tid, ids] of Object.entries(c.watched || {})) watched[tid] = [...new Set([...(watched[tid] || []), ...(ids || [])])];
        merged.watched = watched;
        if (c.prefs) for (const k of PREF_KEYS) if (k in c.prefs) merged[k] = !!c.prefs[k];
        if (c.team) merged.team = c.team;
        state.prefs = normalizePrefs(merged);
        try { localStorage.setItem(LS_KEY, JSON.stringify(state.prefs)); } catch { /* ignore */ }
        await this.push();
        applyDisplayPrefs();
        if (state.teamId) { renderList(); if (state.selected) { const f = state.fixtures.find(x => x.eventId === state.selected); if (f) renderDetail(f, state.matchCache.get(f.eventId) || null, classify().get(f.eventId)); } }
        toast(`ログインしました: ${this.user.displayName || ""}`);
      } catch (e) { console.warn("cloud pull failed", e); toast("同期に失敗しました（端末の記録を使います）"); }
      finally { this.loading = false; }
    },
    async push() {
      if (!this.user || !this.ready) return;
      const prefs = {}; for (const k of PREF_KEYS) prefs[k] = state.prefs[k];
      await this.docRef().set({ watched: state.prefs.watched || {}, prefs, team: state.prefs.team || null,
        updatedAt: firebase.firestore.FieldValue.serverTimestamp() }, { merge: true });
    },
    scheduleSave() {
      if (!this.user || this.loading) return;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.push().catch(e => console.warn("cloud save failed", e)), 800);
    },
  };
  function renderAuth() {
    const u = cloud.user;
    const b1 = $("#btn-auth"), b2 = $("#btn-auth2"), st = $("#auth-status");
    if (!cloud.ready) { if (b1) b1.style.display = "none"; if (b2) b2.style.display = "none"; if (st) st.textContent = "ログイン機能は現在使えません。記録はこの端末に保存されます。"; return; }
    if (u) {
      const name = u.displayName || u.email || "ログイン中";
      if (b1) b1.innerHTML = `${u.photoURL ? `<img class="avatar" src="${esc(u.photoURL)}" alt="">` : ""}<span>${esc(name.split(" ")[0])}</span>`;
      if (b2) b2.textContent = "ログアウト";
      if (st) st.textContent = `${name} としてログイン中。観た記録と設定はこのアカウントに同期されています。`;
    } else {
      if (b1) b1.textContent = "ログイン";
      if (b2) b2.textContent = "Google でログイン";
      if (st) st.textContent = "ログインすると「観た」記録と設定が PC・スマホで同期され、Google アカウントごとに別々に保存されます。";
    }
  }
  const watchedSet = () => new Set(state.prefs.watched[state.teamId] || []);
  function setWatched(eventId, on) {
    const s = watchedSet();
    on ? s.add(eventId) : s.delete(eventId);
    state.prefs.watched[state.teamId] = [...s];
    save();
  }

  // ---------------------------------------------------------------- helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fetchJson = async (url) => {
    const r = await fetch(url, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  };
  const JST = { timeZone: "Asia/Tokyo" };
  const WD = ["日", "月", "火", "水", "木", "金", "土"];
  function fmtParts(iso) {
    // 日本時間に変換してから各要素を取り出す
    const j = new Date(new Date(iso).toLocaleString("en-US", JST));
    const pad = n => String(n).padStart(2, "0");
    const md = `${j.getMonth() + 1}/${j.getDate()}`;
    const wd = WD[j.getDay()];
    const hm = `${pad(j.getHours())}:${pad(j.getMinutes())}`;
    return { md, wd, hm, full: `${md}(${wd}) ${hm}` };
  }
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2200);
  }
  const shortName = (name) => {
    const parts = String(name || "").trim().split(/\s+/);
    if (parts.length <= 1) return parts[0] || "";
    // "Bruno Fernandes" → "B. Fernandes"、"Matthijs de Ligt" → "M. de Ligt"（長すぎる場合は最後の語だけ）
    const rest = parts.slice(1).join(" ");
    return rest.length <= 12 ? `${parts[0][0]}. ${rest}` : parts[parts.length - 1];
  };
  const initials = (name) => String(name || "").split(/\s+/).map(w => w[0] || "").join("").slice(0, 2).toUpperCase();

  // Transfermarkt の写真はサイズ違いの URL があるので、用途に応じて差し替える（header: 139px、big: 300px）
  const tmSize = (url, size) => (url || "").replace(/\/portrait\/(small|medium|header|big)\//, `/portrait/${size}/`);
  function photoEl(p, cls = "") {
    const num = p.jersey ? `<span class="num">${esc(p.jersey)}</span>` : "";
    const src = tmSize(p.photo, cls === "big" ? "big" : "header");
    const img = p.photo ? `<img src="${esc(src)}" alt="" loading="lazy" onerror="this.remove()">` : "";
    return `<div class="ph ${cls}"><span class="ini">${esc(initials(p.name))}</span>${img}${num}</div>`;
  }
  const playerChip = (p, side = "us", role = "starter") =>
    `<div class="pl" data-pid="${esc(p.id)}" data-side="${side}" data-role="${role}" title="${esc(p.name)} ・ ${esc(p.pos || "")}">${photoEl(p)}<div class="nm">${esc(shortName(p.name))}</div></div>`;

  async function loadMatch(eventId) {
    if (state.matchCache.has(eventId)) return state.matchCache.get(eventId);
    try {
      const m = await fetchJson(`data/${state.teamId}/matches/${eventId}.json`);
      state.matchCache.set(eventId, m);
      return m;
    } catch (e) { console.warn(e); return null; }
  }

  // ---------------------------------------------------------------- 選手詳細
  const POS_JA = { G: "GK", GK: "GK", D: "DF", M: "MF", F: "FW", LB: "左SB", RB: "右SB", CB: "CB", CD: "CB", "CD-L": "左CB", "CD-R": "右CB", SW: "スイーパー",
    LWB: "左WB", RWB: "右WB", DM: "守備的MF", CDM: "守備的MF", CM: "セントラルMF", LM: "左MF", RM: "右MF", AM: "トップ下", CAM: "トップ下",
    "AM-L": "左の攻撃的MF", "AM-R": "右の攻撃的MF", LW: "左WG", RW: "右WG", ST: "CF", CF: "CF", FW: "FW", SS: "セカンドトップ" };
  const posJa = a => POS_JA[(a || "").toUpperCase()] || a || "";
  const normName = s => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  let plIndex = null, absencesCfg = null;
  const careersCache = new Map();
  const videosCache = new Map();
  // 相手チームの選手用（チーム横断の共有ファイル）
  let oppCareers = null, oppVideos = null;
  async function getOppCareers() {
    if (!oppCareers) { try { oppCareers = (await fetchJson("data/opponents/careers.json")).players || {}; } catch { oppCareers = {}; } }
    return oppCareers;
  }
  async function getOppVideos() {
    if (!oppVideos) { try { oppVideos = await fetchJson("data/opponents/videos.json"); } catch { oppVideos = { enabled: false, players: {} }; } }
    return oppVideos;
  }
  async function getVideos() {
    if (!videosCache.has(state.teamId)) {
      try { videosCache.set(state.teamId, await fetchJson(`data/${state.teamId}/videos.json`)); }
      catch { videosCache.set(state.teamId, { enabled: false, players: {} }); }
    }
    return videosCache.get(state.teamId);
  }
  // YouTube API のタイトルは HTML エンティティ（&#39; など）入りで返るので元に戻す
  const decodeEntities = s => { const t = document.createElement("textarea"); t.innerHTML = String(s || ""); return t.value; };
  function renderVideos(name, entry, enabled) {
    const q = encodeURIComponent(`${name} skills`);
    const link = `<a class="yt-link" href="https://www.youtube.com/results?search_query=${q}" target="_blank" rel="noopener noreferrer">▶ YouTube でプレー動画を探す ↗</a>
      <p class="note" style="margin:4px 0 0">⚠ YouTube の検索結果には、試合結果やスコアを含む動画のタイトル・サムネイルが並ぶことがあります。観ていない試合がある時期はご注意ください。</p>`;
    const vids = (entry && entry.videos) || [];
    let grid = "";
    if (vids.length) {
      grid = `<div class="vids">${vids.map(v => { const t = decodeEntities(v.title); return `<div class="vid" data-vid="${esc(v.id)}" title="${esc(t)}">
          <img src="https://i.ytimg.com/vi/${esc(v.id)}/mqdefault.jpg" alt="" loading="lazy"><span class="play">▶</span>
          <div class="vt">${esc(t)}</div></div>`; }).join("")}</div>
        <p class="note">タイトルに試合結果を含みそうな動画は除いていますが、完全ではありません。</p>`;
    } else if (enabled) {
      grid = `<p class="note">条件に合う動画が見つかりませんでした。</p>`;
    } else {
      grid = `<p class="note">サイト内再生は YouTube API キーを設定すると有効になります（README 参照）。</p>`;
    }
    return `<div class="sec"><h3>プレー動画</h3>${grid}${link}</div>`;
  }
  function bindVideoClicks(root) {
    root.querySelectorAll(".vid").forEach(v => v.addEventListener("click", () => {
      const id = v.dataset.vid;
      v.outerHTML = `<div class="vid playing"><iframe src="https://www.youtube-nocookie.com/embed/${esc(id)}?rel=0&modestbranding=1&autoplay=1" title="YouTube video" allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe></div>`;
    }));
  }
  async function getCareers() {
    if (!careersCache.has(state.teamId)) {
      try { careersCache.set(state.teamId, (await fetchJson(`data/${state.teamId}/careers.json`)).players || {}); }
      catch { careersCache.set(state.teamId, {}); }
    }
    return careersCache.get(state.teamId);
  }
  function renderCareer(entry) {
    if (!entry) return `<div class="sec"><h3>経歴</h3><p class="note">経歴情報はまだ取得されていません（次回の自動更新で追加されます）。</p></div>`;
    const list = entry.career || [];
    if (!entry.qid || !list.length) return `<div class="sec"><h3>経歴</h3><p class="note">経歴情報なし（Wikidata に登録がありません）</p></div>`;
    const clubs = list.filter(c => !c.national), nats = list.filter(c => c.national);
    const row = c => {
      const cur = !c.end && !c.national;
      const tags = [c.loan ? "ローン" : "", c.youth ? "ユース" : ""].filter(Boolean).map(t => `<span class="ctag">${t}</span>`).join("");
      const logo = c.logo ? `<img class="clogo" src="${esc(c.logo)}" alt="" loading="lazy" onerror="this.remove()">` : `<span class="clogo blank"></span>`;
      return `<div class="crow ${cur ? "cur" : ""}"><span class="cy">${esc(c.start || "?")}〜${c.end ? esc(c.end) : "現在"}</span>${logo}<span class="cn">${esc(c.club)}${tags}</span>${c.apps != null ? `<span class="ca">${esc(c.apps)}試合</span>` : ""}</div>`;
    };
    return `<div class="sec"><h3>経歴 <small>所属クラブ</small></h3>${clubs.map(row).join("") || `<p class="note">クラブ情報なし</p>`}
      ${nats.length ? `<h3 style="margin-top:10px">代表</h3>${nats.map(row).join("")}` : ""}
      <p class="note" style="margin:8px 0 0">出典: Wikidata</p></div>`;
  }
  async function getPlIndex() { if (!plIndex) { try { plIndex = (await fetchJson("data/pl-players.json")).players || {}; } catch { plIndex = {}; } } return plIndex; }
  async function getAbsences() { if (!absencesCfg) { try { absencesCfg = await fetchJson("absences.json"); } catch { absencesCfg = {}; } } return absencesCfg; }
  function lookupIndex(name, idx) {
    const n = normName(name);
    if (idx[n]) return idx[n];
    const last = n.split(" ").pop();
    const hits = Object.values(idx).filter(r => normName(r.name).split(" ").pop() === last);
    return hits.length === 1 ? hits[0] : null;
  }
  function ageFrom(dob) {
    if (!dob) return null;
    const b = new Date(dob + "T00:00:00Z"), n = new Date();
    let a = n.getUTCFullYear() - b.getUTCFullYear();
    const m = n.getUTCMonth() - b.getUTCMonth();
    if (m < 0 || (m === 0 && n.getUTCDate() < b.getUTCDate())) a--;
    return a;
  }
  const fmtDate = iso => { if (!iso) return ""; const [y, m, d] = iso.split("-"); return `${y}年${+m}月${+d}日`; };
  const flagImg = code => code ? `<img class="flag" src="https://flagcdn.com/w40/${esc(code.toLowerCase())}.png" alt="" onerror="this.remove()">` : "";

  async function openPlayer(p, ctx) {
    const dlg = $("#dlg-player"), box = $("#player-body");
    box.innerHTML = `<div class="empty">読み込み中...</div>`;
    if (!dlg.open) dlg.showModal();
    const ours = ctx.side !== "opp";
    let bio = ours ? (state.roster.get(p.id) || null) : null;
    if (!bio || !bio.dob) {
      const r = lookupIndex(p.name, await getPlIndex());
      if (r) bio = { ...r, ...(bio || {}), dob: (bio && bio.dob) || r.dob, photo: (bio && bio.photo) || r.photo };
    }
    bio = bio || {};
    const photo = p.photo || bio.photo;

    let role = "";
    if (ctx.role === "starter") role = `先発 ・ ${esc(posJa(p.pos))}`;
    else if (ctx.role === "bench") role = "ベンチ";
    else if (ctx.role === "absent") {
      const r = resolveReason(p, ctx.matchDate || "");
      role = `メンバー外 ・ ${esc(r.type || "理由不明")}${r.reason ? " ・ " + esc(r.reason) : ""}`;
    }

    // 今季の出場状況（自チームのみ、観た試合＋次に観る試合の範囲）
    let season = "";
    if (ours) {
      const kinds = classify();
      const vis = state.fixtures.filter(f => f.hasLineup && ["watched", "current", "open"].includes(kinds.get(f.eventId)));
      const ms = await Promise.all(vis.map(f => loadMatch(f.eventId)));
      let st = 0, be = 0, ab = 0;
      ms.forEach(m => {
        if (!m || !m.team) return;
        if (m.team.starters.some(x => x.id === p.id)) st++;
        else if (m.team.bench.some(x => x.id === p.id)) be++;
        else if ((m.absentees || []).some(x => x.id === p.id)) ab++;
      });
      season = `<div class="sec"><h3>今季の出場状況<small>観た試合＋次に観る試合の ${vis.length} 試合分</small></h3>
        <div class="stats"><div><b>${st}</b><span>先発</span></div><div><b>${be}</b><span>ベンチ</span></div><div><b>${ab}</b><span>メンバー外</span></div></div></div>`;
    }

    // 経歴（Wikidata。相手チームの選手は共有キャッシュから）
    const career = renderCareer((ours ? await getCareers() : await getOppCareers())[p.id]);

    // プレー動画（埋め込み候補＋検索リンク。設定で非表示にもできる）
    let videos = "";
    if (state.prefs.showVideos) {
      const vdata = ours ? await getVideos() : await getOppVideos();
      videos = renderVideos(p.name, (vdata.players || {})[p.id], !!vdata.enabled);
    }

    // 欠場の記録（手入力分 ＋ Transfermarkt の負傷履歴）
    let absHist = "";
    if (ours) {
      const cfg = await getAbsences();
      const manual = (cfg[state.teamId] || []).filter(e => nameMatches(p.name, e.name)).map(e => ({ type: e.type || "欠場", reason: e.reason || "", from: e.from, until: e.until, src: "手入力" }));
      const auto = injuryEntriesFor(p.name).map(e => ({ type: e.type || "負傷", reason: e.reasonJa || e.reason || "", from: e.since, until: e.active ? e.until : (e.until || e.lastSeen), src: e.active ? "現在" : "復帰済み" }));
      const list = [...manual, ...auto].sort((a, b) => (b.from || "").localeCompare(a.from || ""));
      if (list.length) absHist = `<div class="sec"><h3>欠場の記録</h3>${list.map(e =>
        `<div class="abs-row"><b>${esc(e.type)}</b> ${esc(e.reason)} <span class="ctag">${esc(e.src)}</span><small>${e.from ? fmtDate(e.from) : ""}${(e.from || e.until) ? " 〜 " : ""}${e.until ? fmtDate(e.until) : ""}</small></div>`).join("")}</div>`;
    }

    const age = ageFrom(bio.dob);
    const facts = [
      age != null ? ["年齢", `${age}歳（${fmtDate(bio.dob)}）`] : null,
      bio.nat ? ["国籍", `${flagImg(bio.natCode)} ${esc(bio.nat)}`] : null,
      bio.height ? ["身長", `${esc(bio.height)} cm`] : null,
      bio.birthPlace ? ["出身地", esc(bio.birthPlace)] : null,
      bio.joined ? ["加入", fmtDate(bio.joined)] : null,
      (!ours && bio.team) ? ["所属", esc(bio.team)] : null,
    ].filter(Boolean);
    box.innerHTML = `
      <div class="p-head">${photoEl({ ...p, photo }, "big")}<div>
        <div class="p-name">${esc(p.name)}</div>
        <div class="p-sub">${p.jersey ? `#${esc(p.jersey)} ・ ` : ""}${esc(bio.posInfo || posJa(p.pos))}</div>
        ${role ? `<div class="p-role">${role}</div>` : ""}</div></div>
      ${facts.length ? `<div class="sec facts">${facts.map(([k, v]) => `<div><span>${k}</span><b>${v}</b></div>`).join("")}</div>` : `<p class="note">プロフィール情報はまだ取得できていません。</p>`}
      ${season}${career}${videos}${absHist}`;
    bindVideoClicks(box);
  }

  // ---------------------------------------------------------------- 状態分類
  // avail = スタメンがある or 開始済みの試合。未視聴の最初の1試合が「次に観る」、それ以降はロック。
  function classify() {
    const watched = watchedSet();
    const avail = state.fixtures.filter(f => f.status === "played" || f.hasLineup);
    const curIdx = avail.findIndex(f => !watched.has(f.eventId));
    const map = new Map();
    avail.forEach((f, i) => {
      let k;
      if (watched.has(f.eventId)) k = "watched";
      else if (i === curIdx) k = "current";
      else if (state.prefs.lock && curIdx >= 0 && i > curIdx) k = "locked";
      else k = "open";
      map.set(f.eventId, k);
    });
    state.fixtures.forEach(f => { if (!map.has(f.eventId)) map.set(f.eventId, f.status === "postponed" ? "postponed" : "upcoming"); });
    return map;
  }

  // ---------------------------------------------------------------- 描画: 一覧
  function fixtureRow(f, kind, big = false) {
    const t = fmtParts(f.date);
    const ha = f.isHome ? "ホーム" : "アウェイ";
    let badge = "", crest = `<img class="crest" src="${esc(f.opponent.logo)}" alt="" loading="lazy">`;
    const compTag = f.compShort && f.compShort !== "PL" ? `<span class="comp">${esc(f.compShort)}</span>` : "";
    let opp = esc(f.opponent.name) + compTag, sub = `${ha} ・ ${esc(f.competition)}`;
    if (kind === "current") badge = `<span class="badge ok">${f.hasLineup ? "スタメン公開" : "次に観る"}</span>`;
    else if (kind === "watched") badge = `<span class="badge dim">観た ✓</span>`;
    else if (kind === "open") badge = `<span class="badge">${f.hasLineup ? "スタメン公開" : "未視聴"}</span>`;
    else if (kind === "locked") {
      badge = "";
      sub = `${ha} ・ スタメンは前の試合を観ると表示`;
    } else if (kind === "postponed") badge = `<span class="badge warn">延期</span>`;
    else badge = `<span class="badge dim">予定</span>`;
    const clickable = kind !== "locked";
    // 一覧から直接「観た」にできるボタン
    let btn = "";
    if (kind === "current" || kind === "open") btn = `<button class="row-btn" data-act="watch" title="この試合を観た">✓ 観た</button>`;
    else if (kind === "locked") btn = `<button class="row-btn" data-act="upto" title="この試合まで全部観たことにする">ここまで観た</button>`;
    else if (kind === "watched") btn = `<button class="row-btn ghost" data-act="unwatch" title="未視聴に戻す">戻す</button>`;
    return `<div class="fx ${esc(kind)} ${big ? "big" : ""} ${clickable ? "clickable" : ""} ${state.selected === f.eventId ? "selected" : ""}" data-id="${esc(f.eventId)}" ${clickable ? 'role="button" tabindex="0"' : ""}>
      <div class="d">${esc(t.md)}<small>${esc(t.wd)} ${esc(t.hm)}</small></div>
      ${kind === "locked" ? `<div class="crest-lock">${crest}<span class="lockic small">🔒</span></div>` : crest}
      <div class="o">${opp}<small>${sub}</small></div><div class="side">${badge}${btn}</div></div>`;
  }

  function renderList() {
    const kinds = classify();
    const by = k => state.fixtures.filter(f => kinds.get(f.eventId) === k);
    const current = by("current")[0];
    const watched = by("watched").slice().reverse();
    const locked = by("locked");
    const open = by("open");
    const upcoming = state.fixtures.filter(f => ["upcoming", "postponed"].includes(kinds.get(f.eventId)));
    let html = "";

    html += `<div class="section-label">次に観る試合</div>`;
    if (current) {
      html += `<div class="card">${fixtureRow(current, "current", true)}</div>`;
    } else if (upcoming[0]) {
      html += `<div class="card">${fixtureRow(upcoming[0], "upcoming", true)}</div><p class="hint">スタメンはキックオフ約1時間前から表示されます。</p>`;
    } else {
      html += `<div class="card"><div class="ghost-row">試合がありません</div></div>`;
    }
    if (open.length) {
      html += `<div class="section-label">未視聴の試合 <span class="count">${open.length}</span></div><div class="card">${open.map(f => fixtureRow(f, "open")).join("")}</div>`;
    }
    if (locked.length) {
      html += `<div class="section-label">その後の試合 <span class="count">${locked.length}</span></div><div class="card">${locked.map(f => fixtureRow(f, "locked")).join("")}</div>`;
    }
    const future = current || open.length ? upcoming : upcoming.slice(1);
    if (future.length) {
      html += `<div class="section-label">今後の日程 <span class="count">${future.length}</span></div><div class="card">${future.map(f => fixtureRow(f, kinds.get(f.eventId))).join("")}</div>`;
    }
    if (watched.length) {
      html += `<div class="section-label">観た試合 <span class="count">${watched.length}</span></div><div class="card">${watched.map(f => fixtureRow(f, "watched")).join("")}</div>`;
    }
    const el = $("#list");
    el.innerHTML = html;
    el.querySelectorAll(".fx.clickable").forEach(row => {
      const go = (e) => { if (e.target.closest(".row-btn")) return; openMatch(row.dataset.id); };
      row.addEventListener("click", go);
      row.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(e); } });
    });
    el.querySelectorAll(".row-btn").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      const id = b.closest(".fx").dataset.id;
      const f = state.fixtures.find(x => x.eventId === id);
      if (!f) return;
      if (b.dataset.act === "watch") { setWatched(id, true); toast("観た試合に記録しました"); }
      else if (b.dataset.act === "unwatch") { setWatched(id, false); toast("未視聴に戻しました"); }
      else if (b.dataset.act === "upto") {
        const n = state.fixtures.filter(x => x.date <= f.date && (x.status === "played" || x.hasLineup) && !watchedSet().has(x.eventId)).length;
        if (!confirm(`${fmtParts(f.date).md} の試合までの ${n} 試合をすべて「観た」にしますか？`)) return;
        state.fixtures.filter(x => x.date <= f.date && (x.status === "played" || x.hasLineup)).forEach(x => setWatched(x.eventId, true));
        toast(`${n} 試合を「観た」に記録しました`);
      }
      renderList();
      // 詳細を開いていたら、その表示も最新の状態に合わせる
      if (state.selected) {
        const sf = state.fixtures.find(x => x.eventId === state.selected);
        const sm = state.matchCache.get(state.selected) || null;
        if (sf) renderDetail(sf, sm, classify().get(sf.eventId));
      }
    }));
  }

  // ---------------------------------------------------------------- 描画: 詳細
  async function openMatch(eventId) {
    const f = state.fixtures.find(x => x.eventId === eventId);
    if (!f) return;
    const kind = classify().get(eventId);
    if (kind === "locked") { toast("前の試合を「観た」にすると見られます"); return; }
    state.selected = eventId;
    state.showOpp = state.prefs.oppDefault;
    state.statsShown = null;  // 別の試合を開いたらスタッツは隠し直す
    state.resultShown = null; // 結果も同様
    document.body.classList.add("show-detail");
    renderList();
    const el = $("#detail");
    el.innerHTML = `<button class="back" id="btn-back">‹ 一覧へ</button><div class="empty">読み込み中...</div>`;
    bindBack();
    const m = f.hasLineup ? await loadMatch(eventId) : null;
    renderDetail(f, m, kind);
    if (window.innerWidth < 900) window.scrollTo({ top: 0 });
  }

  function bindBack() {
    const b = $("#btn-back");
    if (b) b.addEventListener("click", () => { document.body.classList.remove("show-detail"); state.selected = null; renderList(); });
  }

  function renderDetail(f, m, kind) {
    const t = fmtParts(f.date);
    const ha = f.isHome ? "ホーム" : "アウェイ";
    const watched = kind === "watched";
    let badge = watched ? `<span class="badge dim">観た ✓</span>` : f.hasLineup ? `<span class="badge ok">スタメン公開</span>` : `<span class="badge dim">スタメン未発表</span>`;
    let html = `<button class="back" id="btn-back">‹ 一覧へ</button>
      <div class="section-label">${watched ? "観た試合" : kind === "current" ? "次に観る試合" : "試合"}</div>
      <div class="card">
        <div class="match-head"><img class="crest" src="${esc(f.opponent.logo)}" alt="">
          <div><div class="vs">${esc(ha)} ・ ${esc(f.competition)}${f.venue ? " ・ " + esc(f.venue) : ""}</div>
          <div class="opp">vs ${esc(f.opponent.name)}</div>
          <div class="when">${esc(t.full)} キックオフ（日本時間）</div></div>${badge}</div>`;

    if (m && m.team) {
      const side = state.showOpp && m.opponent && m.opponent.starters ? m.opponent : m.team;
      const ourName = state.teams.find(x => x.id === state.teamId)?.shortName || "自チーム";
      html += `<div class="formation-bar"><span>フォーメーション</span><b>${esc(side.formation || "—")}</b><span class="spacer"></span>
        ${m.opponent && m.opponent.starters ? `<span class="seg"><button data-side="us" class="${state.showOpp ? "" : "on"}">${esc(ourName)}</button><button data-side="opp" class="${state.showOpp ? "on" : ""}">${esc(f.opponent.abbr || "相手")}</button></span>` : ""}</div>`;
      const sk = state.showOpp ? "opp" : "us";
      html += renderPitch(side, sk);
      html += `<div class="section-label" style="margin-top:4px">ベンチ <span class="count">${side.bench.length}</span></div><div class="bench">${side.bench.map(p => playerChip(p, sk, "bench")).join("")}</div></div>`;
      if (!state.showOpp) html += renderAbsentees(m.absentees || [], f.date);
      else html += `<p class="hint">相手チームの欠場者情報は取得していません。</p>`;
    } else {
      html += `<div class="lock-msg"><div class="big">⏳</div>スタメンはまだ発表されていません。<br>キックオフ約1時間前以降の自動更新で表示されます。</div></div>`;
    }

    // スタッツ（ボタンを押すまで隠す。設定で非表示にもできる）
    if (f.hasStats && m && state.prefs.showStats) {
      const shown = state.statsShown && state.statsShown.eventId === f.eventId ? state.statsShown.which : null;
      html += `<div class="section-label">スタッツ</div><div class="card stats-card">
        <div class="stats-btns">
          <button class="stats-btn ${shown === "ht" ? "on" : ""}" data-which="ht">ハーフタイム時のスタッツを表示</button>
          <button class="stats-btn ${shown === "ft" ? "on" : ""}" data-which="ft">試合終了時のスタッツを表示</button>
        </div>
        <div id="stats-body">${shown ? `<div class="empty">読み込み中...</div>` : `<p class="hint" style="margin:0 16px 12px">数字から試合展開を推測できる場合があります。見るときだけ押してください。</p>`}</div></div>`;
    }

    // 結果（確認つきボタンを押すまで、ファイルすら読まない。設定で非表示にもできる）
    if (f.hasResult && m && state.prefs.showResult) {
      const shown = state.resultShown === f.eventId;
      html += `<div class="section-label">結果</div><div class="card result-card">
        ${shown ? `<div id="result-body"><div class="empty">読み込み中...</div></div>`
                : `<div class="stats-btns"><button class="stats-btn danger" id="btn-result">結果を表示</button></div>
                   <p class="hint" style="margin:0 16px 12px">スコアと得点者、退場者が表示されます。押す前に確認が出ます。</p>`}</div>`;
    }

    if (f.status === "played" || f.hasLineup) {
      html += watched
        ? `<button class="watch-btn done" id="btn-watch" data-on="0">観た ✓ （タップで未視聴に戻す）</button>`
        : `<button class="watch-btn" id="btn-watch" data-on="1">✓ この試合を観た</button>`;
      const earlier = state.fixtures.filter(x => x.date < f.date && (x.status === "played" || x.hasLineup) && !watchedSet().has(x.eventId));
      if (!watched && earlier.length) {
        html += `<button class="watch-btn done" id="btn-watch-upto">この試合とそれ以前の ${earlier.length + 1} 試合をまとめて「観た」にする</button>`;
      }
    }
    const el = $("#detail");
    el.innerHTML = html;
    bindBack();
    el.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => { state.showOpp = b.dataset.side === "opp"; renderDetail(f, m, kind); }));
    // スタッツのボタン
    el.querySelectorAll(".stats-btn[data-which]").forEach(b => b.addEventListener("click", () => {
      const which = b.dataset.which;
      const cur = state.statsShown && state.statsShown.eventId === f.eventId ? state.statsShown.which : null;
      state.statsShown = cur === which ? null : { eventId: f.eventId, which };
      renderDetail(f, m, kind);
    }));
    const sb = $("#stats-body");
    if (sb && state.statsShown && state.statsShown.eventId === f.eventId) {
      const which = state.statsShown.which;
      loadStats(f.eventId).then(st => {
        if (!$("#stats-body") || !state.statsShown || state.statsShown.eventId !== f.eventId) return;
        $("#stats-body").innerHTML = renderStats(st, which, f);
      });
    }
    // 結果ボタン
    const rb = $("#btn-result");
    if (rb) rb.addEventListener("click", () => {
      if (!confirm("この試合の結果（スコア・得点者）を表示します。本当によろしいですか？")) return;
      state.resultShown = f.eventId;
      renderDetail(f, m, kind);
    });
    if ($("#result-body") && state.resultShown === f.eventId) {
      loadResult(f.eventId).then(r => { if ($("#result-body") && state.resultShown === f.eventId) $("#result-body").innerHTML = renderResult(r, f); });
    }
    // 選手の写真 → 詳細ポップアップ
    el.querySelectorAll("[data-pid]").forEach(c => c.addEventListener("click", () => {
      if (!m) return;
      const { pid, side: sk, role } = c.dataset;
      const src = sk === "opp" ? m.opponent : m.team;
      const p = role === "absent" ? (m.absentees || []).find(x => x.id === pid) : src && [...src.starters, ...src.bench].find(x => x.id === pid);
      if (p) openPlayer(p, { side: sk, role, matchDate: f.date });
    }));
    const wu = $("#btn-watch-upto");
    if (wu) wu.addEventListener("click", () => {
      state.fixtures.filter(x => x.date <= f.date && (x.status === "played" || x.hasLineup)).forEach(x => setWatched(x.eventId, true));
      toast("ここまでの試合を「観た」に記録しました");
      renderList();
      renderDetail(f, m, classify().get(f.eventId));
    });
    const wb = $("#btn-watch");
    if (wb) wb.addEventListener("click", () => {
      const on = wb.dataset.on === "1";
      setWatched(f.eventId, on);
      toast(on ? "観た試合に記録しました。次の試合が解放されます" : "未視聴に戻しました");
      const k = classify().get(f.eventId);
      renderList();
      renderDetail(f, m, k);
    });
  }

  // ---------------------------------------------------------------- スタッツ
  const statsCache = new Map();
  async function loadStats(eventId) {
    const key = `${state.teamId}/${eventId}`;
    if (statsCache.has(key)) return statsCache.get(key);
    try { const st = await fetchJson(`data/${state.teamId}/stats/${eventId}.json`); statsCache.set(key, st); return st; }
    catch (e) { console.warn(e); return null; }
  }
  const STAT_ROWS = [
    ["possession", "ボール支配率", "%"], ["shots", "シュート"], ["onTarget", "枠内シュート"], ["offTarget", "枠外シュート"], ["blocked", "ブロックされたシュート"],
    ["corners", "コーナーキック"], ["fouls", "ファウル"], ["offsides", "オフサイド"], ["yellow", "イエローカード"], ["red", "レッドカード"],
    ["passes", "パス"], ["passesAccurate", "成功したパス"], ["passAcc", "パス成功率", "pct"], ["tackles", "タックル"], ["tacklesWon", "成功したタックル"],
    ["interceptions", "インターセプト"], ["clearances", "クリア"], ["crosses", "クロス"], ["crossesAccurate", "成功したクロス"],
  ];
  function renderStats(st, which, f) {
    if (!st) return `<p class="hint" style="margin:0 16px 12px">スタッツを読み込めませんでした。</p>`;
    const data = which === "ht" ? st.ht : st.ft;
    if (!data) return `<p class="hint" style="margin:0 16px 12px">この試合のハーフタイム時点のデータはありません。</p>`;
    const team = state.teams.find(x => x.id === state.teamId);
    const fmt = (v, unit) => {
      if (v == null || v === "") return "—";
      if (unit === "pct") { const n = Number(v); return isNaN(n) ? esc(v) : `${Math.round(n * 100)}%`; }
      if (unit === "%") return `${esc(v)}%`;
      return esc(v);
    };
    const rows = STAT_ROWS.filter(([k]) => data.us[k] !== undefined && (data.us[k] != null || data.opp[k] != null)).map(([k, label, unit]) => {
      const a = data.us[k], b = data.opp[k];
      const na = Number(a), nb = Number(b);
      const tot = (isNaN(na) ? 0 : na) + (isNaN(nb) ? 0 : nb);
      const pa = tot ? Math.round((isNaN(na) ? 0 : na) / tot * 100) : 50;
      return `<div class="srow"><span class="sv">${fmt(a, unit)}</span><span class="sl">${label}<i class="bar"><b style="width:${pa}%"></b></i></span><span class="sv">${fmt(b, unit)}</span></div>`;
    }).join("");
    return `<div class="stats-table">
      <div class="shead"><span>${esc(team?.shortName || "自チーム")}</span><span>${which === "ht" ? "ハーフタイム時点" : "試合終了時点"}</span><span>${esc(f.opponent.abbr || f.opponent.name)}</span></div>
      ${rows}
      <p class="hint" style="margin:10px 16px 12px">${esc(st.note || "")}${which === "ht" ? " ボール支配率などの集計値は試合終了時のみです。" : ""}</p></div>`;
  }

  // ---------------------------------------------------------------- 結果
  async function loadResult(eventId) {
    try { return await fetchJson(`data/${state.teamId}/results/${eventId}.json`); }
    catch (e) { console.warn(e); return null; }
  }
  function renderResult(r, f) {
    if (!r) return `<p class="hint" style="margin:12px 16px">結果を読み込めませんでした。</p>`;
    const team = state.teams.find(x => x.id === state.teamId);
    const us = team?.shortName || "自チーム", opp = f.opponent.abbr || f.opponent.name;
    const left = r.isHome ? { n: us, s: r.score.us } : { n: opp, s: r.score.opp };
    const right = r.isHome ? { n: opp, s: r.score.opp } : { n: us, s: r.score.us };
    const verdict = r.score.us > r.score.opp ? "勝ち" : r.score.us < r.score.opp ? "負け" : "引き分け";
    const kindMark = k => k === "og" ? "（OG）" : k === "pen" ? "（PK）" : "";
    const goalRow = g => `<div class="grow ${g.side}"><span class="gm">${esc(g.minute)}</span><span class="gn">⚽ ${esc(g.scorer || "")}${kindMark(g.kind)}${g.assist ? `<small>アシスト: ${esc(g.assist)}</small>` : ""}</span></div>`;
    const redRow = c => `<div class="grow ${c.side}"><span class="gm">${esc(c.minute)}</span><span class="gn">🟥 ${esc(c.name || "")}<small>退場</small></span></div>`;
    const events = [...r.goals.map(g => ({ ...g, _t: g.minute })), ...r.redCards.map(c => ({ ...c, _red: true }))]
      .sort((a, b) => parseInt(a.minute) - parseInt(b.minute));
    return `<div class="result-box">
      <div class="score-line"><span class="tn">${esc(left.n)}</span><span class="sc">${left.s} <i>-</i> ${right.s}</span><span class="tn">${esc(right.n)}</span></div>
      <div class="verdict">${esc(us)} の${verdict}</div>
      <div class="glist">${events.map(e => e._red ? redRow(e) : goalRow(e)).join("") || `<p class="hint">得点なし</p>`}</div>
    </div>`;
  }

  function renderPitch(side, sk = "us") {
    const byId = new Map(side.starters.map(p => [p.id, p]));
    const rows = (side.rows && side.rows.length ? side.rows : [side.starters.map(p => p.id)]).map(r => r.map(id => byId.get(id)).filter(Boolean));
    return `<div class="pitch"><div class="lines"><i class="out"></i><i class="half"></i><i class="circle"></i><i class="boxb"></i><i class="boxt"></i></div>
      <div class="rows">${rows.slice().reverse().map(r => `<div class="row">${r.map(p => playerChip(p, sk, "starter")).join("")}</div>`).join("")}</div></div>`;
  }

  // 欠場理由の決定: 手入力(absences.json) > 更新スクリプトが付けた理由 > Transfermarkt の負傷履歴
  const addDays = (iso, n) => { const d = new Date(iso + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  function nameMatches(playerName, entryName) {
    const n = normName(playerName), e = normName(entryName);
    return !!e && (e === n || n.split(" ").includes(e) || n.endsWith(" " + e) || e.endsWith(" " + n.split(" ").pop()) && e.split(" ")[0] === n.split(" ")[0]);
  }
  function injuryEntriesFor(playerName) {
    return (state.injuries || []).filter(e => nameMatches(playerName, e.name));
  }
  function resolveReason(p, matchDateIso) {
    const d = (matchDateIso || "").slice(0, 10);
    for (const e of ((state.absencesCfg || {})[state.teamId] || [])) {
      if (nameMatches(p.name, e.name) && (!e.from || e.from <= d) && (!e.until || d <= e.until)) return { type: e.type || "欠場", reason: e.reason || "", source: "manual" };
    }
    if (p.type && p.type !== "理由不明") return { type: p.type, reason: p.reason || "", source: p.source };
    for (const e of injuryEntriesFor(p.name)) {
      if (e.since && e.since > d) continue;                 // 試合より後に起きた負傷は見せない
      const end = e.until || e.lastSeen;
      if (end && d > addDays(end, 2)) continue;              // とっくに復帰している
      return { type: e.type || "負傷", reason: e.reasonJa || e.reason || "", source: "tm", until: e.active ? e.until : null };
    }
    return { type: "理由不明", reason: "", source: "none" };
  }

  function renderAbsentees(list, matchDateIso) {
    if (!list.length) return `<div class="section-label">欠場・メンバー外</div><div class="card"><div class="ghost-row">メンバー外の選手はいません</div></div>`;
    // 今季メンバー入りした選手、または理由が分かっている選手（長期離脱中など）を本欄に出す
    const seen = p => (state.squadHistory[p.id] || 0) > 0 || resolveReason(p, matchDateIso).type !== "理由不明";
    const main = list.filter(seen), other = list.filter(p => !seen(p));
    const row = p => {
      const r = resolveReason(p, matchDateIso);
      const unk = r.type === "理由不明";
      const sus = /停止/.test(r.type || "");
      let why = unk ? "メンバー外 ・ 理由は未登録" : esc(r.reason || "");
      if (!unk && r.until) why += `<small>復帰見込み ${esc(fmtDate(r.until))}</small>`;
      return `<div class="r" data-pid="${esc(p.id)}" data-side="us" data-role="absent">${photoEl(p)}<div><div class="n">${esc(p.name)}</div><div class="why">${why}</div></div><span class="tag ${unk ? "unk" : sus ? "sus" : ""}">${esc(r.type || "欠場")}</span></div>`;
    };
    let html = `<div class="section-label">欠場・メンバー外 <span class="count">${main.length}</span></div><div class="card abs">`;
    html += main.length ? main.map(row).join("") : `<div class="ghost-row">今季メンバー入りした選手は全員ベンチ入りしています</div>`;
    if (other.length) html += `<details class="more"><summary>今季まだメンバー入りしていない選手 (${other.length})</summary>${other.map(row).join("")}</details>`;
    html += `</div><p class="hint">理由は Transfermarkt の負傷情報から自動で付けています。手で直す場合は absences.json（README 参照）。</p>`;
    return html;
  }

  // ---------------------------------------------------------------- チーム
  async function selectTeam(id) {
    const team = state.teams.find(t => t.id === id) || state.teams[0];
    if (!team) return;
    state.teamId = team.id;
    state.prefs.team = team.id; save();
    state.selected = null;
    document.documentElement.style.setProperty("--accent", team.color || "#e2231a");
    $("#team-crest").src = `https://a.espncdn.com/i/teamlogos/soccer/500/${team.espnTeamId}.png`;
    $("#team-name").textContent = team.name;
    $("#team-sub").textContent = `${team.leagueName || ""} 2026-27 ・ ネタバレなし`;
    const icsUrl = new URL(`data/${team.id}/fixtures.ics`, location.href).href;
    $("#ics-url").value = icsUrl;
    $("#ics-webcal").href = icsUrl.replace(/^https?:/, "webcal:");
    renderTabs();
    $("#list").innerHTML = `<div class="empty">読み込み中...</div>`;
    $("#detail").innerHTML = `<div class="empty">一覧から試合を選んでください</div>`;
    document.body.classList.remove("show-detail");
    try {
      const [fx, ro, sh, inj, abs] = await Promise.all([
        fetchJson(`data/${team.id}/fixtures.json`),
        fetchJson(`data/${team.id}/roster.json`).catch(() => ({ players: [] })),
        fetchJson(`data/${team.id}/squad-history.json`).catch(() => ({ appearancesInSquad: {} })),
        fetchJson(`data/${team.id}/injuries.json`).catch(() => ({ players: [] })),
        fetchJson("absences.json").catch(() => ({})),
      ]);
      state.fixtures = (fx.fixtures || []).slice().sort((a, b) => a.date.localeCompare(b.date));
      state.roster = new Map((ro.players || []).map(p => [p.id, p]));
      state.squadHistory = sh.appearancesInSquad || {};
      state.injuries = inj.players || [];
      state.absencesCfg = abs || {};
      state.matchCache.clear();
      renderList();
      // PC では「次に観る試合」を自動で開く
      if (window.innerWidth >= 900) {
        const cur = [...classify()].find(([, k]) => k === "current");
        if (cur) openMatch(cur[0]);
      }
    } catch (e) {
      $("#list").innerHTML = `<div class="empty">データがまだありません。<br>scripts/update.py を実行してください。<br><small>${esc(e.message)}</small></div>`;
    }
  }

  function renderTabs() {
    const el = $("#tabs");
    el.innerHTML = state.teams.map(t => `<button class="tab ${t.id === state.teamId ? "on" : ""}" data-id="${esc(t.id)}">${esc(t.shortName || t.name)}</button>`).join("")
      + `<button class="tab add" id="tab-add">＋ チームを追加</button>`;
    el.querySelectorAll(".tab[data-id]").forEach(b => b.addEventListener("click", () => selectTeam(b.dataset.id)));
    $("#tab-add").addEventListener("click", () => $("#dlg-addteam").showModal());
  }

  // ---------------------------------------------------------------- 設定
  function bindSettings() {
    const dlg = $("#dlg-settings");
    $("#btn-settings").addEventListener("click", () => {
      $("#opt-lock").checked = state.prefs.lock;
      $("#opt-opp").checked = state.prefs.oppDefault;
      for (const k of ["showResult", "showStats", "showVideos", "showNames"]) $("#opt-" + k).checked = state.prefs[k];
      renderAuth();
      dlg.showModal();
    });
    for (const k of ["showResult", "showStats", "showVideos", "showNames"]) {
      $("#opt-" + k).addEventListener("change", e => {
        state.prefs[k] = e.target.checked; save(); applyDisplayPrefs();
        if (state.selected) { const f = state.fixtures.find(x => x.eventId === state.selected); if (f) renderDetail(f, state.matchCache.get(f.eventId) || null, classify().get(f.eventId)); }
      });
    }
    const authClick = () => { if (cloud.user) { if (confirm("ログアウトしますか？（記録はこの端末には残ります）")) cloud.signOut(); } else cloud.signIn(); };
    $("#btn-auth").addEventListener("click", authClick);
    $("#btn-auth2").addEventListener("click", authClick);
    $("#opt-lock").addEventListener("change", e => { state.prefs.lock = e.target.checked; save(); renderList(); toast(e.target.checked ? "ロックを有効にしました" : "ロックを解除しました"); });
    $("#opt-opp").addEventListener("change", e => { state.prefs.oppDefault = e.target.checked; save(); });
    $("#btn-copy-ics").addEventListener("click", async () => {
      const url = $("#ics-url").value;
      try { await navigator.clipboard.writeText(url); toast("URL をコピーしました"); }
      catch { $("#ics-url").select(); toast("選択した URL をコピーしてください"); }
    });
    $("#btn-reset").addEventListener("click", () => {
      if (!confirm("このチームの「観た」記録をすべて消しますか？")) return;
      state.prefs.watched[state.teamId] = []; save(); renderList(); toast("リセットしました");
    });
  }

  // ---------------------------------------------------------------- init
  async function init() {
    bindSettings();
    applyDisplayPrefs();
    cloud.init();
    renderAuth();
    try {
      const [cfg, meta] = await Promise.all([fetchJson("teams.json"), fetchJson("data/meta.json").catch(() => null)]);
      state.teams = cfg.teams || [];
      if (meta && meta.updatedAt) {
        const u = fmtParts(meta.updatedAt);
        $("#updated").textContent = `最終更新 ${u.full}（日本時間）`;
        $("#settings-note").textContent = `データ最終更新: ${u.full}。更新は GitHub Actions で1時間ごとに自動実行されます。`;
      } else {
        $("#updated").textContent = "データ未取得";
      }
      await selectTeam(state.prefs.team || (state.teams[0] && state.teams[0].id));
    } catch (e) {
      $("#list").innerHTML = `<div class="empty">teams.json が読み込めません。<br><small>${esc(e.message)}</small><br><br>ファイルを直接開いている場合は serve.bat でローカルサーバーを起動してください。</div>`;
    }
  }
  init();
})();
