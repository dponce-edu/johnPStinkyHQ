// Ratings, comments and log-in on the game page.
// Talks to server/app.py at /api/. If the API isn't there (for example on
// GitHub Pages, which only serves files) the section stays hidden.
(function () {
  var section = document.getElementById("community");
  var gameId = new URLSearchParams(location.search).get("game");
  if (!section || !gameId) return;

  var el = {
    stars: document.getElementById("stars"),
    summary: document.getElementById("rating-summary"),
    account: document.getElementById("account"),
    form: document.getElementById("comment-form"),
    body: document.getElementById("comment-body"),
    count: document.getElementById("comment-count"),
    msg: document.getElementById("community-msg"),
    list: document.getElementById("comments")
  };
  var state = { user: null, rating: null, comments: [] };

  // ---- talking to the server

  function api(method, path, body) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (method !== "GET") {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body || {});
    }
    return fetch(path, opts).then(function (res) {
      var type = res.headers.get("Content-Type") || "";
      if (type.indexOf("application/json") === -1) {
        throw { offline: true, message: "The comments server isn't reachable." };
      }
      return res.json().then(function (data) {
        if (!res.ok) throw { status: res.status, message: data.error || "Something went wrong." };
        return data;
      });
    }, function () {
      throw { offline: true, message: "Couldn't reach the server. Check your connection." };
    });
  }

  function say(text) { el.msg.textContent = text || ""; }
  function fail(err) { say(err && err.message ? err.message : "Something went wrong."); }

  // ---- rating

  function renderRating() {
    var r = state.rating;
    var mine = r && r.mine;
    el.stars.replaceChildren();
    for (var i = 1; i <= 5; i++) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = "★";
      b.className = mine && i <= mine ? "on" : "";
      b.setAttribute("aria-label", "Rate " + i + " star" + (i > 1 ? "s" : ""));
      b.setAttribute("aria-pressed", String(mine === i));
      b.dataset.stars = i;
      el.stars.appendChild(b);
    }
    var text = r && r.count
      ? "Average " + r.avg.toFixed(1) + " from " + r.count + " rating" + (r.count === 1 ? "" : "s") + "."
      : "No ratings yet.";
    if (mine) text += " You gave it " + mine + ".";
    else if (!state.user) text += " Log in to rate.";
    el.summary.textContent = text;
  }

  el.stars.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    if (!state.user) { say("Log in below to rate this game."); return; }
    api("PUT", "/api/games/" + gameId + "/rating", { stars: Number(b.dataset.stars) })
      .then(function (data) { state.rating = data.rating; renderRating(); say(""); }, fail);
  });

  // ---- account

  function renderAccount() {
    el.account.replaceChildren();
    if (state.user) {
      // Log out lives in the top-right corner (account.js).
      var p = document.createElement("p");
      p.className = "muted";
      p.append("Commenting as ");
      var b = document.createElement("strong");
      b.textContent = state.user.name;
      p.append(b);
      el.account.append(p);
      el.form.hidden = false;
      return;
    }
    // Logged out while on this page (e.g. the session ran out): send them to
    // the PIN log-in page, which brings them back here afterwards.
    el.form.hidden = true;
    var p = document.createElement("p");
    var a = document.createElement("a");
    a.href = "login.html?next=" + encodeURIComponent(location.pathname + location.search);
    a.textContent = "Log in";
    p.append(a, " to rate and comment.");
    el.account.append(p);
  }

  function setUser(user) {
    state.user = user;
    renderAccount();
    renderRating();
    renderComments();
  }

  // ---- comments

  function ago(seconds) {
    var s = Math.max(0, Date.now() / 1000 - seconds);
    if (s < 60) return "just now";
    var units = [[86400 * 365, "year"], [86400 * 30, "month"], [86400, "day"], [3600, "hour"], [60, "minute"]];
    for (var i = 0; i < units.length; i++) {
      var n = Math.floor(s / units[i][0]);
      if (n >= 1) return n + " " + units[i][1] + (n > 1 ? "s" : "") + " ago";
    }
    return "just now";
  }

  function renderComments() {
    el.list.replaceChildren();
    if (!state.comments.length) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "No comments yet. Be the first!";
      el.list.append(empty);
      return;
    }
    state.comments.forEach(function (c) {
      var li = document.createElement("li");
      var meta = document.createElement("p");
      meta.className = "meta";
      var who = document.createElement("strong");
      who.textContent = c.user;
      var when = document.createElement("time");
      when.dateTime = new Date(c.created * 1000).toISOString();
      when.title = new Date(c.created * 1000).toLocaleString();
      when.textContent = ago(c.created);
      meta.append(who, " · ", when);
      if (c.canDelete) {
        var del = document.createElement("button");
        del.type = "button";
        del.className = "link";
        del.textContent = "Delete";
        del.addEventListener("click", function () { confirmDelete(c, del); });
        meta.append(" · ", del);
      }
      if (c.reported) {
        meta.append(" · Reported");
      } else if (c.canReport) {
        var rep = document.createElement("button");
        rep.type = "button";
        rep.className = "link";
        rep.textContent = "Report";
        rep.addEventListener("click", function () { confirmReport(c, rep); });
        meta.append(" · ", rep);
      }
      if (c.reports) { // only sent to admins
        var flag = document.createElement("span");
        flag.className = "flagged";
        flag.textContent = "⚑ " + c.reports + " report" + (c.reports === 1 ? "" : "s");
        meta.append(" · ", flag);
      }
      var body = document.createElement("p");
      body.className = "body";
      body.textContent = c.body; // plain text only, never HTML
      li.append(meta, body);
      el.list.append(li);
    });
  }

  // Two-step delete: first click asks, second click within 4 seconds deletes.
  function confirmDelete(comment, button) {
    if (button.dataset.armed) {
      api("DELETE", "/api/comments/" + comment.id).then(function () {
        state.comments = state.comments.filter(function (c) { return c.id !== comment.id; });
        renderComments();
        say("Comment deleted.");
      }, fail);
      return;
    }
    button.dataset.armed = "1";
    button.textContent = "Really delete?";
    setTimeout(function () {
      if (!button.isConnected) return;
      delete button.dataset.armed;
      button.textContent = "Delete";
    }, 4000);
  }

  // Same two-step pattern as delete, so a stray click doesn't report anyone.
  function confirmReport(comment, button) {
    if (button.dataset.armed) {
      button.disabled = true;
      api("POST", "/api/comments/" + comment.id + "/report").then(function () {
        comment.reported = true;
        renderComments();
        say("Thanks. A teacher will take a look.");
      }, function (err) {
        button.disabled = false;
        fail(err);
      });
      return;
    }
    button.dataset.armed = "1";
    button.textContent = "Report this comment?";
    setTimeout(function () {
      if (!button.isConnected || button.disabled) return;
      delete button.dataset.armed;
      button.textContent = "Report";
    }, 4000);
  }

  function updateCount() {
    el.count.textContent = el.body.value.length + " / 1000";
  }
  el.body.addEventListener("input", updateCount);

  el.form.addEventListener("submit", function (e) {
    e.preventDefault();
    var text = el.body.value.trim();
    if (!text) return;
    var post = el.form.querySelector("button[type=submit]");
    post.disabled = true;
    api("POST", "/api/games/" + gameId + "/comments", { body: text }).then(function (data) {
      state.comments.unshift(data.comment);
      el.body.value = "";
      updateCount();
      renderComments();
      say("Comment posted.");
    }, fail).then(function () { post.disabled = false; });
  });

  // ---- start

  function refresh() {
    return api("GET", "/api/games/" + gameId).then(function (data) {
      state.rating = data.rating;
      state.comments = data.comments;
      renderRating();
      renderComments();
    });
  }

  Promise.all([api("GET", "/api/me"), refresh()]).then(function (results) {
    state.user = results[0].user;
    renderAccount();
    renderRating();
    renderComments();
    updateCount();
    section.hidden = false;
  }, function () {
    // No API here (or unknown game): leave the section hidden.
  });
})();
