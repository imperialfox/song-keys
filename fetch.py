#!/usr/bin/env python3
"""song-keys artist fan-out.

For each seed artist: up to 3 similar artists (layer 2), then for each of those
1 more (layer 3), then up to 5 best-known vocal songs per new artist. Similar
artists come from Last.fm and ListenBrainz together; published names and IDs
come from MusicBrainz where a match exists.

Privacy rules (see HANDOFF.md, D2 and D2a):
- The seed list is read from a file written from a repo secret. It is never
  committed, never printed, and never written to the output.
- Logs print counts only. Errors print their type, never a URL or a name.
- The lookup cache lives in .cache/ (git-ignored, kept in the private
  Actions cache), because cached lookups would show which artists were searched.

Standard library only. Run:  python3 fetch.py --seeds seed.txt --limit 10 --out data/neighbours-dry-run.json
"""
import argparse, json, os, re, sys, threading, time, traceback, unicodedata, urllib.parse, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

VERSION = "0.1.3"
UA = f"song-keys/{VERSION} (https://github.com/imperialfox/song-keys)"
LASTFM = "https://ws.audioscrobbler.com/2.0/"
LB_SIMILAR = "https://labs.api.listenbrainz.org/similar-artists/json"
# ListenBrainz names its similarity datasets; try these in order and record which one answered.
LB_ALGORITHMS = [
    "session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30",
    "session_based_days_9000_session_300_contribution_5_threshold_15_limit_50_skip_30",
]
MB = "https://musicbrainz.org/ws/2/"

LASTFM_FLOOR = 0.2          # D3: drop Last.fm matches under this
LAYER2_PER_SEED = 3
LAYER3_PER_ARTIST = 1
SONGS_PER_ARTIST = 5
INSTR_TITLE = re.compile(r"\b(instrumental|karaoke|backing track|type beat|beat tape|interlude|skit|remix|sped up|slowed|8d audio)\b", re.I)
LIVE_TITLE = re.compile(r"[\(\[-]\s*live\b", re.I)


# ---------- helpers ----------

def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


PHASE = {"name": "starting", "receipt": None}


def as_list(x):
    """Last.fm sends one item as a dict instead of a one-item list."""
    if isinstance(x, list):
        return x
    return [x] if isinstance(x, dict) else []


def log(msg):
    print(msg, flush=True)


def phase(name):
    PHASE["name"] = name
    log(f"Phase: {name}")


class Limiter:
    """At most one call per `gap` seconds for one service, shared across threads."""
    def __init__(self, gap):
        self.gap, self.lock, self.next = gap, threading.Lock(), 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            delay = self.next - now
            self.next = max(now, self.next) + self.gap
        if delay > 0:
            time.sleep(delay)


class Client:
    """HTTP with a per-service rate limit and a disk cache. Never logs URLs."""
    def __init__(self, cache_dir, lastfm_key, deadline):
        self.cache_dir, self.key, self.deadline = cache_dir, lastfm_key, deadline
        os.makedirs(cache_dir, exist_ok=True)
        self.limits = {"lastfm": Limiter(1.0), "lb": Limiter(1.0), "mb": Limiter(1.05)}
        self.cache, self.lock = {}, threading.Lock()
        self.stats = {"requests": 0, "cache_hits": 0, "errors": {}}
        for svc in self.limits:
            p = os.path.join(cache_dir, svc + ".json")
            self.cache[svc] = json.load(open(p)) if os.path.exists(p) else {}

    def save(self):
        with self.lock:
            for svc, data in self.cache.items():
                tmp = os.path.join(self.cache_dir, svc + ".json.tmp")
                json.dump(data, open(tmp, "w"))
                os.replace(tmp, os.path.join(self.cache_dir, svc + ".json"))

    def out_of_time(self):
        return time.monotonic() > self.deadline

    def _err(self, svc, kind):
        with self.lock:
            k = f"{svc}:{kind}"
            self.stats["errors"][k] = self.stats["errors"].get(k, 0) + 1

    def get(self, svc, url, params):
        ckey = url + "?" + urllib.parse.urlencode(sorted(params.items()))
        with self.lock:
            if ckey in self.cache[svc]:
                self.stats["cache_hits"] += 1
                return self.cache[svc][ckey]
        if self.out_of_time():
            return None
        full = dict(params)
        if svc == "lastfm":
            full.update(api_key=self.key, format="json")
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(full),
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        data = None
        for attempt in range(3):
            self.limits[svc].wait()
            with self.lock:
                self.stats["requests"] += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(5 * (attempt + 1))
                    continue
                self._err(svc, f"http{e.code}")
                data = {"_error": e.code}
                break
            except Exception as e:  # network, timeout, bad JSON: type only
                if attempt < 2:
                    time.sleep(3)
                    continue
                self._err(svc, type(e).__name__)
                return None  # not cached, so a re-run tries again
        if svc == "lastfm" and isinstance(data, dict) and "error" in data:
            self._err(svc, f"api{data.get('error')}")
            if data.get("error") in (11, 16, 29):  # temporary: don't cache
                return None
        with self.lock:
            self.cache[svc][ckey] = data
        return data


