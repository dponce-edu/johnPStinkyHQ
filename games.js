// The game list. The homepage and the player both read this file.
//
// To add a game:
//   1. Put the .swf in the games/ folder, named <id>.swf (e.g. games/red-ball.swf).
//      games/ isn't in git; copy it to the server with rsync (server/README.md).
//   2. Add an entry below.
//
//   id     short name used in the link (play.html?game=<id>); letters, numbers, dashes
//   title  name shown on the card and the player page
//   file   path to the .swf
//   blurb  optional one-line description on the card
//   ratio  optional player shape as "width / height". Usually not needed: the
//          player sizes itself to the game once it loads.
//
// Don't rename or move a .swf once people have played it: saves are tied to its path.
//
// Hidden games go in games/hidden/ instead: the .swf files and their own list,
// games/hidden/games.js. Only admins and accounts allowed to see hidden games
// (admin page, or `python3 server/app.py allow-hidden NAME`) can load anything
// in that folder; for them, hidden games work just like these. That list adds
// to this one; start it from this template:
//
//   window.GAMES = (window.GAMES || []).concat([
//     {
//       id: "secret-game",
//       title: "Secret Game",
//       file: "games/hidden/secret-game.swf"
//     }
//   ]).sort(function (a, b) { return a.title.localeCompare(b.title); });

