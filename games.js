// The game list. The homepage and the player both read this file.
//
// To add a game:
//   1. Put the .swf in the games/ folder, named <id>.swf (e.g. games/red-ball.swf).
//   2. Add an entry below.
//
//   id     short name used in the link (play.html?game=<id>); letters, numbers, dashes
//   title  name shown on the card and the player page
//   file   path to the .swf
//   blurb  optional one-line description on the card
//   thumb  optional image path. If left out, the site looks for thumbs/<id>.png,
//          and shows a placeholder until that file exists.
//   ratio  optional player shape as "width / height". Usually not needed: the
//          player sizes itself to the game once it loads.
//
// Don't rename or move a .swf once people have played it: saves are tied to its path.

window.GAMES = [
  {
    id: "amberial",
    title: "Amberial",
    file: "games/amberial.swf",
    blurb: "Momentum-based platformer."
  },
  {
    id: "anime-face-maker",
    title: "Anime Face Maker",
    file: "games/anime-face-maker.swf",
    blurb: "Design your own anime character."
  },
  {
    id: "avalanche",
    title: "Avalanche",
    file: "games/avalanche.swf",
    blurb: "Climb the falling blocks before you're crushed."
  },
  {
    id: "awesome-tanks",
    title: "Awesome Tanks",
    file: "games/awesome-tanks.swf",
    blurb: "Blast enemy tanks and upgrade your own."
  },
  {
    id: "bloxorz",
    title: "Bloxorz",
    file: "games/bloxorz.swf",
    blurb: "Roll the block into the square hole."
  },
  {
    id: "cheese-dreams",
    title: "Cheese Dreams",
    file: "games/cheese-dreams.swf",
    blurb: "Bouncy cheesy and a little platformy."
  },
  {
    id: "cover-orange",
    title: "Cover Orange",
    file: "games/cover-orange.swf",
    blurb: "Shield the oranges from the toxic cloud."
  },
  {
    id: "cover-orange-2",
    title: "Cover Orange 2",
    file: "games/cover-orange-2.swf",
    blurb: "Shield the oranges from the toxic cloud, again!"
  },
  {
    id: "devilish-cooking",
    title: "Devilish Cooking",
    file: "games/devilish-cooking.swf",
    blurb: "Cook up some mischief."
  },
  {
    id: "devilish-hairdresser",
    title: "Devilish Hairdresser",
    file: "games/devilish-hairdresser.swf",
    blurb: "Give your customers the haircut they deserve."
  },
  {
    id: "dragon-maker",
    title: "Dragon Maker",
    file: "games/dragon-maker.swf",
    blurb: "Design your own dragon."
  },
  {
    id: "fancy-pants-1",
    title: "Fancy Pants Adventures: World 1",
    file: "games/fancy-pants-1.swf",
    blurb: "He's fast, he's fearless... and he's got Fancy Pants!"
  },
  {
    id: "fancy-pants-2",
    title: "Fancy Pants Adventures: World 2",
    file: "games/fancy-pants-2.swf",
    blurb: "The Adventures of Fancy Pants Man 2: Electric Boogaloo!"
  },
  {
    id: "fireboy-watergirl-forest-temple",
    title: "Fireboy & Watergirl: The Forest Temple",
    file: "games/fireboy-watergirl-forest-temple.swf",
    blurb: "Two-player puzzle platformer. Fire and water don't mix."
  },
  {
    id: "flip-man",
    title: "Flip Man",
    file: "games/flip-man.swf",
    blurb: "Flip that man!"
  },
  {
    id: "learn-to-fly",
    title: "Learn to Fly",
    file: "games/learn-to-fly.swf",
    blurb: "Launch a penguin, buy upgrades, learn! To! Fly!"
  },
  {
    id: "learn-to-fly-2",
    title: "Learn to Fly 2",
    file: "games/learn-to-fly-2.swf",
    blurb: "The penguin is back, and still determined to fly."
  },
  {
    id: "my-new-room",
    title: "My New Room",
    file: "games/my-new-room.swf",
    blurb: "Decorate a room your way."
  },
  {
    id: "pokemon-towering-legends",
    title: "Pokémon Towering Legends",
    file: "games/pokemon-towering-legends.swf",
    blurb: "Pokémon fan tower-building-time-tester!"
  },
  {
    id: "powerpuff-girls-puppybots",
    title: "The Powerpuff Girls: Attack of the Puppybots",
    file: "games/powerpuff-girls-puppybots.swf",
    blurb: "Beat this bullet-mania as Bubbles, Blossom, and Buttercup."
  },
  {
    id: "raft-wars",
    title: "Raft Wars",
    file: "games/raft-wars.swf",
    blurb: "Defend your treasure from raft-riding raiders."
  },
  {
    id: "raft-wars-2",
    title: "Raft Wars 2",
    file: "games/raft-wars-2.swf",
    blurb: "More rafts, more water balloons, more war."
  },
  {
    id: "red-ball",
    title: "Red Ball: Definitive Edition",
    file: "games/red-ball.swf",
    blurb: "Roll, bounce and push your way through each level."
  },
  {
    id: "riddle-school",
    title: "Riddle School",
    file: "games/riddle-school.swf",
    blurb: "Point-and-click your way out of school."
  },
  {
    id: "rubble-trouble-moscow",
    title: "Rubble Trouble: Moscow",
    file: "games/rubble-trouble-moscow.swf",
    blurb: "гул!!! гул!!! гул!!!"
  },
  {
    id: "rubble-trouble-new-york",
    title: "Rubble Trouble: New York",
    file: "games/rubble-trouble-new-york.swf",
    blurb: "BOOM!!! BOOSH!!! BADOOOOOOOM!!!"
  },
  {
    id: "rubble-trouble-tokyo",
    title: "Rubble Trouble: Tokyo",
    file: "games/rubble-trouble-tokyo.swf",
    blurb: "EXPLOSIONS!!! BUILDINGS!!! MASS DESTRUCTION!!!"
  },
  {
    id: "skywire",
    title: "Skywire",
    file: "games/skywire.swf",
    blurb: "Get the cable car safely to the end of the line."
  },
  {
    id: "super-mario-63",
    title: "Super Mario 63",
    file: "games/super-mario-63.swf",
    blurb: "Fan-made Mario adventure collecting Shine Sprites and Star Coins."
  },
  {
    id: "toxic-2",
    title: "Toxic 2",
    file: "games/toxic-2.swf",
    blurb: "That's... a lot of goo."
  },
  {
    id: "unfair-mario",
    title: "Unfair Mario",
    file: "games/unfair-mario.swf",
    blurb: "A Mario-style platformer with a few surprises along the way."
  },
  {
    id: "vvvvvv",
    title: "VVVVVV",
    file: "games/vvvvvv.swf",
    blurb: "Flip gravity instead of jumping.",
    ratio: "4 / 3"
  },
  {
    id: "wolf-maker",
    title: "Wolf Maker",
    file: "games/wolf-maker.swf",
    blurb: "Design your own wolf."
  }
];