# ---------- sources ----------

class Sources:
    def __init__(self, client):
        self.c = client
        self.lb_algorithm = None
        self.lb_dead = False
        self.lb_lock = threading.Lock()

    # Last.fm
    def lfm_similar(self, name):
        d = self.c.get("lastfm", LASTFM, {"method": "artist.getsimilar", "artist": name, "autocorrect": "1", "limit": "30"})
        out = []
        try:
            for a in as_list(d["similarartists"]["artist"]):
                m = float(a.get("match") or 0)
                if m >= LASTFM_FLOOR:
                    out.append({"name": a["name"], "mbid": a.get("mbid") or None, "score": m})
        except (TypeError, KeyError):
            pass
        return out

    def lfm_top_tracks(self, name):
        d = self.c.get("lastfm", LASTFM, {"method": "artist.gettoptracks", "artist": name, "autocorrect": "1", "limit": "15"})
        try:
            return [{"title": t["name"], "mbid": t.get("mbid") or None} for t in as_list(d["toptracks"]["track"]) if t.get("name")]
        except (TypeError, KeyError):
            return []

    def lfm_is_instrumental(self, name):
        d = self.c.get("lastfm", LASTFM, {"method": "artist.gettoptags", "artist": name, "autocorrect": "1"})
        try:
            tags = as_list(d["toptags"]["tag"])
        except (TypeError, KeyError):
            return False
        return bool(tags) and "instrumental" in str(tags[0].get("name") or "").lower()

    # ListenBrainz (needs a MusicBrainz artist ID)
    def lb_similar(self, mbid):
        if not mbid or self.lb_dead:
            return []
        algs = [self.lb_algorithm] if self.lb_algorithm else LB_ALGORITHMS
        for alg in algs:
            d = self.c.get("lb", LB_SIMILAR, {"artist_mbids": mbid, "algorithm": alg})
            rows = d if isinstance(d, list) else (d.get("data") if isinstance(d, dict) else None)
            if isinstance(rows, list):
                with self.lb_lock:
                    self.lb_algorithm = self.lb_algorithm or alg
                top = max([float(r.get("score") or 0) for r in rows] or [1]) or 1
                return [{"name": r.get("name") or r.get("artist_name") or "", "mbid": r.get("artist_mbid"),
                         "score": float(r.get("score") or 0) / top} for r in rows if r.get("artist_mbid")]
        with self.lb_lock:
            if not self.lb_algorithm:
                self.lb_dead = True  # no dataset answered: carry on with Last.fm only
        return []

    # MusicBrainz
    @staticmethod
    def _q(s):
        return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", s)

    def mb_artist(self, name):
        d = self.c.get("mb", MB + "artist", {"query": f'artist:"{self._q(name)}"', "limit": "3", "fmt": "json"})
        # Only accept a MusicBrainz artist whose name matches. A top search score alone is not
        # enough: "SiR" scored 100 for "Sir Arthur Conan Doyle" and "Dave" for "Dave Matthews Band".
        try:
            for a in as_list(d["artists"]):
                if int(a.get("score", 0)) >= 90 and norm(a["name"]) == norm(name):
                    return {"mbid": a["id"], "name": a["name"]}
                for alias in as_list(a.get("aliases")):
                    if int(a.get("score", 0)) >= 90 and norm(alias.get("name", "")) == norm(name):
                        return {"mbid": a["id"], "name": a["name"]}
        except (TypeError, KeyError, IndexError):
            pass
        return None

    def mb_recording(self, title, artist_mbid, rec_mbid):
        if rec_mbid:
            d = self.c.get("mb", MB + "recording/" + rec_mbid, {"inc": "artist-credits", "fmt": "json"})
            if isinstance(d, dict) and d.get("title") and "_error" not in d:
                return d
        if not artist_mbid:
            return None
        d = self.c.get("mb", MB + "recording", {"query": f'recording:"{self._q(title)}" AND arid:{artist_mbid}', "limit": "1", "fmt": "json"})
        try:
            r = d["recordings"][0]
            if int(r.get("score", 0)) >= 90 and norm(r["title"]) == norm(title):
                return r
        except (TypeError, KeyError, IndexError):
            pass
        return None


# ---------- the fan-out ----------

