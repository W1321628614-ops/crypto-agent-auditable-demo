"""Exclusive journal, request integrity, reproducible restart. Not an adversarial sandbox."""
import copy,os
from contextlib import contextmanager
from .provenance import read,digest,write_new,canonical_json_sha256
class Journal:
    @contextmanager
    def lock(self):
        target = self.path / "run.lock"
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        try:
            self._reload()
            yield
        finally:
            target.unlink()  # Only the lock this invocation created; no old artifacts deleted.


    def _reload(self):
        self.state = dict(index=self.config["warmup"] - 1, cash=self.config["initial_cash"],
                          position=None, order=None, last_decision=None, request_id=None,
                          close_position=False, sequence=0, last_hash=None, paused=False, fired=[], wait_reason=None)
        self.events = []
        for n, p in enumerate(sorted((self.path / "journal").glob("*.json"))):
            if p.name != f"{n:06d}.json":
                raise ValueError("journal gap")
            event = read(p)
            recorded = event.pop("record_sha256")
            if canonical_json_sha256(event) != recorded:
                raise ValueError("journal content hash mismatch")
            event["record_sha256"] = recorded
            if event["manifest_sha256"] != digest(self.path / "manifest.json"):
                raise ValueError("frozen run configuration changed")
            if event["previous_sha256"] != self.state["last_hash"]:
                raise ValueError("journal chain mismatch")
            self.state = event["state"]
            self.state["last_hash"] = digest(p)
            self.events.append(event)
        expected = {e["data"]["request_id"] for e in self.events if e["kind"] == "request"}
        actual = {p.stem for p in (self.path / "requests").glob("*.json")}
        if expected != actual:
            raise ValueError("orphan/missing request; interrupted persistence, stop for inspection")
        for e in self.events:
            if e["kind"] == "request":
                request_path = self.path / "requests" / (e["data"]["request_id"] + ".json")
                if digest(request_path) != e["data"]["packet_file_sha256"]:
                    raise ValueError("request hash mismatch")
                chart = read(request_path).get("chart")
                if chart and digest(self.path / chart["file"]) != chart["sha256"]:
                    raise ValueError("causal chart hash mismatch")


    def _commit(self, kind, data):
        n = len(self.events)
        self.state["sequence"] = n + 1
        event = dict(kind=kind, data=data, previous_sha256=self.state["last_hash"],
                     manifest_sha256=digest(self.path / "manifest.json"),
                     state=copy.deepcopy(self.state))
        event["record_sha256"] = canonical_json_sha256(event)
        p = self.path / "journal" / f"{n:06d}.json"
        write_new(p, event)
        self.state["last_hash"] = digest(p)
        self.events.append(event)
