# song-keys · artist fan-out · build handoff

**Render:** 4 Nov 2026, 08:22. Ivan said "Repo made, render". The scope is the whole fan-out plan with every default accepted (D1 to D6 and D2a below).
**Build:** 4 Nov 2026, 10:34. Ivan said "build here". **State: Building.** The code is pushed. The dry run and full run come next, run by Ivan from the Actions tab.

There's no Q number, because this repo belongs to no app.

## Goal

Start from Ivan's top 300 artists. Find 3 similar artists for each, then 1 more for each of those, and take 5 best-known songs per new artist. The output is artist and title only. That's about 1,200 to 1,500 new artists and 6 to 7k songs.

## Agreed

- **Sources.** Last.fm and ListenBrainz together. Artists named by both rank higher, and Last.fm matches under 0.2 are dropped (D3).
- **Names.** Published names and IDs come from MusicBrainz where it has a match (D4).
- **Running.** A GitHub Action, run on demand, with one request a second per service (D6).
- **Secrets.** The seed list (300 names) is the `SEED_ARTISTS` repo secret, and the Last.fm key is `LASTFM_API_KEY`. Ivan adds both himself (D2).
- **Privacy.** Nothing public points back at the seed. Logs show counts only, the lookup cache stays in the private Actions cache, and the output never says which seed led to which artist (D2a).
- **Instrumentals.** These are dropped by title words and by the artist's top Last.fm tag (D5).
- **Repo files.** MIT licence, README with credits, changelog, this handoff (D1).

## Out of scope

- Keys for the new songs.
- The local merge with Ivan's personal song file.
- The app's suggested-key screen.
- Any charts layer.

## Touches

This repo only: `fetch.py`, `tests/test_fetch.py`, `.github/workflows/build.yml`, `data/` (written by the Action), `README.md`, `CHANGELOG.md`, `HANDOFF.md`, `LICENSE`, `.gitignore`.

## Done when

- `data/neighbours.json` holds each new artist with its closeness score, sources, MusicBrainz ID where found, and up to 5 songs.
- No seed names appear in the repo, its history or its Action logs.
- `data/build-receipt.md` is written by the run.
- A re-run only fetches what changed.

## Checks

1. Run the dry run on 10 seeds, and Ivan looks over the neighbours before the full run.
2. Spot-check artists he knows, plus 10 at random.
3. At least a third of the layer-3 picks should be named by both sources. If fewer are, lower the floor or report it.
4. Search the repo, its history and one Action log for five seed names. None should turn up.
5. Check the credit lines against each service's terms.

## Notes from the build

- Seeds are only excluded as candidates against the 300 seed names, not against all 3,242 of Ivan's artists. So some neighbours may be artists he already has. The local merge removes those duplicates. Excluding all of them would have meant putting his full artist list into GitHub.
- The first dry run (run 1, 4 Nov 11:10) failed after 10 minutes with nothing saved. The likely cause was Last.fm's single-item replies. Fixed in 0.1.1, which also makes every run record its own result in `data/`.
- Claude can push to this repo but can't read its Actions settings, runs or logs through its proxy. So Ivan adds the secrets and starts the runs, and Claude reads the results from the committed `data/` files.

## Debrief

(after the full run)
