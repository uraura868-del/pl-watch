/* PL Watch Service Worker
 * 役割: ホーム画面への追加（インストール）を可能にし、画面の骨組みだけオフラインでも開けるようにする。
 * データ（data/ 以下）は常にネットワークから取り、キャッシュしない（古いスタメンが出ないように）。 */
const CACHE = "plwatch-shell-v1";
const SHELL = ["./", "./index.html", "./assets/style.css", "./assets/app.js", "./assets/firebase-config.js", "./teams.json", "./manifest.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => null));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  // データは常にネットワーク（失敗時のみキャッシュ）。骨組みはネットワーク優先で、落ちていればキャッシュ
  if (sameOrigin && !url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(req).then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone())).catch(() => null);
        return res;
      }).catch(() => caches.match(req).then((hit) => hit || (req.mode === "navigate" ? caches.match("./index.html") : undefined)))
    );
  }
});
