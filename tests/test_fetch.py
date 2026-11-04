"""Offline test for fetch.py with made-up artists. No network.

Run:  python3 -I tests/test_fetch.py
Checks the 3-then-1 picking, seed exclusion, the instrumental drop, MusicBrainz
naming, the output shape, and that no seed name reaches the logs or the output
(except as a featured credit on someone else's song, which is public data).
"""
import io, json, os, subprocess, sys, tempfile, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FAKE = textwrap.dedent(r'''
import json, sys, urllib.parse, urllib.request, io
SIM = {  # Last.fm similar lists
  "Seedone":  [("Alpha", .9), ("Seedtwo", .8), ("Beta", .7), ("Gamma", .5), ("Delta", .3), ("Weak", .1)],
  "Seedtwo":  [("Alpha", .9), ("Seedthree", .88), ("Mine", .87), ("Pianoman", .85), ("Epsilon", .6), ("Zeta", .4)],
  "Alpha":    [("Beta", .9), ("Eta", .7)],
  "Beta":     [("Theta", .8)],
  "Gamma":    [("Iota", .8)],
  "Epsilon":  [("Eta", .9), ("Kappa", .6)],
  "Zeta":     [("Lambda", .5)],
}
LB = {"mb-seedone": [("Gamma", "mb-gamma", 50), ("Alpha", "mb-alpha", 100)]}
INSTR = {"Pianoman"}
def resp(url):
    u = urllib.parse.urlparse(url); q = dict(urllib.parse.parse_qsl(u.query))
    if "audioscrobbler" in u.netloc:
        m, a = q["method"], q.get("artist", "")
        if m == "artist.getsimilar" and a == "Gamma":  # one similar artist comes as a dict
            return {"similarartists": {"artist": {"name": "Iota", "mbid": "", "match": "0.8"}}}
        if m == "artist.getsimilar":
            return {"similarartists": {"artist": [{"name": n, "mbid": "", "match": str(s)} for n, s in SIM.get(a, [])]}}
        if m == "artist.gettoptags":
            tag = {"name": "instrumental" if a in INSTR else "soul"}
            return {"toptags": {"tag": tag if a in ("Beta", "Pianoman") else [tag]}}  # one tag comes as a dict
        if m == "artist.gettoptracks":
            names = [f"{a} Song 1 (Remix)", f"{a} Instrumental", f"{a} Song 2 - Live"] + [f"{a} Song {i}" for i in range(1, 7)]
            return {"toptracks": {"track": [{"name": n, "mbid": "rec-" + n if n.endswith("1") else ""} for n in names]}}
    if "listenbrainz" in u.netloc:
        return [{"artist_mbid": m, "name": n, "score": s} for n, m, s in LB.get(q["artist_mbids"], [])]
    if "musicbrainz" in u.netloc:
        if u.path.endswith("/artist"):
            name = q["query"].split('"')[1].replace("\\", "")
            if name == "Theta":  # a top-scoring but wrong artist must be refused
                return {"artists": [{"id": "mb-wrong", "name": "Theta Orchestra", "score": 100}]}
            return {"artists": [{"id": "mb-" + name.lower(), "name": name.upper() if name == "Alpha" else name, "score": 100}]}
        if "/recording/" in u.path:
            return {"id": u.path.rsplit("/", 1)[1], "title": "MB " + u.path.rsplit("/", 1)[1][4:], "artist-credit": [{"name": "Credit", "joinphrase": ""}]}
        return {"recordings": []}
    raise RuntimeError("unexpected host")
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
def fake_urlopen(req, timeout=0):
    return R(json.dumps(resp(req.full_url)).encode())
urllib.request.urlopen = fake_urlopen
sys.argv = ["fetch.py"] + sys.argv[1:]
sys.path.insert(0, %r)
import fetch
fetch.Limiter.wait = lambda self: None
fetch.main()
''' % ROOT)


def main():
    with tempfile.TemporaryDirectory() as d:
        seeds = os.path.join(d, "seed.txt")
        open(seeds, "w").write("Seedone\nSeedtwo\nSeedthree\n")
        skip = os.path.join(d, "skip.txt")
        open(skip, "w").write("Mine\n")
        runner = os.path.join(d, "run.py")
        open(runner, "w").write(FAKE)
        out, rec = os.path.join(d, "out.json"), os.path.join(d, "receipt.md")
        p = subprocess.run([sys.executable, "-I", runner, "--seeds", seeds, "--out", out, "--receipt", rec,
                            "--cache", os.path.join(d, "cache"), "--workers", "2", "--skip", skip, "--limit", "2"],
                           env={**os.environ, "LASTFM_API_KEY": "test"}, capture_output=True, text=True)
        assert p.returncode == 0, p.stdout + p.stderr
        logs = p.stdout + p.stderr
        data = json.load(open(out))
        receipt = open(rec).read()
        names = [a["name"] for a in data["artists"]]
        by = {a["name"]: a for a in data["artists"]}

        # Seeds never appear as artists, in logs or in the receipt
        for s in ("Seedone", "Seedtwo", "Seedthree", "Mine"):
            assert s not in names and s not in logs and s not in receipt, s
            assert s not in json.dumps([a["name"] for a in data["artists"]])
        # Layer 2: Seedone -> Alpha (both), Gamma (both), Beta; Seedtwo -> Alpha, Epsilon, Zeta (Pianoman instrumental)
        l2 = {a["name"] for a in data["artists"] if a["layer"] == 2}
        assert l2 == {"ALPHA", "Gamma", "Beta", "Epsilon", "Zeta"}, l2
        assert by["ALPHA"]["closeness"] == 2.0 and by["ALPHA"]["name_source"] == "musicbrainz"
        assert by["Gamma"]["found_by"] == ["lastfm", "listenbrainz"]
        assert "Pianoman" not in names and "Weak" not in names and "Delta" not in names
        # Layer 3: one new each, never a seed or a layer-2 artist
        l3 = {a["name"] for a in data["artists"] if a["layer"] == 3}
        assert l3 == {"Eta", "Theta", "Iota", "Kappa", "Lambda"}, l3
        # Songs: 5 each, no remix/instrumental/live, MusicBrainz title used when a recording ID exists
        for a in data["artists"]:
            assert len(a["songs"]) == 5, (a["name"], len(a["songs"]))
            for s in a["songs"]:
                assert not any(w in s["title"] for w in ("Remix", "Instrumental", "Live")), s
        assert any(s["source"] == "musicbrainz" for s in by["Beta"]["songs"])
        assert by["Theta"]["name_source"] == "lastfm" and by["Theta"]["mbid"] is None, by["Theta"]
        assert "instrumental artists" in receipt and "complete" in receipt
        assert "30 titles" in receipt, receipt
        print("OK:", len(data["artists"]), "artists,", sum(len(a["songs"]) for a in data["artists"]), "songs")
        print(receipt)


if __name__ == "__main__":
    main()
