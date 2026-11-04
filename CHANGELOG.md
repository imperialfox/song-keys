# Changelog

## 0.1.0 · 4 Nov 2026

- First version. This is the artist fan-out, with 3 similar artists per seed, then 1 more each, and 5 songs per new artist.
- Similar artists come from Last.fm and ListenBrainz. Artists named by both rank first, and Last.fm matches under 0.2 are dropped.
- Names and IDs come from MusicBrainz where it has a match.
- Instrumental artists are dropped by their top tag. Instrumental, remix, live, slowed and sped-up titles are dropped too.
- Each service gets one request a second. Lookups are cached privately, and a run that runs out of time can be run again to continue.
- Logs print counts only, and nothing public says which seed led to which artist.
- The on-demand GitHub Action has a dry (10 seeds) and a full mode. Each run writes a build receipt.
- There's an offline test with made-up artists.
