import json
import os
import tempfile
import unittest

from harness.detect import detect_project


def write(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


class DetectTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_multi_service_with_compose(self):
        write(self.root, "docker-compose.yml", "services: {}\n")
        write(self.root, "api/pyproject.toml", "[tool.pytest]\n")
        write(self.root, "api/tests/test_x.py", "")
        write(self.root, "web/package.json", json.dumps({"name": "web", "scripts": {"build": "vite build"}}))
        r = detect_project(self.root)
        self.assertTrue(r["hasDockerCompose"])
        self.assertEqual(r["dockerComposeFile"], "docker-compose.yml")
        by = {c["name"]: c for c in r["components"]}
        self.assertEqual(by["api"]["type"], "python")
        self.assertEqual(by["api"]["commands"]["test"], "python3 -m pytest")
        self.assertEqual(by["web"]["commands"]["build"], "npm run build")

    def test_compose_yaml_candidate(self):
        write(self.root, "compose.yaml", "services: {}\n")
        self.assertEqual(detect_project(self.root)["dockerComposeFile"], "compose.yaml")
        self.assertFalse(detect_project(tempfile.gettempdir() + "/nonexistent-xyz")["hasDockerCompose"])

    def test_package_managers_and_monorepo(self):
        write(self.root, "pnpm-lock.yaml", "lockfileVersion: 9.0\n")
        write(self.root, "apps/web/package.json",
              json.dumps({"name": "@acme/web", "scripts": {"build": "vite build", "lint": "eslint ."}}))
        write(self.root, "packages/shared/package.json",
              json.dumps({"name": "@acme/shared", "packageManager": "yarn@4.1.0",
                          "scripts": {"test": "node --test", "typecheck": "tsc --noEmit"}}))
        r = detect_project(self.root)
        self.assertEqual(len(r["components"]), 2)
        by = {c["relPath"]: c for c in r["components"]}
        web, shared = by["apps/web"], by["packages/shared"]
        self.assertEqual(web["packageManager"], "pnpm")
        self.assertEqual(web["commands"]["build"], "pnpm run build")
        self.assertEqual(web["commands"]["lint"], "pnpm run lint")
        self.assertEqual(shared["packageManager"], "yarn")
        self.assertEqual(shared["commands"]["test"], "yarn test")
        self.assertEqual(shared["commands"]["typecheck"], "yarn run typecheck")

    def test_libs_modules_and_polyglot_root(self):
        write(self.root, "go.mod", "module x\n")
        write(self.root, "package.json", json.dumps({"name": "root", "scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}))
        write(self.root, "libs/math/package.json", json.dumps({"name": "@acme/math", "scripts": {"test": "node t.js"}}))
        write(self.root, "modules/core/Cargo.toml", "")
        write(self.root, "node_modules/x/package.json", "{}")
        r = detect_project(self.root)
        types = sorted((c["relPath"], c["type"]) for c in r["components"])
        self.assertEqual(types, [(".", "go"), (".", "node"), ("libs/math", "node"), ("modules/core", "rust")])
        root_node = next(c for c in r["components"] if c["type"] == "node" and c["relPath"] == ".")
        self.assertNotIn("test", root_node["commands"])

    def test_unittest_fallback_and_skip_dirs(self):
        write(self.root, "requirements.txt", "requests\n")
        write(self.root, "tests/test_a.py", "")
        write(self.root, "examples/demo/package.json", "{}")
        r = detect_project(self.root)
        self.assertEqual(len(r["components"]), 1)
        self.assertIn("unittest", r["components"][0]["commands"]["test"])


if __name__ == "__main__":
    unittest.main()
