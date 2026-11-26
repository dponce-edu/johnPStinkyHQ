// The game list. The homepage and the player both read this file.
//
// To add a game:
//   1. Put the .swf in the games/ folder.
//   2. Add an entry below.
//
//   id     short name used in the link (play.html?game=<id>); letters, numbers, dashes
//   title  name shown on the card and the player page
//   file   path to the .swf
//   blurb  optional one-line description on the card
//   thumb  optional image path. If left out, the site looks for thumbs/<id>.png,
//          and shows a placeholder until that file exists.
//   ratio  optional player shape as "width / height" (default "4 / 3")

window.GAMES = [
  {
    id: "vvvvvv",
    title: "VVVVVV",
    file: "games/vvvvvv.swf",
    blurb: "Flip gravity instead of jumping.",
    ratio: "4 / 3"
  }
];
