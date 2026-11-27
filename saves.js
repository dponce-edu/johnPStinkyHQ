// Flash game saves, kept with each person's account on the server.
//
// Ruffle keeps a game's saves in this browser's localStorage, one entry per
// save, named "<site>/<path>/<save name>" (e.g. "example.com/games/run.swf/save")
// with the save data as base64. This file copies those entries:
//   - down from the server before a game starts, so the game finds them, and
//   - up to the server while playing (every 15 s) and when leaving the page.
//
// Shared computers: the browser remembers whose saves it holds. If someone
// else logs in, the last person's saves are wiped from the browser first
// (they're already on the server), so nobody plays on someone else's save.
//
// Without the server (e.g. GitHub Pages) none of this runs and saves stay in
// the browser like before.
(function () {
  var OWNER = "ce-saves-owner";   // whose saves this browser holds
  var PREFIX = location.hostname + "/";
  var KEEPALIVE_LIMIT = 60000;    // browsers cap keepalive uploads at 64 KB

  var enabled = false;
  var synced = {};                // what the server has, as far as we know
  var sending = null;

  function gameKeys() {
    var keys = [];
    for (var i = 0; i < localStorage.length; i++) {
      var k = localStorage.key(i);
      if (k && k.indexOf(PREFIX) === 0) keys.push(k);
    }
    return keys;
  }

  function wipeLocal() {
    gameKeys().forEach(function (k) { localStorage.removeItem(k); });
  }

  function snapshot() {
    var now = {};
    gameKeys().forEach(function (k) { now[k] = localStorage.getItem(k); });
    return now;
  }

  function changes() {
    var now = snapshot(), put = {}, del = [], any = false;
    Object.keys(now).forEach(function (k) {
      if (synced[k] !== now[k]) { put[k] = now[k]; any = true; }
    });
    Object.keys(synced).forEach(function (k) {
      if (!(k in now)) { del.push(k); any = true; }
    });
    return any ? { now: now, body: { put: put, delete: del } } : null;
  }

  function post(body, keepalive) {
    return fetch("/api/saves", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: body,
      keepalive: keepalive
    }).then(function (res) {
      if (!res.ok) throw new Error("save upload failed: " + res.status);
    });
  }

  // Upload whatever changed since the last upload.
  function push(leaving) {
    if (!enabled) return Promise.resolve();
    if (sending && !leaving) return sending;
    var c = changes();
    if (!c) return Promise.resolve();
    var body = JSON.stringify(c.body);
    var p = post(body, leaving && body.length < KEEPALIVE_LIMIT).then(function () {
      synced = c.now;
    }).catch(function (err) {
      console.warn(err); // try again next time
    }).then(function () { sending = null; });
    if (!leaving) sending = p;
    return p;
  }

  // Call before the game loads. Always resolves; if the server can't be
  // reached in time, the game still starts with whatever the browser has and
  // nothing is uploaded, so a stale copy can't overwrite the server's.
  function start() {
    var timedOut = false;
    var load = fetch("/api/saves", { credentials: "same-origin" }).then(function (res) {
      var type = res.headers.get("Content-Type") || "";
      if (!res.ok || type.indexOf("application/json") === -1) return null;
      return res.json();
    }).then(function (data) {
      if (!data || !data.user || timedOut) return; // too late: the game has started
      var owner = localStorage.getItem(OWNER);
      var server = data.saves || {};
      if (owner && owner !== data.user) {
        wipeLocal(); // someone else's saves
      }
      // Saves made in this browser before cloud saves existed: keep them
      // (uploaded below) unless the server already has that save.
      Object.keys(server).forEach(function (k) { localStorage.setItem(k, server[k]); });
      localStorage.setItem(OWNER, data.user);
      synced = server;
      enabled = true;
      return push();
    }).catch(function (err) { console.warn("cloud saves off:", err); });

    var timeout = new Promise(function (resolve) {
      setTimeout(function () { timedOut = true; resolve(); }, 5000);
    });
    return Promise.race([load, timeout]).then(function () {
      if (!enabled) return; // timed out or no server: leave saves alone
      setInterval(function () { push(); }, 15000);
      document.addEventListener("visibilitychange", function () {
        if (document.visibilityState === "hidden") push();
      });
    });
  }

  // Ruffle writes any unsaved data on "pagehide" too. Listeners run in the
  // order they were added, so call this after the player exists to upload
  // after Ruffle has written.
  function watchLeaving() {
    window.addEventListener("pagehide", function () { push(true); });
  }

  // Log out: upload what's left, then take this person's saves off the browser.
  function logout() {
    return push(true).then(function () {
      enabled = false;
      wipeLocal();
      localStorage.removeItem(OWNER);
    });
  }

  window.cloudSaves = { start: start, watchLeaving: watchLeaving, logout: logout };
})();
