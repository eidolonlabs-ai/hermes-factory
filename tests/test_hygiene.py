import os
import subprocess
import tempfile
import unittest

from harness.hygiene import check_hygiene


def sh(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def write(root, rel, text=""):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text)


class HygieneTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._td.name)
        sh(self.root, "init", "-q")
        sh(self.root, "config", "user.name", "t")
        sh(self.root, "config", "user.email", "t@example.com")

    def tearDown(self):
        self._td.cleanup()

    def test_clean_repo_passes(self):
        write(self.root, "a.txt", "hi")
        sh(self.root, "add", "a.txt")
        c = check_hygiene(self.root)
        self.assertEqual((c.id, c.status), ("hygiene", "PASS"))

    def test_env_without_ignore_fails(self):
        write(self.root, ".env", "X=1\n")
        c = check_hygiene(self.root)
        self.assertEqual(c.status, "FAIL")
        self.assertTrue(any(".env" in d for d in c.details))

    def test_env_with_gitignore_passes(self):
        write(self.root, ".env", "X=1\n")
        write(self.root, ".gitignore", ".env\n")
        self.assertEqual(check_hygiene(self.root).status, "PASS")

    def test_env_ignored_via_info_exclude_passes(self):
        write(self.root, ".env", "X=1\n")
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a") as fh:
            fh.write(".env\n")
        self.assertEqual(check_hygiene(self.root).status, "PASS")

    def test_tracked_env_fails_even_if_ignored(self):
        write(self.root, ".env", "X=1\n")
        write(self.root, ".gitignore", ".env\n")
        sh(self.root, "add", "-f", ".env")
        c = check_hygiene(self.root)
        self.assertEqual(c.status, "FAIL")
        self.assertIn("tracked sensitive file: .env", c.details)

    def test_tracked_keys_fail(self):
        names = ["id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "sub/server.pem", "k.key", ".env.production"]
        for n in names:
            write(self.root, n, "x")
        sh(self.root, "add", "-f", ".")
        c = check_hygiene(self.root)
        self.assertEqual(c.status, "FAIL")
        for n in names:
            self.assertIn(f"tracked sensitive file: {n}", c.details)

    def test_env_templates_allowed(self):
        for n in [".env.example", ".env.sample", ".env.template", ".env.test"]:
            write(self.root, n, "X=")
        sh(self.root, "add", "-f", ".")
        self.assertEqual(check_hygiene(self.root).status, "PASS")

    def test_non_git_dir_env_needs_gitignore(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, ".env", "X=1")
            self.assertEqual(check_hygiene(d).status, "FAIL")
            write(d, ".gitignore", ".env\n")
            self.assertEqual(check_hygiene(d).status, "PASS")


if __name__ == "__main__":
    unittest.main()
