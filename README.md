# rscripts-cli

Browse [rscripts.net](https://rscripts.net) from your terminal — search scripts, view details, check trending, and copy raw Lua code.

Inspired by [uc-cli](https://github.com/overtimepog/uc-cli).

## Install

```bash
pip install rscripts-cli
```

Or from source:

```bash
git clone https://github.com/overtimepog/rscripts-cli
cd rscripts-cli
pip install -e .
```

## Usage

```
rs --help
```

### Browse scripts

```bash
# Latest scripts
rs scripts

# Search
rs scripts --search "blade ball"

# Filter options
rs scripts --free --no-key --mobile --verified
rs scripts --order-by views --sort desc
rs scripts --user SomeCreator
rs scripts --page 2
```

### View a script

```bash
rs script <id>

# Also show the raw Lua code
rs script <id> --raw
```

### Trending (last 48 h)

```bash
rs trending
```

### Get raw Lua source

```bash
rs raw <id>

# Pipe it somewhere
rs raw <id> > script.lua
```

### Hunt obfuscated scripts

Scans popular pages and/or search queries, fingerprints the obfuscator
(Luraph v1x, MoonSec, IronBrew, Synapse Xen, WeAreDevs, …), follows
`loadstring(game:HttpGet(...))` loader chains up to 3 hops, and saves the real
payloads with provenance headers.

```bash
# All obfuscated payloads from popular pages
rs hunt

# Luraph only, both sources, popular + "hub" searches, 5 pages each
rs hunt -s rscripts -s scriptblox -q "hub" --obf Luraph -p 5

# Game-specific (files land in ./hunt-all/)
rs hunt -q "infected lands" -q "zombies"
```

Results table shows obfuscator, version, title, provenance (source script ID +
payload URL). Each saved file carries the same provenance in a header comment.

### Find script gaps (popular games with few scripts)

Pulls every game on Roblox's explore page (plus deeper pages of Top Playing
Now / Up-and-Coming / Top Trending), then counts the scripts each game's root
place has on **both** rscripts and scriptblox. Ranks by players per recent
script — a high number means lots of players and little supply.

```bash
# Default: games with 1500+ players, "recent" = last 60 days
rs gaps

# Only near-empty games, hide ones you've already worked on
rs gaps -m 5000 --max-recent 2 --known notes/MEMORY.md --known hermes-work/ --hide-known

# Specific games
rs gaps --place 107535308163741 --place 9391468976

# Different window, dump every row
rs gaps --days 30 --json gaps.json

# Filter by genre (repeatable; -g = OR, -x = exclude)
rs gaps -g rpg -g roleplay
rs gaps -g fps -x "deathmatch"
rs gaps --list-genres          # what genres exist among candidates, with counts
```

Genre filters match, case-insensitively, against all three Roblox genre
levels: legacy `genre` (RPG, FPS, Horror…), `genre_l1` (Shooter, Survival,
Roleplay & Avatar Sim…) and `genre_l2` (Tycoon, Tower Defense, Deathmatch
Shooter…). Shorthands: `fps` → shooter, `rp` → roleplay, `td` → tower
defense, `pvp` → battlegrounds/fighting/shooter, `sim` → simulation. Genres
are filtered before counting, so narrow hunts are faster too.

How it counts:

- **scriptblox** is queried by place id (`/script/fetch?placeId=`), so its
  count doesn't depend on the title.
- **rscripts** has no place filter, so it searches by name and keeps only rows
  whose linked `game.placeId` matches. It also searches the older names the
  game was scripted under (taken from the scriptblox rows) and the title's
  segments, so a renamed game ("Vanguards: 2nd Anniversary" = Anime Vanguards)
  isn't reported as empty.
- Universal hubs (no linked place) never count toward a game.
- `+` after a count means the page cap was hit and the real total is higher —
  usually the very biggest games, where fuzzy search buries exact matches.

Per-game results are cached at `~/.cache/rscripts-cli/gaps.json` (override
with `--cache` or `RS_CACHE_DIR`) for `--ttl` hours (default 12). The cache
stores each matching row's date, so changing `--days` needs no re-fetch; use
`--refresh` to re-count. The MCP server exposes the same hunt as
`find_script_gaps`.

## Script ID

The `<id>` is the 24-character hex string shown in the ID column of `rs scripts` / `rs trending`, e.g. `6a2f2d5c25e0b3f946aa1088`.

## Attribution

Uses the [Rscripts public API](https://api.rscripts.net). Please include attribution in any applications you build with it.

## License

MIT
