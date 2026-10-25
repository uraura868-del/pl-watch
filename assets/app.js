/* PL Watch ・ ネタバレなし観戦ノート（フロントエンド）
 * data/ 以下の JSON を読んで描画するだけ。スコア等はそもそもデータに含まれない。 */
(() => {
  "use strict";

  const LS_KEY = "plwatch.v1";
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
  function load() {
    try {
      const p = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
      return { team: p.team || null, watched: p.watched || {}, lock: p.lock !== false, oppDefault: !!p.oppDefault };
    } catch { return { team: null, watched: {}, lock: true, oppDefault: false }; }
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state.prefs)); } catch { /* private mode など */ }
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
    // "Bruno Fernandes" → "B. Fernandes"、3語以上は最後の語
    return parts.length === 2 ? `${parts[0][0]}. ${parts[1]}` : parts[parts.length - 1];
  };
  const initials = (name) => String(name || "").split(/\s+/).map(w => w[0] || "").join("").slice(0, 2).toUpperCase();

  function photoEl(p, cls = "") {
    const num = p.jersey ? `<span class="num">${esc(p.jersey)}</span>` : "";
    const img = p.photo ? `<img src="${esc(p.photo)}" alt="" loading="lazy" onerror="this.remove()">` : "";
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
  async function getCareers() {
    if (!careersCache.has(state.teamId)) {
      try { careersCache.set(state.teamId, (await fetchJson(`data/${state.teamId}/careers.json`)).players || {}); }
      catch { careersCache.set(state.teamId, {}); }
    }
    return careersCache.get(state.teamId);
  }
  function renderCareer(entry) {
    if (!entry) return `<div class="sec"><h3>経歴</h3><p class="note">経歴情報はまだ取得されていません。</p></div>`;
    const list = entry.career || [];
    if (!entry.qid || !list.length) return `<div class="sec"><h3>経歴</h3><p class="note">経歴情報なし（Wikidata に登録がありません）</p></div>`;
    const clubs = list.filter(c => !c.national), nats = list.filter(c => c.national);
    const row = c => {
      const cur = !c.end && !c.national;
      const tags = [c.loan ? "ローン" : "", c.youth ? "ユース" : ""].filter(Boolean).map(t => `<span class="ctag">${t}</span>`).join("");
      return `<div class="crow ${cur ? "cur" : ""}"><span class="cy">${esc(c.start || "?")}〜${c.end ? esc(c.end) : "現在"}</span><span class="cn">${esc(c.club)}${tags}</span>${c.apps != null ? `<span class="ca">${esc(c.apps)}試合</span>` : ""}</div>`;
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
    else if (ctx.role === "absent") role = `メンバー外 ・ ${esc(p.type || "理由不明")}${p.reason ? " ・ " + esc(p.reason) : ""}`;

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

    // 経歴（自チームのみ、Wikidata）
    let career = "";
    if (ours) career = renderCareer((await getCareers())[p.id]);

    // 欠場の記録（absences.json の手入力分）
    let absHist = "";
    if (ours) {
      const cfg = await getAbsences();
      const n = normName(p.name);
      const list = (cfg[state.teamId] || []).filter(e => { const en = normName(e.name); return en && (en === n || n.split(" ").includes(en) || n.endsWith(" " + en)); });
      if (list.length) absHist = `<div class="sec"><h3>欠場の記録</h3>${list.map(e =>
        `<div class="abs-row"><b>${esc(e.type || "欠場")}</b> ${esc(e.reason || "")}<small>${e.from ? fmtDate(e.from) : ""}${(e.from || e.until) ? " 〜 " : ""}${e.until ? fmtDate(e.until) : ""}</small></div>`).join("")}</div>`;
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
      ${season}${career}${absHist}`;
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
    let opp = esc(f.opponent.name), sub = `${ha} ・ ${esc(f.competition)}`;
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
      if (!state.showOpp) html += renderAbsentees(m.absentees || []);
      else html += `<p class="hint">相手チームの欠場者情報は取得していません。</p>`;
    } else {
      html += `<div class="lock-msg"><div class="big">⏳</div>スタメンはまだ発表されていません。<br>キックオフ約1時間前以降の自動更新で表示されます。</div></div>`;
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
    // 選手の写真 → 詳細ポップアップ
    el.querySelectorAll("[data-pid]").forEach(c => c.addEventListener("click", () => {
      if (!m) return;
      const { pid, side: sk, role } = c.dataset;
      const src = sk === "opp" ? m.opponent : m.team;
      const p = role === "absent" ? (m.absentees || []).find(x => x.id === pid) : src && [...src.starters, ...src.bench].find(x => x.id === pid);
      if (p) openPlayer(p, { side: sk, role });
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

  function renderPitch(side, sk = "us") {
    const byId = new Map(side.starters.map(p => [p.id, p]));
    const rows = (side.rows && side.rows.length ? side.rows : [side.starters.map(p => p.id)]).map(r => r.map(id => byId.get(id)).filter(Boolean));
    return `<div class="pitch"><div class="lines"><i class="out"></i><i class="half"></i><i class="circle"></i><i class="boxb"></i><i class="boxt"></i></div>
      <div class="rows">${rows.slice().reverse().map(r => `<div class="row">${r.map(p => playerChip(p, sk, "starter")).join("")}</div>`).join("")}</div></div>`;
  }

  function renderAbsentees(list) {
    if (!list.length) return `<div class="section-label">欠場・メンバー外</div><div class="card"><div class="ghost-row">メンバー外の選手はいません</div></div>`;
    const seen = p => (state.squadHistory[p.id] || 0) > 0;
    const main = list.filter(seen), other = list.filter(p => !seen(p));
    const row = p => {
      const unk = p.type === "理由不明";
      const sus = /停止/.test(p.type || "");
      const why = unk ? "メンバー外 ・ 理由は未登録" : esc(p.reason || "");
      return `<div class="r" data-pid="${esc(p.id)}" data-side="us" data-role="absent">${photoEl(p)}<div><div class="n">${esc(p.name)}</div><div class="why">${why}</div></div><span class="tag ${unk ? "unk" : sus ? "sus" : ""}">${esc(p.type || "欠場")}</span></div>`;
    };
    let html = `<div class="section-label">欠場・メンバー外 <span class="count">${main.length}</span></div><div class="card abs">`;
    html += main.length ? main.map(row).join("") : `<div class="ghost-row">今季メンバー入りした選手は全員ベンチ入りしています</div>`;
    if (other.length) html += `<details class="more"><summary>今季まだメンバー入りしていない選手 (${other.length})</summary>${other.map(row).join("")}</details>`;
    html += `</div><p class="hint">欠場理由は absences.json に書くと表示されます（詳しくは README）。</p>`;
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
    renderTabs();
    $("#list").innerHTML = `<div class="empty">読み込み中...</div>`;
    $("#detail").innerHTML = `<div class="empty">一覧から試合を選んでください</div>`;
    document.body.classList.remove("show-detail");
    try {
      const [fx, ro, sh] = await Promise.all([
        fetchJson(`data/${team.id}/fixtures.json`),
        fetchJson(`data/${team.id}/roster.json`).catch(() => ({ players: [] })),
        fetchJson(`data/${team.id}/squad-history.json`).catch(() => ({ appearancesInSquad: {} })),
      ]);
      state.fixtures = (fx.fixtures || []).slice().sort((a, b) => a.date.localeCompare(b.date));
      state.roster = new Map((ro.players || []).map(p => [p.id, p]));
      state.squadHistory = sh.appearancesInSquad || {};
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
      dlg.showModal();
    });
    $("#opt-lock").addEventListener("change", e => { state.prefs.lock = e.target.checked; save(); renderList(); toast(e.target.checked ? "ロックを有効にしました" : "ロックを解除しました"); });
    $("#opt-opp").addEventListener("change", e => { state.prefs.oppDefault = e.target.checked; save(); });
    $("#btn-reset").addEventListener("click", () => {
      if (!confirm("このチームの「観た」記録をすべて消しますか？")) return;
      state.prefs.watched[state.teamId] = []; save(); renderList(); toast("リセットしました");
    });
  }

  // ---------------------------------------------------------------- init
  async function init() {
    bindSettings();
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
