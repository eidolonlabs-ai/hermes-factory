import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory import compose as C

DOCKER_OK, DOCKER_WHY = C.docker_available()
CLEAN = {"name": "p-12345678", "services": {"test": {"image": "busybox", "volumes": [
    {"type": "bind", "source": "/wt/src", "target": "/src"}]}}}
WT = "/wt"


def v(cfg, **kw):
    return C.policy_violations(cfg, kw.pop("wt", WT), kw.pop("prot", []), **kw)


def svc(**kw):
    return {"name": "p-1", "services": {"a": {"image": "busybox", **kw}}}


class PolicyTests(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(v(CLEAN, wt="/wt"), [])

    def test_container_name(self):
        self.assertTrue(v(svc(container_name="x")))

    def test_privileged(self):
        self.assertTrue(v(svc(privileged=True)))

    def test_host_modes(self):
        self.assertTrue(v(svc(network_mode="host")))
        self.assertTrue(v(svc(pid="host")))
        self.assertTrue(v(svc(ipc="host")))

    def test_caps(self):
        self.assertTrue(v(svc(cap_add=["ALL"])))
        self.assertTrue(v(svc(cap_add=["SYS_ADMIN"])))
        self.assertEqual(v(svc(cap_add=["NET_BIND_SERVICE"])), [])

    def test_devices(self):
        self.assertTrue(v(svc(devices=["/dev/fuse:/dev/fuse"])))

    def test_docker_socket(self):
        for p in ("/var/run/docker.sock", "/run/docker.sock", os.path.expanduser("~/.docker")):
            self.assertTrue(v(svc(volumes=[{"type": "bind", "source": p, "target": "/x"}])), p)

    def test_bind_outside(self):
        self.assertTrue(v(svc(volumes=[{"type": "bind", "source": "/etc", "target": "/x"}])))

    def test_bind_symlink_escape(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d, "wt"); wt.mkdir()
            out = Path(d, "out"); out.mkdir()
            (wt / "link").symlink_to(out)
            cfg = svc(volumes=[{"type": "bind", "source": str(wt / "link"), "target": "/x"}])
            self.assertTrue(v(cfg, wt=str(wt)))

    def test_named_volume_ok(self):
        self.assertEqual(v(svc(volumes=[{"type": "volume", "source": "data", "target": "/d"}])), [])

    def test_ports(self):
        cfg = svc(ports=[{"mode": "ingress", "target": 80, "published": "8080"}])
        self.assertTrue(v(cfg))
        self.assertEqual(v(cfg, allow_published_ports=True), [])

    def test_external(self):
        self.assertTrue(v({"services": {}, "networks": {"n": {"external": True}}}))
        self.assertTrue(v({"services": {}, "volumes": {"d": {"external": True}}}))

    def test_protected(self):
        self.assertTrue(v({"name": "chronograph", "services": {}}, prot=["chronograph"]))

    def test_driver_opts_env_file_secrets_configs_volumes_from(self):
        self.assertTrue(v(svc(volumes_from=["other"])))
        self.assertTrue(v(svc(env_file="/etc/passwd")))
        self.assertTrue(v({"name": "p-1", "services": {},
                           "volumes": {"v": {"driver_opts": {"type": "none", "o": "bind", "device": "/var/run/docker.sock"}}}}))
        self.assertTrue(v({"name": "p-1", "services": {}, "secrets": {"s": {"file": "/etc/shadow"}}}))
        self.assertTrue(v({"name": "p-1", "services": {}, "configs": {"c": {"external": True}}}))
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d, "wt"); wt.mkdir()
            (wt / "env.local").write_text("A=1\n")
            self.assertEqual(v(svc(env_file="env.local"), wt=str(wt)), [])

    def test_peer_factory_project_exemption(self):
        self.assertTrue(C.is_peer_factory_project("factory-20261118xyz"))
        self.assertTrue(C.is_peer_factory_project("factory-agy-1234abcd"))
        self.assertTrue(C.is_peer_factory_project("chronograph-a1b2c3d4"))
        self.assertTrue(C.is_peer_factory_project("chronograph-preview"))
        self.assertFalse(C.is_peer_factory_project("chronograph"))
        self.assertFalse(C.is_peer_factory_project("my-postgres"))
        self.assertFalse(C.is_peer_factory_project(""))


class NameTests(unittest.TestCase):
    def test_sanitize(self):
        n = C.project_name("My App!_X", "AB-CD_ef0123456789")
        self.assertTrue(n.startswith("my-app-_x-") and len(n) == len("my-app-_x-") + 8, n)
        self.assertNotEqual(C.project_name("p", "20261116-1-build-M1-aaaa"),
                            C.project_name("p", "20261116-2-build-M1-bbbb"))
        import re
        self.assertRegex(n, r"^[a-z0-9][a-z0-9_-]*$")
        self.assertRegex(C.project_name("__", "!!"), r"^[a-z0-9][a-z0-9_-]*$")
        self.assertRegex(C.project_name("-x", "1"), r"^[a-z0-9]")


YAML = """services:
  web:
    image: busybox
    command: ["sleep", "300"]
    healthcheck:
      test: ["CMD", "true"]
      interval: 1s
      retries: 3
"""


@unittest.skipUnless(DOCKER_OK, DOCKER_WHY)
class DockerTests(unittest.TestCase):
    def ps(self, name):
        r = subprocess.run(["docker", "ps", "-a", "-q", "--filter",
                            f"label=com.docker.compose.project={name}"], capture_output=True, text=True)
        return r.stdout.split()

    def test_session(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "compose.yaml").write_text(YAML)
            name = C.project_name("hctest", "sess0001zz")
            art = Path(d, "art")
            with C.ComposeSession(d, "compose.yaml", name, {}, str(art), timeout_s=90) as s:
                cfg = C.load_config(d, "compose.yaml", name, s.env)
                self.assertEqual(C.policy_violations(cfg, d, []), [])
                self.assertEqual(s.up().returncode, 0)
                self.assertTrue(self.ps(name))
                r = s.run("web", ["echo", "hi"], 60)
                self.assertEqual(r.returncode, 0)
                self.assertIn("hi", Path(r.log).read_text())
            self.assertEqual(self.ps(name), [])
            self.assertEqual(s.foreign_changed, [])
            self.assertTrue(s.teardown_ok)
            self.assertTrue(C.teardown_check(s).ok)
            self.assertTrue((art / "compose-logs.log").exists())
            self.assertTrue(list(art.glob("compose-*-up.log")))

    def test_outside_bind_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d, "wt"); wt.mkdir()
            Path(d, "outside").mkdir()
            Path(wt, "compose.yaml").write_text(
                "services:\n  web:\n    image: busybox\n    volumes:\n      - ../outside:/o\n")
            name = C.project_name("hctest", "bind0002")
            cfg = C.load_config(str(wt), "compose.yaml", name, {})
            viol = C.policy_violations(cfg, str(wt), [])
            self.assertTrue(any("outside worktree" in x for x in viol), viol)
            chk = C.policy_check(str(wt), "compose.yaml", name, [])
            self.assertEqual(chk.status, "FAIL")
            self.assertEqual(self.ps(name), [])


if __name__ == "__main__":
    unittest.main()