window.GAMES = [
  {
    id: "amberial",
    title: "Amberial",
    file: "games/amberial.swf",
    blurb: "Momentum-based platformer."
  },
  {
    id: "amberial-nebulosa",
    title: "Amberial: Nebulosa Realms",
    file: "games/amberial-nebulosa.swf",
    blurb: "The AmberBall is back: 22 new levels and a tower of glory."
  },
  {
    id: "angry-birds",
    title: "Angry Birds",
    file: "games/angry-birds.swf",
    blurb: "Fling birds, topple pigs."
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
    id: "bejeweled-2",
    title: "Bejeweled 2",
    file: "games/bejeweled-2.swf",
    blurb: "Swap gems to line up three or more."
  },
  {
    id: "bejeweled-twist",
    title: "Bejeweled Twist",
    file: "games/bejeweled-twist.swf",
    blurb: "Rotate gems in fours to make matches."
  },
  {
    id: "bloxorz",
    title: "Bloxorz",
    file: "games/bloxorz.swf",
    blurb: "Roll the block into the square hole."
  },
  {
    id: "cactus-mccoy",
    title: "Cactus McCoy and the Curse of Thorns",
    file: "games/cactus-mccoy.swf",
    blurb: "Punch, shoot and lasso your way across the Wild West."
  },
  {
    id: "cactus-mccoy-2",
    title: "Cactus McCoy 2: The Ruins of Calavera",
    file: "games/cactus-mccoy-2.swf",
    blurb: "Cactus is back, and the Enemigos want the Calavera treasure."
  },
  {
    id: "cheese-dreams",
    title: "Cheese Dreams",
    file: "games/cheese-dreams.swf",
    blurb: "Bouncy cheesy and a little platformy."
  },
  {
    id: "cheese-dreams-new-moon",
    title: "Cheese Dreams: New Moon",
    file: "games/cheese-dreams-new-moon.swf",
    blurb: "More bouncy, cheesy platforming."
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
    id: "devilish-candy-house",
    title: "Devilish Candy House",
    file: "games/devilish-candy-house.swf",
    blurb: "Build a candy house, or sneakily wreck one."
  },
  {
    id: "devilish-cat",
    title: "Devilish Cat",
    file: "games/devilish-cat.swf",
    blurb: "Look after a cat, or play pranks on it."
  },
  {
    id: "devilish-christmas",
    title: "Devilish Christmas",
    file: "games/devilish-christmas.swf",
    blurb: "Holiday mischief."
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
    id: "fancy-pants-3",
    title: "Fancy Pants Adventures: World 3",
    file: "games/fancy-pants-3.swf",
    blurb: "Fancy Pants Man is back for more."
  },
  {
    id: "fireboy-watergirl-forest-temple",
    title: "Fireboy & Watergirl: The Forest Temple",
    file: "games/fireboy-watergirl-forest-temple.swf",
    blurb: "Two-player puzzle platformer. Fire and water don't mix."
  },
  {
    id: "fireboy-watergirl-ice-temple",
    title: "Fireboy & Watergirl: The Ice Temple",
    file: "games/fireboy-watergirl-ice-temple.swf",
    blurb: "Two-player puzzle platformer on slippery ice."
  },
  {
    id: "fireboy-watergirl-light-temple",
    title: "Fireboy & Watergirl: The Light Temple",
    file: "games/fireboy-watergirl-light-temple.swf",
    blurb: "Two-player puzzles with mirrors and beams of light."
  },
  {
    id: "flip-man",
    title: "Flip Man",
    file: "games/flip-man.swf",
    blurb: "Flip that man!"
  },
  {
    id: "home-run-derby",
    title: "Home Run Derby",
    file: "games/home-run-derby.swf",
    blurb: "Swing for the fences."
  },
  {
    id: "jacksmith",
    title: "Jacksmith",
    file: "games/jacksmith.swf",
    blurb: "Forge weapons for your army, then watch them fight."
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
    id: "line-rider-2",
    title: "Line Rider 2",
    file: "games/line-rider-2.swf",
    blurb: "Draw a track and watch the rider go."
  },
  {
    id: "my-new-room",
    title: "My New Room",
    file: "games/my-new-room.swf",
    blurb: "Decorate a room your way."
  },
  {
    id: "n",
    title: "N",
    file: "games/n.swf",
    blurb: "Ninja platformer. Dodge the drones, grab the gold."
  },
  {
    id: "pac-man",
    title: "Pac-Man",
    file: "games/pac-man.swf",
    blurb: "Eat the dots, dodge the ghosts."
  },
  {
    id: "papa-louie",
    title: "Papa Louie: When Pizzas Attack!",
    file: "games/papa-louie.swf",
    blurb: "Rescue the customers from the pizza monsters."
  },
  {
    id: "papa-louie-2",
    title: "Papa Louie 2: When Burgers Attack!",
    file: "games/papa-louie-2.swf",
    blurb: "Burgers have gone wild. Save the day!"
  },
  {
    id: "papa-louie-3",
    title: "Papa Louie 3: When Sundaes Attack!",
    file: "games/papa-louie-3.swf",
    blurb: "Sweet treats, sour villains."
  },
  {
    id: "papas-bakeria",
    title: "Papa's Bakeria",
    file: "games/papas-bakeria.swf",
    blurb: "Bake pies to order and keep customers happy."
  },
  {
    id: "papas-burgeria",
    title: "Papa's Burgeria",
    file: "games/papas-burgeria.swf",
    blurb: "Grill, build and serve the perfect burger."
  },
  {
    id: "papas-cheeseria",
    title: "Papa's Cheeseria",
    file: "games/papas-cheeseria.swf",
    blurb: "Grilled cheese and fries, made to order."
  },
  {
    id: "papas-cupcakeria",
    title: "Papa's Cupcakeria",
    file: "games/papas-cupcakeria.swf",
    blurb: "Bake, frost and top cupcakes for every season."
  },
  {
    id: "papas-donuteria",
    title: "Papa's Donuteria",
    file: "games/papas-donuteria.swf",
    blurb: "Shape, fry and decorate donuts."
  },
  {
    id: "papas-freezeria",
    title: "Papa's Freezeria",
    file: "games/papas-freezeria.swf",
    blurb: "Blend sundaes on a sunny island."
  },
  {
    id: "papas-hot-doggeria",
    title: "Papa's Hot Doggeria",
    file: "games/papas-hot-doggeria.swf",
    blurb: "Hot dogs, drinks and popcorn at the ballpark."
  },
  {
    id: "papas-pancakeria",
    title: "Papa's Pancakeria",
    file: "games/papas-pancakeria.swf",
    blurb: "Flip pancakes and pour drinks for the breakfast rush."
  },
  {
    id: "papas-pastaria",
    title: "Papa's Pastaria",
    file: "games/papas-pastaria.swf",
    blurb: "Cook pasta just right and serve it with bread."
  },
  {
    id: "papas-pizzeria",
    title: "Papa's Pizzeria",
    file: "games/papas-pizzeria.swf",
    blurb: "Take orders, top pizzas, keep customers happy."
  },
  {
    id: "papas-scooperia",
    title: "Papa's Scooperia",
    file: "games/papas-scooperia.swf",
    blurb: "Scoop ice cream onto fresh-baked cookies."
  },
  {
    id: "pokemon-towering-legends",
    title: "Pokémon Towering Legends",
    file: "games/pokemon-towering-legends.swf",
    blurb: "Pokémon fan tower-building-time-tester!"
  },
  {
    id: "portal",
    title: "Portal: The Flash Version",
    file: "games/portal.swf",
    blurb: "Think with portals, in 2D."
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
    id: "red-ball-2",
    title: "Red Ball 2",
    file: "games/red-ball-2.swf",
    blurb: "More rolling, more bouncing."
  },
  {
    id: "red-ball-3",
    title: "Red Ball 3",
    file: "games/red-ball-3.swf",
    blurb: "Roll on through a brand new set of levels."
  },
  {
    id: "red-ball-4-vol-1",
    title: "Red Ball 4: Volume 1",
    file: "games/red-ball-4-vol-1.swf",
    blurb: "Stop the evil black squares from squaring the world."
  },
  {
    id: "red-ball-4-vol-2",
    title: "Red Ball 4: Volume 2",
    file: "games/red-ball-4-vol-2.swf",
    blurb: "The squares are back. Roll them out."
  },
  {
    id: "red-ball-4-vol-3",
    title: "Red Ball 4: Volume 3",
    file: "games/red-ball-4-vol-3.swf",
    blurb: "Into the factory for the final fight."
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
    id: "run",
    title: "Run",
    file: "games/run.swf",
    blurb: "Run and jump through a tunnel in space."
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
    id: "ultimate-flash-sonic",
    title: "Ultimate Flash Sonic",
    file: "games/ultimate-flash-sonic.swf",
    blurb: "Gotta go fast!"
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
