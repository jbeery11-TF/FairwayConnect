// FairwayConnect — LinkedIn-style network for golfers.
// API-driven SPA. The backend is server.py; auth token lives in localStorage.

const API_BASE = window.FC_API_BASE || "";
const TOKEN_KEY = "fc-token";

let token = localStorage.getItem(TOKEN_KEY);
let meBrief = null;        // {id, name, color, ...} for the nav
let pollTimer = null;      // message-page refresh timer

const $app = document.getElementById("app");

// ---------- Utilities ----------

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function initials(name) {
  return name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
}

function avatar(u, size) {
  return `<span class="avatar avatar-${size}" style="background:${esc(u.color)}">${initials(u.name)}</span>`;
}

function handicapLabel(h) {
  if (h == null) return "—";
  return h < 0 ? `+${Math.abs(h)}` : h;
}

function timeAgo(epoch) {
  const s = Math.max(1, Date.now() / 1000 - epoch);
  if (s < 60) return "now";
  if (s < 3600) return Math.floor(s / 60) + "m";
  if (s < 86400) return Math.floor(s / 3600) + "h";
  return Math.floor(s / 86400) + "d";
}

function toast(msg) {
  document.querySelectorAll(".toast").forEach(t => t.remove());
  const t = document.createElement("div");
  t.className = "toast";
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

async function api(path, method = "GET", body) {
  const headers = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  if (body) headers["Content-Type"] = "application/json";
  let res;
  try {
    res = await fetch(API_BASE + "/api" + path, {
      method, headers, body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    toast("Can't reach the clubhouse — is the server running?");
    throw e;
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && !path.startsWith("/login") && !path.startsWith("/signup")) {
    setToken(null);
    render();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    throw Object.assign(new Error(data.error || "Something went wrong"), { api: true });
  }
  return data;
}

// api() wrapper for click handlers: shows errors as toasts, then re-renders.
async function act(promise, successMsg) {
  try {
    const result = await promise;
    if (successMsg) toast(successMsg);
    await render();
    return result;
  } catch (e) {
    if (e.api) toast(e.message);
  }
}

function setToken(t) {
  token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
  document.body.classList.toggle("noauth", !t);
}

function go(path) {
  location.hash = "#/" + path;
}

// ---------- Nav chrome ----------

async function refreshChrome() {
  if (!token) return;
  let b;
  try {
    b = await api("/badges");
  } catch (e) { return; }
  meBrief = b.me;
  const setBadge = (id, n) => {
    const el = document.getElementById(id);
    el.textContent = n;
    el.classList.toggle("hidden", n === 0);
  };
  setBadge("badgeNetwork", b.invites);
  setBadge("badgeMessages", b.messages);
  setBadge("badgeNotifs", b.notifications);
  const nav = document.getElementById("navAvatar");
  nav.style.background = b.me.color;
  nav.textContent = initials(b.me.name);

  const path = location.hash.replace("#/", "").split("/")[0] || "feed";
  document.querySelectorAll(".nav-item").forEach(el => {
    const key = el.dataset.nav;
    el.classList.toggle("active", key === path || (key === "me" && path === "profile"));
  });
}

// ---------- Auth ----------

let authMode = "login";

function renderAuth() {
  document.body.classList.add("noauth");
  const isLogin = authMode === "login";
  $app.innerHTML = `
    <div class="auth-wrap">
      <div class="auth-hero">
        <div style="font-size:54px">⛳</div>
        <h1>FairwayConnect</h1>
        <p>The professional network for golfers.<br>Find your foursome. Brag responsibly.</p>
      </div>
      <div class="card">
        <div class="auth-tabs">
          <button class="auth-tab ${isLogin ? "active" : ""}" onclick="setAuthMode('login')">Sign in</button>
          <button class="auth-tab ${isLogin ? "" : "active"}" onclick="setAuthMode('signup')">Join the club</button>
        </div>
        <form class="card-pad" onsubmit="return submitAuth(event)">
          ${isLogin ? "" : `
            <div class="field"><label>Name</label><input id="authName" type="text" placeholder="Bobby Jones" /></div>`}
          <div class="field"><label>Email</label><input id="authEmail" type="email" placeholder="you@example.com" /></div>
          <div class="field"><label>Password</label><input id="authPassword" type="password" placeholder="${isLogin ? "Your password" : "At least 8 characters"}" /></div>
          ${isLogin ? "" : `
            <div class="field"><label>Headline (optional)</label><input id="authHeadline" type="text" placeholder="Weekend Warrior · Chasing single digits" /></div>
            <div class="field"><label>Home course (optional)</label><input id="authCourse" type="text" placeholder="Harding Park GC" /></div>
            <div class="field"><label>Handicap index (optional)</label><input id="authHandicap" type="number" step="0.1" placeholder="18.5" /></div>`}
          <div class="auth-error" id="authError"></div>
          <button class="btn btn-primary btn-block" type="submit">${isLogin ? "Sign in" : "Create account"}</button>
        </form>
      </div>
      <div class="demo-hint">
        <b>Demo accounts</b> (password <code>golf1234</code>): maria@demo.fairwayconnect.app,
        dev@…, tommy@…, grace@…, hannah@…, sam@…, ray@… — or create your own.
      </div>
    </div>`;
}

function setAuthMode(mode) {
  authMode = mode;
  renderAuth();
}

async function submitAuth(ev) {
  ev.preventDefault();
  const errEl = document.getElementById("authError");
  errEl.textContent = "";
  const payload = {
    email: document.getElementById("authEmail").value,
    password: document.getElementById("authPassword").value,
  };
  if (authMode === "signup") {
    payload.name = document.getElementById("authName").value;
    payload.headline = document.getElementById("authHeadline").value;
    payload.homeCourse = document.getElementById("authCourse").value;
    payload.handicap = document.getElementById("authHandicap").value;
  }
  try {
    const data = await api("/" + authMode, "POST", payload);
    setToken(data.token);
    meBrief = data.user;
    go("feed");
    await render();
    toast(authMode === "signup" ? "Welcome to the club ⛳" : "Welcome back ⛳");
  } catch (e) {
    errEl.textContent = e.message;
  }
  return false;
}

async function signOut() {
  try { await api("/logout", "POST"); } catch (e) { /* token may already be dead */ }
  setToken(null);
  go("feed");
  render();
}

// ---------- Shared components ----------

function railProfileCard(m) {
  return `
    <div class="card rail-left">
      <div class="rail-banner"></div>
      <div class="rail-avatar-wrap">${avatar(m, "lg")}</div>
      <div class="rail-name"><a href="#/profile/me">${esc(m.name)}</a></div>
      <div class="rail-headline">${esc(m.headline)}</div>
      <div class="rail-stats">
        <div class="rail-stat"><span>Handicap index</span><b>${handicapLabel(m.handicap)}</b></div>
        <div class="rail-stat"><span>Rounds logged</span><b>${m.rounds ?? 0}</b></div>
        <div class="rail-stat"><span>Foursome connections</span><b>${m.connections ?? 0}</b></div>
      </div>
    </div>`;
}

function suggestionsCard(suggestions) {
  if (!suggestions || !suggestions.length) return "";
  return `
    <div class="card card-pad">
      <h3 class="card-title">Golfers you may know</h3>
      ${suggestions.map(u => `
        <div class="person-row">
          ${avatar(u, "sm")}
          <div class="person-grow">
            <div class="person-name" onclick="go('profile/${u.id}')">${esc(u.name)}</div>
            <div class="person-sub">${esc(u.headline)}</div>
          </div>
          <button class="btn btn-outline btn-sm" onclick="connect(${u.id}, '${esc(u.name)}')">+ Pair up</button>
        </div>`).join("")}
    </div>`;
}

function connect(id, name) {
  act(api(`/users/${id}/connect`, "POST"), `Invitation sent to ${name} 🤝`);
}

// ---------- Feed ----------

let composerScorecardOpen = false;

async function renderFeed() {
  const data = await api("/feed");
  const m = data.me;
  $app.innerHTML = `
    <div class="layout-3col">
      ${railProfileCard(m)}
      <div>
        <div class="card">
          <div class="composer">
            ${avatar(m, "md")}
            <textarea id="composerText" placeholder="Share a round, a swing thought, or a hot take…"></textarea>
          </div>
          <div id="scoreFields" class="scorefields ${composerScorecardOpen ? "" : "hidden"}">
            <input id="scCourse" placeholder="Course" />
            <input id="scScore" placeholder="Score" inputmode="numeric" />
            <input id="scPar" placeholder="Par" inputmode="numeric" />
            <input id="scFairways" placeholder="FWs e.g. 9/14" />
            <input id="scPutts" placeholder="Putts" inputmode="numeric" />
          </div>
          <div class="composer-actions">
            <button class="btn btn-ghost btn-sm" onclick="toggleScorecard()">${composerScorecardOpen ? "− Remove scorecard" : "＋ Attach scorecard"}</button>
            <button class="btn btn-primary" onclick="publishPost()">Post</button>
          </div>
        </div>
        <div id="feedPosts">
          ${data.posts.map(postCard).join("") || `<div class="card empty-note">Nothing in the feed yet. Be the first to post.</div>`}
        </div>
      </div>
      <div class="rail-right">
        ${suggestionsCard(data.suggestions)}
        <div class="card card-pad" style="margin-top:16px">
          <h3 class="card-title">Trending on the course</h3>
          <div class="person-sub" style="padding:4px 0">🔥 #AerationSeason — grumbling intensifies</div>
          <div class="person-sub" style="padding:4px 0">🏆 #USOpen — qualifying drama</div>
          <div class="person-sub" style="padding:4px 0">🛒 #WITB — what's in the bag week</div>
          <div class="person-sub" style="padding:4px 0">😤 #ThreePuttSupportGroup — you're not alone</div>
        </div>
      </div>
    </div>`;
}

function postCard(p) {
  const a = p.author;
  const score = p.scorecard ? `
    <div class="scorecard">
      <div><b>${esc(p.scorecard.score)}</b>Score${p.scorecard.par ? ` (par ${esc(p.scorecard.par)})` : ""}</div>
      ${p.scorecard.fairways ? `<div><b>${esc(p.scorecard.fairways)}</b>Fairways</div>` : ""}
      ${p.scorecard.putts ? `<div><b>${esc(p.scorecard.putts)}</b>Putts</div>` : ""}
      ${p.scorecard.course ? `<div style="align-self:center">📍 ${esc(p.scorecard.course)}</div>` : ""}
    </div>` : "";
  const menu = p.mine
    ? `<button class="menu-item danger" onclick="deletePost(${p.id})">🗑 Delete post</button>`
    : `<button class="menu-item" onclick="reportPost(${p.id})">🚩 Report post</button>
       <button class="menu-item danger" onclick="blockUser(${a.id}, '${esc(a.name)}')">🚫 Block ${esc(a.name)}</button>`;
  return `
    <div class="card" style="margin-top:16px">
      <div class="post-head">
        ${avatar(a, "md")}
        <div>
          <div class="post-author" onclick="go('profile/${a.id}')">${esc(a.name)}</div>
          <div class="post-sub">${esc(a.headline)}</div>
          <div class="post-sub">${timeAgo(p.createdAt)} · 🌐</div>
        </div>
        <details class="post-menu">
          <summary>⋯</summary>
          <div class="post-menu-items">${menu}</div>
        </details>
      </div>
      <div class="post-body">${esc(p.text)}</div>
      ${score}
      <div class="post-stats">
        <span>🏌️ ${p.likes} nice shot${p.likes === 1 ? "" : "s"}</span>
        <span>${p.comments.length} comment${p.comments.length === 1 ? "" : "s"}</span>
      </div>
      <div class="post-actions">
        <button class="post-action ${p.likedByMe ? "liked" : ""}" onclick="toggleLike(${p.id})">🏌️ Nice shot</button>
        <button class="post-action" onclick="document.getElementById('comment-input-${p.id}').focus()">💬 Comment</button>
      </div>
      <div class="comments">
        ${p.comments.map(c => `
          <div class="comment">
            ${avatar(c.author, "sm")}
            <div class="comment-bubble">
              <div class="comment-author" style="cursor:pointer" onclick="go('profile/${c.author.id}')">${esc(c.author.name)}</div>
              ${esc(c.text)}
            </div>
          </div>`).join("")}
        <form class="comment-form" onsubmit="return addComment(event, ${p.id})">
          ${meBrief ? avatar(meBrief, "sm") : ""}
          <input id="comment-input-${p.id}" type="text" placeholder="Add a comment…" enterkeyhint="send" />
          <button class="btn btn-primary btn-sm" type="submit">Post</button>
        </form>
      </div>
    </div>`;
}

function toggleScorecard() {
  composerScorecardOpen = !composerScorecardOpen;
  const text = document.getElementById("composerText").value;
  renderFeed().then(() => { document.getElementById("composerText").value = text; });
}

async function publishPost() {
  const text = document.getElementById("composerText").value.trim();
  const body = { text };
  if (composerScorecardOpen) {
    const sc = {
      course: document.getElementById("scCourse").value.trim(),
      score: document.getElementById("scScore").value.trim(),
      par: document.getElementById("scPar").value.trim(),
      fairways: document.getElementById("scFairways").value.trim(),
      putts: document.getElementById("scPutts").value.trim(),
    };
    if (sc.score || sc.course) body.scorecard = sc;
  }
  composerScorecardOpen = false;
  await act(api("/posts", "POST", body), "Posted to your network ⛳");
}

async function toggleLike(pid) {
  await act(api(`/posts/${pid}/like`, "POST"));
}

async function addComment(ev, pid) {
  ev.preventDefault();
  const input = document.getElementById("comment-input-" + pid);
  const text = input.value.trim();
  if (!text) return false;
  await act(api(`/posts/${pid}/comments`, "POST", { text }));
  return false;
}

async function deletePost(pid) {
  if (!confirm("Delete this post? No mulligans on this one.")) return;
  await act(api(`/posts/${pid}`, "DELETE"), "Post deleted");
}

async function reportPost(pid) {
  const reason = prompt("What's wrong with this post? (spam, abuse, etc.)");
  if (reason === null) return;
  await act(api(`/posts/${pid}/report`, "POST", { reason }),
            "Reported. Our marshals will review it.");
}

async function blockUser(uid, name) {
  if (!confirm(`Block ${name}? You won't see each other's posts, messages, or profiles.`)) return;
  await act(api(`/users/${uid}/block`, "POST"), `${name} has been blocked`);
}

// ---------- Network ----------

async function renderNetwork() {
  const data = await api("/network");
  $app.innerHTML = `
    <div class="layout-2col">
      <div>
        <div class="card">
          <div class="card-pad" style="padding-bottom:0"><h3 class="card-title">Foursome invitations (${data.invites.length})</h3></div>
          ${data.invites.map(u => `
            <div class="invite-card">
              ${avatar(u, "md")}
              <div class="person-grow">
                <div class="person-name" onclick="go('profile/${u.id}')">${esc(u.name)}</div>
                <div class="person-sub">${esc(u.headline)}</div>
                <div class="person-sub">Wants to join your foursome network</div>
              </div>
              <div class="invite-actions">
                <button class="btn btn-ghost btn-sm" onclick="act(api('/users/${u.id}/decline', 'POST'))">Ignore</button>
                <button class="btn btn-primary btn-sm" onclick="act(api('/users/${u.id}/connect', 'POST'), 'You\\'re now connected with ${esc(u.name)} ⛳')">Accept</button>
              </div>
            </div>`).join("") || `<div class="empty-note">No pending invitations. Go forth and network on the range.</div>`}
        </div>

        <div class="card">
          <div class="card-pad" style="padding-bottom:0"><h3 class="card-title">Grow your foursome network</h3></div>
          <div class="people-grid">
            ${data.suggestions.map(u => `
              <div class="people-card">
                <div class="people-card-banner"></div>
                ${avatar(u, "lg")}
                <div class="people-card-name" onclick="go('profile/${u.id}')">${esc(u.name)}</div>
                <div class="people-card-sub">${esc(u.headline)}</div>
                ${u.pending
                  ? `<button class="btn btn-ghost btn-sm" disabled>Pending</button>`
                  : `<button class="btn btn-outline btn-sm" onclick="connect(${u.id}, '${esc(u.name)}')">+ Pair up</button>`}
              </div>`).join("") || `<div class="empty-note">You've paired up with everyone. Impressive networking.</div>`}
          </div>
        </div>
      </div>

      <div class="card card-pad">
        <h3 class="card-title">Your foursome network (${data.connections.length})</h3>
        ${data.connections.map(u => `
          <div class="person-row">
            ${avatar(u, "sm")}
            <div class="person-grow">
              <div class="person-name" onclick="go('profile/${u.id}')">${esc(u.name)}</div>
              <div class="person-sub">${esc(u.headline)}</div>
            </div>
            <button class="btn btn-outline btn-sm" onclick="go('messages/${u.id}')">Message</button>
          </div>`).join("") || `<div class="empty-note">No connections yet.</div>`}
      </div>
    </div>`;
}

// ---------- Tee Times ----------

let teetimeFormOpen = false;

async function renderTeeTimes() {
  const data = await api("/teetimes");
  $app.innerHTML = `
    <div class="layout-2col">
      <div class="card">
        <div class="card-pad" style="padding-bottom:0">
          <h3 class="card-title">Open tee times</h3>
        </div>
        ${data.teetimes.map(t => `
          <div class="teetime">
            <div class="teetime-logo">${esc(t.icon)}</div>
            <div class="person-grow">
              <div class="teetime-title">${esc(t.title)}</div>
              <div class="teetime-meta">${esc(t.course)} · ${esc(t.when)}</div>
              <div class="teetime-desc">${esc(t.desc)}</div>
              <div class="teetime-foot">
                ${t.tags.map(tag => `<span class="pill">${esc(tag)}</span>`).join("")}
                <span class="pill pill-gold">${t.spotsLeft} spot${t.spotsLeft === 1 ? "" : "s"} open</span>
                <span>Hosted by <a href="#/profile/${t.host.id}" style="color:var(--green);font-weight:600">${esc(t.host.name)}</a></span>
              </div>
              ${t.mine && t.requests.length ? `
                <div class="tee-requests">
                  <div class="tee-requests-title">Player requests</div>
                  ${t.requests.map(u => `
                    <div class="tee-request-row">
                      ${avatar(u, "sm")}
                      <div class="person-grow">
                        <div class="person-name" onclick="go('profile/${u.id}')">${esc(u.name)}</div>
                        <div class="person-sub">${u.status === "accepted" ? "Spot confirmed" : "Waiting for your response"}</div>
                      </div>
                      ${u.status === "accepted"
                        ? `<span class="pill">Accepted ✓</span>`
                        : `<div class="tee-request-actions">
                            <button class="btn btn-primary btn-sm" onclick="reviewTeeTimeRequest(${t.id}, ${u.id}, 'accept')">Accept</button>
                            <button class="btn btn-ghost btn-sm" onclick="reviewTeeTimeRequest(${t.id}, ${u.id}, 'decline')">Decline</button>
                          </div>`}
                    </div>`).join("")}
                </div>` : ""}
            </div>
            <div>
              ${t.mine
                ? `<button class="btn btn-ghost btn-sm" disabled>Your listing</button>`
                : t.requestStatus === "pending"
                  ? `<button class="btn btn-ghost btn-sm" disabled>Requested ✓</button>`
                  : t.requestStatus === "accepted"
                    ? `<button class="btn btn-ghost btn-sm" disabled>Spot confirmed ✓</button>`
                  : t.spotsLeft === 0
                    ? `<button class="btn btn-ghost btn-sm" disabled>Full</button>`
                    : `<button class="btn btn-primary btn-sm" onclick="act(api('/teetimes/${t.id}/join', 'POST'), 'Request sent — keep your spikes ready 👟')">Request spot</button>`}
            </div>
          </div>`).join("") || `<div class="empty-note">No open tee times. Post one!</div>`}
      </div>

      <div>
        <div class="card card-pad">
          <h3 class="card-title">Host a tee time</h3>
          ${teetimeFormOpen ? `
            <form onsubmit="return createTeeTime(event)">
              <div class="field"><label>Title</label><input id="ttTitle" placeholder="Saturday dawn patrol — need 2" /></div>
              <div class="field"><label>Course</label><input id="ttCourse" placeholder="Harding Park GC" /></div>
              <div class="field"><label>When</label><input id="ttWhen" placeholder="Sat Jun 20, 7:00 AM" /></div>
              <div class="field"><label>Open spots (1–3)</label><input id="ttSpots" type="number" min="1" max="3" value="1" /></div>
              <div class="field"><label>Details</label><input id="ttDesc" placeholder="Walking, all levels welcome" /></div>
              <div class="field"><label>Tags (comma separated)</label><input id="ttTags" placeholder="Casual, Walking" /></div>
              <button class="btn btn-primary btn-block" type="submit">Post tee time</button>
            </form>`
          : `<div class="person-sub" style="margin-bottom:10px">Need players? Post an open spot and let the network fill your cart.</div>
             <button class="btn btn-outline btn-sm" onclick="teetimeFormOpen = true; render()">＋ New listing</button>`}
        </div>
      </div>
    </div>`;
}

async function reviewTeeTimeRequest(teetimeId, userId, action) {
  const verb = action === "accept" ? "accepted" : "declined";
  await act(
    api(`/teetimes/${teetimeId}/requests/${userId}/${action}`, "POST"),
    `Player ${verb}`,
  );
}

async function createTeeTime(ev) {
  ev.preventDefault();
  const body = {
    title: document.getElementById("ttTitle").value,
    course: document.getElementById("ttCourse").value,
    when: document.getElementById("ttWhen").value,
    spots: document.getElementById("ttSpots").value,
    desc: document.getElementById("ttDesc").value,
    tags: document.getElementById("ttTags").value.split(",").map(s => s.trim()).filter(Boolean),
  };
  teetimeFormOpen = false;
  await act(api("/teetimes", "POST", body), "Tee time posted ⛳");
  return false;
}

// ---------- Messaging ----------

async function renderMessages(withId) {
  const list = await api("/threads");
  const isPhone = matchMedia("(max-width: 640px)").matches;
  // On desktop auto-open the latest thread; on phones stay on the list.
  if (!withId && list.threads.length && !isPhone) withId = list.threads[0].with.id;
  const thread = withId ? await api(`/threads/${withId}`).catch(() => null) : null;

  $app.innerHTML = `
    <div class="card msg-layout ${thread ? "has-thread" : ""}">
      <div class="msg-list">
        <div class="msg-pane-head">Messaging</div>
        ${list.threads.map(t => `
          <div class="msg-thread-item ${t.with.id === Number(withId) ? "active" : ""} ${t.unread ? "msg-unread" : ""}"
               onclick="go('messages/${t.with.id}')">
            ${avatar(t.with, "md")}
            <div class="person-grow">
              <div class="person-name">${esc(t.with.name)}</div>
              <div class="msg-preview">${esc(t.last)}</div>
            </div>
          </div>`).join("") || `<div class="empty-note">No conversations yet.<br>Message a connection from their profile.</div>`}
      </div>
      ${thread ? `
        <div class="msg-pane">
          <div class="msg-pane-head"><a class="msg-back" href="#/messages">‹</a>${esc(thread.with.name)} <span class="person-sub" style="font-weight:400">· ${esc(thread.with.headline)}</span></div>
          <div class="msg-scroll">
            ${thread.messages.map(m => `
              <div class="bubble ${m.from === meBrief.id ? "bubble-me" : "bubble-them"}">${esc(m.text)}</div>`).join("")}
          </div>
          <form class="msg-input-row" onsubmit="return sendMessage(event, ${thread.with.id})">
            <input id="msgInput" type="text" placeholder="Write a message…" autocomplete="off" />
            <button class="btn btn-primary btn-sm" type="submit">Send</button>
          </form>
        </div>`
      : `<div class="msg-pane msg-empty">Select a conversation</div>`}
    </div>`;

  const scroll = document.querySelector(".msg-scroll");
  if (scroll) scroll.scrollTop = scroll.scrollHeight;

  // Light polling so replies show up while the page is open.
  pollTimer = setTimeout(() => {
    if ((location.hash || "").startsWith("#/messages")) render();
  }, 6000);
}

async function sendMessage(ev, otherId) {
  ev.preventDefault();
  const input = document.getElementById("msgInput");
  const text = input.value.trim();
  if (!text) return false;
  input.value = "";
  try {
    await api(`/threads/${otherId}`, "POST", { text });
    await render();
  } catch (e) {
    if (e.api) toast(e.message);
  }
  return false;
}

// ---------- Notifications ----------

async function renderNotifications() {
  const data = await api("/notifications");
  $app.innerHTML = `
    <div class="layout-2col">
      <div class="card">
        ${data.notifications.map(n => `
          <div class="notif ${n.unread ? "unread" : ""}" ${n.link ? `style="cursor:pointer" onclick="location.hash='${esc(n.link)}'"` : ""}>
            <span style="font-size:22px">${esc(n.icon)}</span>
            <span>${esc(n.text)}</span>
            <span class="notif-time">${timeAgo(n.createdAt)}</span>
          </div>`).join("") || `<div class="empty-note">All quiet on the course.</div>`}
      </div>
      <div class="card card-pad">
        <h3 class="card-title">Notification settings</h3>
        <div class="person-sub" style="padding:3px 0">🤝 Foursome invitations — on</div>
        <div class="person-sub" style="padding:3px 0">💬 Comments on your posts — on</div>
        <div class="person-sub" style="padding:3px 0">📋 Tee time requests — on</div>
      </div>
    </div>`;
}

// ---------- Profile ----------

async function renderProfile(id) {
  let u;
  try {
    u = await api(id === "me" ? "/me" : `/users/${id}`);
  } catch (e) {
    $app.innerHTML = `<div class="card empty-note">Golfer not found. Probably in the trees on 13.</div>`;
    return;
  }
  const isMe = u.status === "self";

  const cta = isMe
    ? `<button class="btn btn-ghost" onclick="signOut()">Sign out</button>`
    : `
      ${u.status === "connected"
        ? `<button class="btn btn-ghost" disabled>✓ In your foursome</button>`
        : u.status === "pending"
          ? `<button class="btn btn-ghost" disabled>Invitation pending</button>`
          : u.status === "invited-me"
            ? `<button class="btn btn-primary" onclick="act(api('/users/${u.id}/connect', 'POST'), 'Connected ⛳')">Accept invitation</button>`
            : `<button class="btn btn-primary" onclick="connect(${u.id}, '${esc(u.name)}')">+ Pair up</button>`}
      <button class="btn btn-outline" onclick="go('messages/${u.id}')">Message</button>
      <button class="btn btn-danger" onclick="blockUser(${u.id}, '${esc(u.name)}')">Block</button>`;

  $app.innerHTML = `
    <div class="layout-2col">
      <div>
        <div class="card">
          <div class="profile-banner"></div>
          <div class="profile-head">
            ${avatar(u, "xl")}
            <div class="profile-name">${esc(u.name)}</div>
            <div class="profile-headline">${esc(u.headline)}</div>
            <div class="profile-loc">${[
              u.location && esc(u.location),
              u.homeCourse && `Home course: ${esc(u.homeCourse)}`,
              `${u.connections} connection${u.connections === 1 ? "" : "s"}`,
            ].filter(Boolean).join(" · ")}</div>
            <div class="profile-cta">${cta}</div>
          </div>
          <div class="stat-strip">
            <div class="stat-box"><b>${handicapLabel(u.handicap)}</b><span>Handicap index</span></div>
            <div class="stat-box"><b>${u.rounds}</b><span>Rounds logged</span></div>
            <div class="stat-box"><b>${u.best ?? "—"}</b><span>Best round</span></div>
          </div>
        </div>

        ${u.about ? `
          <div class="card card-pad">
            <h3 class="card-title">About</h3>
            <div style="font-size:14px;line-height:1.5">${esc(u.about)}</div>
          </div>` : ""}

        ${u.experience.length ? `
          <div class="card card-pad">
            <h3 class="card-title">Golf experience</h3>
            ${u.experience.map(x => `
              <div class="xp-item">
                <div class="xp-logo">${esc(x.icon)}</div>
                <div>
                  <div class="xp-title">${esc(x.title)}</div>
                  <div class="xp-sub">${esc(x.org)} · ${esc(x.period)}</div>
                  <div class="xp-desc">${esc(x.desc)}</div>
                </div>
              </div>`).join("")}
          </div>` : ""}

        <div class="card card-pad">
          <h3 class="card-title">Strengths${isMe ? "" : " · endorse what you've witnessed"}</h3>
          ${u.skills.map(s => `
            <div class="skill-row">
              <div>
                <div class="skill-name">${esc(s.name)}</div>
                <div class="skill-count">${s.endorsements} endorsement${s.endorsements === 1 ? "" : "s"}</div>
              </div>
              ${isMe ? "" : s.endorsedByMe
                ? `<button class="btn btn-ghost btn-sm" disabled>Endorsed ✓</button>`
                : `<button class="btn btn-outline btn-sm" onclick="act(api('/users/${u.id}/endorse', 'POST', {skillId: ${s.id}}), 'Endorsed 🏌️')">+ Endorse</button>`}
            </div>`).join("") || `<div class="empty-note">No strengths listed yet.</div>`}
        </div>
      </div>

      <div>
        ${u.courses.length ? `
          <div class="card card-pad">
            <h3 class="card-title">Courses played</h3>
            ${u.courses.map(c => `<div class="person-sub" style="padding:4px 0">⛳ ${esc(c)}</div>`).join("")}
          </div>` : ""}
      </div>
    </div>`;
}

// ---------- Search ----------

const searchInput = document.getElementById("searchInput");
const searchResults = document.getElementById("searchResults");
let searchTimer = null;

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (!q) { searchResults.classList.add("hidden"); return; }
  searchTimer = setTimeout(async () => {
    let data;
    try { data = await api("/users?q=" + encodeURIComponent(q)); } catch (e) { return; }
    searchResults.innerHTML = data.users.length
      ? data.users.map(u => `
          <div class="search-result" onclick="searchGo(${u.id})">
            ${avatar(u, "sm")}
            <div>
              <div style="font-weight:700;font-size:14px">${esc(u.name)}</div>
              <div class="person-sub">${esc(u.headline)}</div>
            </div>
          </div>`).join("")
      : `<div class="search-result">No golfers found — check the beverage cart</div>`;
    searchResults.classList.remove("hidden");
  }, 250);
});

document.addEventListener("click", e => {
  if (!e.target.closest(".search-wrap")) searchResults.classList.add("hidden");
});

function searchGo(id) {
  searchResults.classList.add("hidden");
  searchInput.value = "";
  go("profile/" + id);
}

// ---------- Router ----------

async function render() {
  clearTimeout(pollTimer);
  if (!token) { renderAuth(); return; }
  document.body.classList.remove("noauth");

  const parts = (location.hash.replace("#/", "") || "feed").split("/");
  try {
    switch (parts[0]) {
      case "network": await renderNetwork(); break;
      case "teetimes": await renderTeeTimes(); break;
      case "messages": await renderMessages(parts[1]); break;
      case "notifications": await renderNotifications(); break;
      case "profile": await renderProfile(parts[1] || "me"); break;
      default: await renderFeed();
    }
  } catch (e) {
    if (!e.api) throw e;
    $app.innerHTML = `<div class="card empty-note">${esc(e.message)}</div>`;
  }
  refreshChrome();
}

window.addEventListener("hashchange", () => {
  render();
  window.scrollTo(0, 0);
});
render();