def combine(lfm, lb):
    """Merge both lists; named by both ranks first, then by best score."""
    pool = {}
    for src, rows in (("lastfm", lfm), ("listenbrainz", lb)):
        for r in rows:
            k = norm(r["name"])
            if not k:
                continue
            e = pool.setdefault(k, {"name": r["name"], "mbid": None, "score": 0.0, "sources": set()})
            e["sources"].add(src)
            e["score"] = max(e["score"], r["score"])
            if r.get("mbid") and not e["mbid"]:
                e["mbid"] = r["mbid"]
            if src == "lastfm":
                e["name"] = r["name"]
    return sorted(pool.values(), key=lambda e: (-len(e["sources"]), -e["score"], e["name"].lower()))


def safely(src, where, fn, default):
    """Run one artist's lookup; on an unexpected error count it and move on."""
    try:
        return fn()
    except Exception as e:
        src.c._err("script", f"{where}:{type(e).__name__}")
        return default


def candidates(src, name, mbid):
    def go():
        return combine(src.lfm_similar(name), src.lb_similar(mbid))
    return safely(src, "similar", go, [])


def pick(src, cands, take, blocked, picked_now):
    chosen = []
    for c in cands:
        if len(chosen) == take or src.c.out_of_time():
            break
        k = norm(c["name"])
        if k in blocked or k in picked_now:
            continue
        if safely(src, "tags", lambda: src.lfm_is_instrumental(c["name"]), False):
            picked_now.add(k)  # don't re-check it
            src.dropped_instrumental += 1
            continue
        chosen.append(c)
        picked_now.add(k)
    return chosen


