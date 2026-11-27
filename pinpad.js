// The PIN number pad used by login.html and join.html.
//
//   var pad = PinPad({
//     input: <input>,        // shows the dots; a real keyboard can type into it
//     keypad: <div>,         // the buttons are drawn in here
//     length: 6,             // the last digit calls onComplete
//     onComplete: function (pin) {},
//     onEnter: function () {},   // Enter pressed (the form has no submit button)
//     active: function () { return true; },  // false: ignore the keyboard
//     busy: function () { return false; }    // true: ignore everything
//   });
//   pad.clear(); pad.focus(); pad.value();
//
// Keyboard: digits type, Backspace deletes, Esc clears, Enter calls onEnter.
// Typing in any other text box (e.g. the username) is left alone.
// PINs are this many digits. Keep in step with PIN_LENGTH in server/app.py.
var PIN_LENGTH = 6;

(function () {
  var KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

  window.PinPad = function (o) {
    var input = o.input, keypad = o.keypad, length = o.length;
    var busy = o.busy || function () { return false; };
    var active = o.active || function () { return true; };

    keypad.classList.add("keypad");
    keypad.setAttribute("role", "group");
    keypad.setAttribute("aria-label", "Number pad");
    KEYS.forEach(function (key) {
      var b = document.createElement("button");
      b.type = "button";
      b.dataset.key = key;
      if (key === "clear") {
        b.className = "quiet";
        b.textContent = "Clear";
        b.setAttribute("aria-label", "Clear PIN");
      } else if (key === "back") {
        b.className = "quiet";
        b.textContent = "⌫"; // ⌫
        b.setAttribute("aria-label", "Delete last digit");
      } else {
        b.textContent = key;
      }
      keypad.append(b);
    });

    // Light up the on-screen key a keyboard press matches.
    function flash(key) {
      var b = keypad.querySelector('[data-key="' + key + '"]');
      if (!b) return;
      b.classList.add("pressed");
      setTimeout(function () { b.classList.remove("pressed"); }, 120);
    }

    function set(value) {
      input.value = value.replace(/\D/g, "").slice(0, length);
      if (input.value.length === length && o.onComplete) o.onComplete(input.value);
    }

    function press(key) {
      if (busy()) return;
      if (key === "clear") set("");
      else if (key === "back") set(input.value.slice(0, -1));
      else set(input.value + key);
    }

    keypad.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-key]");
      if (b) press(b.dataset.key);
    });

    // Typing straight into the PIN box: keep digits only.
    input.addEventListener("input", function () { set(input.value); });

    document.addEventListener("keydown", function (e) {
      if (!active() || e.ctrlKey || e.metaKey || e.altKey) return;
      var t = e.target;
      if (t !== input && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "Enter") {
        // Let links and other buttons (e.g. Back) do their own thing.
        if (t.tagName === "A" || (t.tagName === "BUTTON" && !keypad.contains(t))) return;
        e.preventDefault();
        if (o.onEnter && !busy()) o.onEnter();
        return;
      }
      var key = /^[0-9]$/.test(e.key) ? e.key
              : e.key === "Backspace" ? "back"
              : e.key === "Escape" ? "clear"
              : null;
      if (!key) return;
      flash(key);
      if (t === input && key !== "clear") return; // the box handles its own typing
      e.preventDefault();
      press(key);
      input.focus();
    });

    return {
      clear: function () { input.value = ""; },
      focus: function () { input.focus(); },
      value: function () { return input.value; }
    };
  };
})();
