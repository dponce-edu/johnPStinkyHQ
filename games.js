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
//
// Don't rename or move a .swf once people have played it: saves are tied to its path.

window.GAMES = [
  {
    id: "acid-factory",
    title: "Acid Factory",
    file: "games/acidfactory.swf"
  },
  {
    id: "amberial",
    title: "Amberial",
    file: "games/amberial.swf"
  },
  {
    id: "anime-face-maker",
    title: "Anime Face Maker",
    file: "games/animefacemaker.swf",
    blurb: "Design your own anime character."
  },
  {
    id: "avalanche",
    title: "Avalanche",
    file: "games/Avalanche.swf",
    blurb: "Climb the falling blocks before you're crushed."
  },
  {
    id: "cheese-dreams",
    title: "Cheese Dreams",
    file: "games/Cheese_Dreams.swf"
  },
  {
    id: "cover-orange",
    title: "Cover Orange",
    file: "games/coverorange.swf",
    blurb: "Shield the oranges from the toxic cloud."
  },
  {
    id: "cover-orange-2",
    title: "Cover Orange 2",
    file: "games/coverorange2.swf",
    blurb: "Shield the oranges from the toxic cloud."
  },
  {
    id: "dragon-maker",
    title: "Dragon Maker",
    file: "games/dragon_maker_by_wyndbain_d3khbvv.swf",
    blurb: "Design your own dragon."
  },
  {
    id: "fancy-pants-1",
    title: "Fancy Pants Adventures: World 1",
    file: "games/FPAWorld1.swf",
    blurb: "Fast, flowing stick-figure platforming."
  },
  {
    id: "fancy-pants-2",
    title: "Fancy Pants Adventures: World 2",
    file: "games/FPAWorld2.swf",
    blurb: "Fast, flowing stick-figure platforming."
  },
  {
    id: "fireboy-watergirl-forest-temple",
    title: "Fireboy & Watergirl: The Forest Temple",
    file: "games/Fireboy & Watergirl - The Forest Temple.swf",
    blurb: "Two-player puzzle platformer. Fire and water don't mix."
  },
  {
    id: "flip-man",
    title: "Flip Man",
    file: "games/FLIP-MAN-GAME.swf"
  },
  {
    id: "learn-to-fly",
    title: "Learn to Fly",
    file: "games/learn-to-fly.swf",
    blurb: "Launch a penguin, buy upgrades, fly farther."
  },
  {
    id: "my-new-room",
    title: "My New Room",
    file: "games/my_new_room_girlsgogames_com_v1_01.swf",
    blurb: "Decorate a room your way."
  },
  {
    id: "papa-louie",
    title: "Papa Louie: When Pizzas Attack!",
    file: "games/papalouie_miniclip.swf",
    blurb: "Rescue the customers from pizza monsters."
  },
  {
    id: "pokemon-towering-legends",
    title: "Pokémon Towering Legends",
    file: "games/pokemon-towering-legends.swf",
    blurb: "Pokémon fan tower defense."
  },
  {
    id: "powerpuff-girls-puppybots",
    title: "The Powerpuff Girls: Attack of the Puppybots",
    file: "games/the_powerpuff_girls___attack_of_the_puppybots_by_oldadobeflashgames01_de16186.swf"
  },
  {
    id: "red-ball",
    title: "Red Ball: Definitive Edition",
    file: "games/Red Ball - Definitive Edition.swf",
    blurb: "Roll, bounce and push your way through each level."
  },
  {
    id: "riddle-school",
    title: "Riddle School",
    file: "games/riddleschool.swf",
    blurb: "Point-and-click your way out of school."
  },
  {
    id: "rubble-trouble-moscow",
    title: "Rubble Trouble: Moscow",
    file: "games/Rubble_Trouble_Moscow.swf",
    blurb: "Demolish buildings with explosives."
  },
  {
    id: "rubble-trouble-new-york",
    title: "Rubble Trouble: New York",
    file: "games/Rubble_Trouble_New_York.swf",
    blurb: "Demolish buildings with explosives."
  },
  {
    id: "rubble-trouble-tokyo",
    title: "Rubble Trouble: Tokyo",
    file: "games/Rubble_Trouble_Tokyo.swf",
    blurb: "Demolish buildings with explosives."
  },
  {
    id: "skywire",
    title: "Skywire",
    file: "games/Skywire.swf",
    blurb: "Get the cable car safely to the end of the line."
  },
  {
    id: "toxic-2",
    title: "Toxic 2",
    file: "games/Toxic_2.swf"
  },
  {
    id: "unfair-mario",
    title: "Unfair Mario",
    file: "games/unfair_mario.swf",
    blurb: "A Mario-style platformer full of nasty traps."
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
    file: "games/wolf_maker_by_wyndbain_d2ytg7v.swf",
    blurb: "Design your own wolf."
  }
];