def songs_for(src, artist):
    tracks = src.lfm_top_tracks(artist["name"])
    out, seen = [], set()
    for t in tracks:
        if len(out) == SONGS_PER_ARTIST or src.c.out_of_time():
            break
        if INSTR_TITLE.search(t["title"]) or LIVE_TITLE.search(t["title"]):
            src.dropped_titles += 1
            continue
        k = norm(re.sub(r"\s*[\(\[].*?[\)\]]", "", t["title"]))
        if not k or k in seen:
            continue
        seen.add(k)
        rec = src.mb_recording(t["title"], artist.get("mbid"), t.get("mbid"))
        if rec:
            credit = "".join(a.get("name", "") + a.get("joinphrase", "") for a in rec.get("artist-credit", [])) or artist["name"]
            out.append({"title": rec["title"], "artist": credit, "mbid": rec.get("id"), "source": "musicbrainz"})
        else:
            out.append({"title": t["title"], "artist": artist["name"], "mbid": None, "source": "lastfm"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", required=True, help="file with one artist per line (from the SEED_ARTISTS secret)")
    ap.add_argument("--skip", default="", help="optional file of other artists to never pick (from the SKIP_ARTISTS secret)")
    ap.add_argument("--limit", type=int, default=0, help="use only the first N seeds (0 = all)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--receipt", required=True)
    ap.add_argument("--cache", default=".cache")
    ap.add_argument("--minutes", type=float, default=320, help="stop starting new lookups after this many minutes")
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    PHASE["receipt"] = a.receipt

    key = os.environ.get("LASTFM_API_KEY", "").strip()
    if not key:
        log("LASTFM_API_KEY is not set. Add it as a repo secret.")
        sys.exit(2)
    seeds = [l.strip() for l in open(a.seeds, encoding="utf-8") if l.strip()]
    if a.limit:
        seeds = seeds[:a.limit]
    if not seeds:
        log("The seed list is empty. Check the SEED_ARTISTS secret.")
        sys.exit(2)

    started = time.monotonic()
    client = Client(a.cache, key, started + a.minutes * 60)
    src = Sources(client)
    src.dropped_instrumental = 0
    src.dropped_titles = 0
    all_seeds = [l.strip() for l in open(a.seeds, encoding="utf-8") if l.strip()]
    skip = [l.strip() for l in open(a.skip, encoding="utf-8") if l.strip()] if a.skip and os.path.exists(a.skip) else []
    # D3: never pick an artist Ivan already has. All seeds are blocked even in a dry run.
    blocked = {norm(s) for s in all_seeds + skip}
    log(f"Seeds: {len(seeds)}, artists to skip: {len(blocked)}")
    phase("layer 2")

    def seed_job(name):
        m = safely(src, "seed-id", lambda: src.mb_artist(name), None)
        return candidates(src, name, m["mbid"] if m else None)

    # Layer 2
    with ThreadPoolExecutor(a.workers) as ex:
        seed_cands = list(ex.map(seed_job, seeds))
    layer2, picked = {}, set()
    for cands in seed_cands:
        for c in pick(src, cands, LAYER2_PER_SEED, blocked, set()):
            e = layer2.setdefault(norm(c["name"]), {**c, "sources": set(), "closeness": 0.0, "layer": 2})
            e["sources"] |= c["sources"]
            e["closeness"] += 1.0
            if c.get("mbid") and not e.get("mbid"):
                e["mbid"] = c["mbid"]
    picked |= set(layer2)
    log(f"Layer 2 artists: {len(layer2)}")
    client.save()

    # Layer 3
    phase("layer 3")
    l2_list = list(layer2.values())
    with ThreadPoolExecutor(a.workers) as ex:
        l2_cands = list(ex.map(lambda e: candidates(src, e["name"], e.get("mbid")), l2_list))
    layer3, both3 = {}, 0
    for cands in l2_cands:
        for c in pick(src, cands, LAYER3_PER_ARTIST, blocked | picked | set(layer3), set()):
            e = layer3.setdefault(norm(c["name"]), {**c, "sources": set(), "closeness": 0.0, "layer": 3})
            e["sources"] |= c["sources"]
            e["closeness"] += 0.5
            if len(c["sources"]) == 2:
                both3 += 1
    log(f"Layer 3 artists: {len(layer3)}")
    client.save()

    # MusicBrainz name and ID for every new artist, then songs
    phase("names and songs")
    artists = list(layer2.values()) + list(layer3.values())

    def finish(e):
        m = safely(src, "artist-id", lambda: src.mb_artist(e["name"]), None)
        if m:
            e["mbid"], e["mb_name"] = m["mbid"], m["name"]
        e["songs"] = safely(src, "songs", lambda: songs_for(src, e), [])
        return e
    with ThreadPoolExecutor(a.workers) as ex:
        artists = list(ex.map(finish, artists))
    client.save()

    phase("writing output")
    out_artists = []
    for e in sorted(artists, key=lambda e: (-e["closeness"], e["layer"], e["name"].lower())):
        if not e["songs"]:
            continue
        out_artists.append({
            "name": e.get("mb_name") or e["name"],
            "mbid": e.get("mbid"),
            "name_source": "musicbrainz" if e.get("mb_name") else "lastfm",
            "layer": e["layer"],
            "closeness": round(e["closeness"], 2),
            "found_by": sorted(e["sources"]),
            "songs": e["songs"],
        })
    partial = client.out_of_time()
    songs = [s for x in out_artists for s in x["songs"]]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    json.dump({"version": VERSION, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "partial": partial, "artists": out_artists}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    mins = (time.monotonic() - started) / 60
    mb_artists = sum(1 for x in out_artists if x["name_source"] == "musicbrainz")
    mb_songs = sum(1 for s in songs if s["source"] == "musicbrainz")
    lines = [
        f"# Build receipt · {os.path.basename(a.out)}",
        "",
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}, song-keys {VERSION}",
        f"- Status: {'PARTIAL (ran out of time; run again to continue from the cache)' if partial else 'complete'}",
        f"- Seed artists used: {len(seeds)}; artists skipped as already known: {len(blocked)} (names kept private)",
        f"- New artists: {len(out_artists)} (layer 2: {sum(1 for x in out_artists if x['layer']==2)}, layer 3: {sum(1 for x in out_artists if x['layer']==3)})",
        f"- Songs: {len(songs)}",
        f"- Named from MusicBrainz: {mb_artists} of {len(out_artists)} artists, {mb_songs} of {len(songs)} songs",
        f"- Layer 3 picks named by both sources: {both3} of {len(layer3)}" + (f" ({100*both3//len(layer3)}%)" if layer3 else ""),
        f"- ListenBrainz dataset: {src.lb_algorithm or 'none answered (Last.fm only)'}",
        f"- Dropped: {src.dropped_instrumental} instrumental artists, {src.dropped_titles} titles (instrumental, remix, live and similar)",
        f"- Requests: {client.stats['requests']}, from cache: {client.stats['cache_hits']}",
        f"- Errors: {json.dumps(client.stats['errors']) if client.stats['errors'] else 'none'}",
        f"- Run time: {mins:.0f} min",
        "",
        "Sources: Last.fm and ListenBrainz (similar artists, top tracks), MusicBrainz (names and IDs, CC0).",
    ]
    open(a.receipt, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    log("\n".join(lines[2:-2]))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:  # never print values that could hold a seed name
        where = [f"{os.path.basename(f.filename)} line {f.lineno} in {f.name}" for f in traceback.extract_tb(e.__traceback__)]
        msg = f"Stopped with an error: {type(e).__name__} during '{PHASE['name']}'"
        print(msg, flush=True)
        for w in where[-4:]:
            print("  at " + w, flush=True)
        if PHASE["receipt"]:
            os.makedirs(os.path.dirname(PHASE["receipt"]) or ".", exist_ok=True)
            open(PHASE["receipt"], "w", encoding="utf-8").write(
                f"# Build receipt\n\n- Status: FAILED\n- {msg}\n" + "".join(f"- at {w}\n" for w in where[-4:]))
        sys.exit(1)
