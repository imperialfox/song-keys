# Changelog

## 0.1.2 · 4 Nov 2026

- A MusicBrainz artist is now only accepted when its name or an alias matches. The dry run had named SiR as "Sir Arthur Conan Doyle", Saba as "Joseph Saba" and Dave as "Dave Matthews Band", because a top search score was trusted on its own.

## 0.1.1 · 4 Nov 2026

- Fixes the first dry run, which stopped after 10 minutes without saving anything. Last.fm sends a single item instead of a one-item list, for example an artist with one tag, and the tag check didn't expect that.
- One artist's bad reply is now counted as an error and skipped, so it can't stop the whole run.
- A failed run now writes a receipt saying which phase failed and on which code line. It never includes the error's text, which could hold an artist name.
- Each run attempt saves its cache under its own name, so a re-run no longer fails to save.
- The result commit pulls the latest code first, so it isn't rejected when the repo has moved on since the run started.
- Every run commits `data/last-run-dry.md` or `data/last-run-full.md`, which says whether each step passed. Results can then be checked without opening the Actions logs.

## 0.1.0 · 4 Nov 2026

- First version. This is the artist fan-out, with 3 similar artists per seed, then 1 more each, and 5 songs per new artist.
- Similar artists come from Last.fm and ListenBrainz. Artists named by both rank first, and Last.fm matches under 0.2 are dropped.
- Names and IDs come from MusicBrainz where it has a match.
- Instrumental artists are dropped by their top tag. Instrumental, remix, live, slowed and sped-up titles are dropped too.
- Each service gets one request a second. Lookups are cached privately, and a run that runs out of time can be run again to continue.
- Logs print counts only, and nothing public says which seed led to which artist.
- The on-demand GitHub Action has a dry (10 seeds) and a full mode. Each run writes a build receipt.
- There's an offline test with made-up artists.
