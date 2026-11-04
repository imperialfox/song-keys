# song-keys

A list of vocal songs, built to suggest each song's original key in a singing app. The key is only ever a suggestion, and the singer can always change it.

This repo is app-neutral. Apps pin a copy of the data and keep their own settings.

## What's here now (0.1.0)

The **artist fan-out**. It starts from a private list of seed artists, then:

1. finds up to 3 similar artists for each seed (layer 2),
2. finds 1 more for each of those (layer 3),
3. takes up to 5 best-known vocal songs for each new artist.

Artists that both Last.fm and ListenBrainz name rank first. Instrumentals are dropped, both by title words and by the artist's top Last.fm tag.

The output is `data/neighbours.json`. It holds artist and title only, with no keys yet. Each run writes a short receipt to `data/build-receipt.md`.

Keys come later, from several sources voting on each song.

## Running it

It runs as a GitHub Action, by hand: **Actions › Build neighbours › Run workflow**, then pick `dry` (first 10 seeds) or `full`.

It needs two repo secrets.
- `LASTFM_API_KEY` is a Last.fm API key.
- `SEED_ARTISTS` is the seed artists, one per line.
- `SKIP_ARTISTS` is optional. It lists other artists to never pick, one per line, so every pick is new to the seed owner.

A full run makes about 10,000 requests at one per second per service, which takes 2 to 3 hours. If it runs out of time it saves what it has and marks the receipt `PARTIAL`. Running it again carries on from the cache.

To test it offline with made-up artists, run `python3 -I tests/test_fetch.py`.

## Privacy

The seed list is personal, so it never appears in this repo.
- It lives only in repo secrets, along with the optional skip list. The Action writes it to a temporary file and deletes it at the end.
- The script never prints seed names, only counts. Errors print their type, never a name or a URL.
- The lookup cache would show which artists were searched, so it stays in the private Actions cache and is never committed.
- The output lists new artists and a closeness score. It never says which seed led to which artist.

## Credits and terms

- **Last.fm** supplies similar artists, top tracks and tags through the [Last.fm API](https://www.last.fm/api). It is used for non-commercial purposes under Last.fm's API terms. Data from [Last.fm](https://www.last.fm).
- **ListenBrainz** supplies similar artists from [ListenBrainz](https://listenbrainz.org) (MetaBrainz Foundation).
- **MusicBrainz** supplies artist and song names and IDs from [MusicBrainz](https://musicbrainz.org) (CC0).

Where MusicBrainz has a match, the published name comes from MusicBrainz. Otherwise the name is spelled as Last.fm lists it, and `name_source` or `source` says which.

## Licence

The code is MIT (see `LICENSE`). Our own picks and scores in `data/` are offered under CC0. Names from MusicBrainz are CC0.
