#!/usr/bin/env python3
"""Live spot-checks of audit findings against the running stacks (unique entity names)."""
import json, urllib.request, uuid

def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

def edges(graph, subj, pred):
    out = []
    nodes = {n.get("id"): n for n in graph.get("nodes", [])}
    for e in graph.get("edges", []):
        s = e.get("source") or e.get("subject")
        name = nodes.get(s, {}).get("name", s) if isinstance(nodes.get(s), dict) else s
        if (subj in json.dumps(e) or subj == name) and e.get("predicate") == pred:
            out.append({k: e.get(k) for k in ("object", "target", "status", "valid_from", "valid_until", "ghost")})
    return out

# ---- Antigravity (high): retracted interval ignored -> two active values -------------
AG = "http://localhost:8000"
s = "AuditAG" + uuid.uuid4().hex[:6]
print("AG ep1", call(AG, "POST", "/api/episodes", {"title": "a1", "raw_content": f"{s} | STATUS | up",
                                                 "reference_time": "2026-01-01T00:00:00Z"})[0])
st, facts = call(AG, "GET", f"/api/facts?entity={s}&status=all")
fid = [f for f in facts if f.get("object") == "up"][0]["id"] if isinstance(facts, list) else None
print("AG retract", call(AG, "POST", f"/api/facts/{fid}/retract", {"retracted_at": "2026-03-01T00:00:00Z"})[0])
print("AG ep2", call(AG, "POST", "/api/episodes", {"title": "a2", "raw_content": f"{s} | STATUS | down",
                                                 "reference_time": "2026-02-01T00:00:00Z"})[0])
st, g = call(AG, "GET", "/api/graph?as_of=2026-02-15T00:00:00Z")
print("AG graph @Feb15 STATUS edges for", s, "->", edges(g, s, "STATUS"))

# ---- Hermes (medium): backdated assertion after retraction leaves no active fact -----
HF = "http://localhost:18000"
s = "AuditHF" + uuid.uuid4().hex[:6]
print("HF ep1", call(HF, "POST", "/api/episodes", {"content": f"{s} | STATUS | x", "occurred_at": "2024-01-01T00:00:00Z"})[0])
print("HF ep2", call(HF, "POST", "/api/episodes", {"content": f"{s} | STATUS | y", "occurred_at": "2024-03-01T00:00:00Z"})[0])
st, facts = call(HF, "GET", f"/api/facts?subject={s}")
fy = [f for f in facts if f.get("object") == "y"][0]["id"]
print("HF retract y", call(HF, "POST", f"/api/facts/{fy}/retract", {})[0])
print("HF ep3 backdated z", call(HF, "POST", "/api/episodes", {"content": f"{s} | STATUS | z", "occurred_at": "2024-02-01T00:00:00Z"})[1])
st, facts = call(HF, "GET", f"/api/facts?subject={s}")
for f in facts:
    print("   fact", f["object"], f["status"], f["valid_from"], f.get("valid_until"), "succ=", f.get("superseded_by_id"))
st, g = call(HF, "GET", "/api/graph?as_of=2024-04-01T00:00:00Z")
print("HF graph @Apr STATUS edges for", s, "->", edges(g, s, "STATUS"))
