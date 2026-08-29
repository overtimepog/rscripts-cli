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

## Script ID

The `<id>` is the 24-character hex string shown in the ID column of `rs scripts` / `rs trending`, e.g. `6a2f2d5c25e0b3f946aa1088`.

## Attribution

Uses the [Rscripts public API](https://api.rscripts.net). Please include attribution in any applications you build with it.

## License

MIT
