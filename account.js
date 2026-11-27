// The account box in the top-right corner of every logged-in page:
// "Sparkle99 · Admin tools · Log out". Without the server (e.g. GitHub Pages)
// nothing shows.
//
// window.siteLogout() is the one way to log out, used by the box and anywhere
// else. It closes a running game first (Ruffle writes its saves as it shuts
// down), uploads and clears this person's game saves (saves.js), then ends the
// session and goes to the log-in page.
(function () {
  function logout() {
    var game = document.querySelector("ruffle-player");
    if (game) game.remove();
    var saves = window.cloudSaves ? window.cloudSaves.logout() : Promise.resolve();
    return saves.catch(function () {}).then(function () {
      return fetch("/api/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}"
      });
    }).catch(function () {}).then(function () {
      location.href = "login.html";
    });
  }
  window.siteLogout = logout;

  function show(user) {
    var box = document.createElement("div");
    box.className = "corner-account";

    var name = document.createElement("strong");
    name.textContent = user.name;
    name.title = "Logged in as " + user.name;
    box.append(name);

    if (user.admin && !/\/admin\.html$/.test(location.pathname)) {
      var admin = document.createElement("a");
      admin.href = "admin.html";
      admin.textContent = "Admin tools";
      box.append(" · ", admin);
    }

    var out = document.createElement("button");
    out.type = "button";
    out.className = "link";
    out.textContent = "Log out";
    out.addEventListener("click", function () {
      out.disabled = true;
      out.textContent = "Logging out…";
      logout();
    });
    box.append(" · ", out);

    (document.querySelector(".site-bar") || document.body).append(box);
    document.body.classList.add("has-corner-account");
  }

  fetch("/api/me", { credentials: "same-origin" }).then(function (res) {
    var type = res.headers.get("Content-Type") || "";
    return res.ok && type.indexOf("application/json") !== -1 ? res.json() : null;
  }).then(function (data) {
    if (data && data.user) show(data.user);
  }).catch(function () {});
})();
