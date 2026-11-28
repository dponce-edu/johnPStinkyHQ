# Game stubs

Harmless stand-ins for outside services some old games call when they start
(publisher counters, trackers) that no longer exist. A game's `urlRewrite`
setting in games.js points those requests here, so the game gets the same
quick answer every time instead of a blocked request.

- `empty.txt`: an empty reply.
- `empty.swf`: the smallest valid Flash file (one empty frame).
