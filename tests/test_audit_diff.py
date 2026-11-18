import json
import os
import subprocess
import tempfile
import unittest

from factory import audit_diff as ad

# Fixture strings are assembled from pieces so this test file never trips the scanner.
AWS = "".join(["AKIA", "1234567890ABCDEF"])
EV = "".join(["ev", "al"])
MARK = "-".join(["factory", "audit", "ignore"])
SQ = "".join(["SEL", "ECT"])


def sh(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def write(root, rel, text="", binary=False):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb" if binary else "w") as fh:
        fh.write(text)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def git_repo(self):
        sh(self.root, "init", "-q")
        sh(self.root, "config", "user.name", "t")
        sh(self.root, "config", "user.email", "t@example.com")

    def rules(self, r):
        return {f["rule"] for f in r["findings"]}

    def scan(self, rel, text):
        write(self.root, rel, text)
        return ad.audit(self.root, all_files=True)


class AuditTests(Base):
    def test_clean_approve(self):
        r = self.scan("ok.js", "export const x = 1;\n")
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")
        self.assertEqual(r["findings"], [])
        self.assertGreaterEqual(r["files_scanned"], 1)

    def test_flagged_exec_and_secret(self):
        r = self.scan("unsafe.js", f'const k = "{AWS}";\nexport function f(u) {{\n  return {EV}(u);\n}}\n')
        self.assertEqual(r["status"], "FLAGGED")
        self.assertEqual(self.rules(r), {"dangerous-exec", "hardcoded-secret"})
        self.assertEqual([f["line"] for f in r["findings"]], [1, 3])

    def test_secret_assign_and_placeholders(self):
        r = self.scan("c.py", 'password = "hunter2hunter2"\napi_key = "your_api_key_here"\n'
                              'token = "${TOKEN_VALUE}"\nsecret = "<secret-value>"\n')
        self.assertEqual([f["line"] for f in r["findings"]], [1])
        self.assertIn("password", r["findings"][0]["message"])

    def test_pem_header(self):
        r = self.scan("k.txt", "-----BEGIN " + "RSA PRIVATE KEY-----\n")
        self.assertEqual(r["status"], "FLAGGED")

    def test_prose_and_env_template_exempt(self):
        write(self.root, "README.md", f'password = "hunter2hunter2"\n{EV}(x)\n')
        write(self.root, ".env.example", 'API_KEY="realistic-looking-1234"\n')
        r = ad.audit(self.root, all_files=True)
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")

    def test_prose_still_flags_aws_key(self):
        r = self.scan("notes.md", f"{AWS}\n")
        self.assertEqual(r["status"], "FLAGGED")

    def test_ignore_marker(self):
        r = self.scan("a.js", f"{EV}(x); // {MARK}\n")
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")

    def test_python_exec_variants(self):
        src = "\n".join([
            "".join(["os.sys", "tem('ls ' + d)"]),
            "".join(["subprocess.run(f'ls {d}', shell=Tr", "ue)"]),
            "".join(["subprocess.run(['ls'], shell=Tr", "ue)"]),
            "".join(["ex", "ec(code)"]),
            "m = pattern.exec(text)",
            "",
        ])
        r = self.scan("p.py", src)
        lines = sorted(f["line"] for f in r["findings"] if f["rule"] == "dangerous-exec")
        self.assertEqual(lines, [1, 2, 4])

    def test_node_exec_template(self):
        src = "".join(["exec", "Sync(`ls ${dir}`);\n"])
        self.assertEqual(self.rules(self.scan("n.js", src)), {"dangerous-exec"})

    def test_xss_medium_is_warn(self):
        r = self.scan("v.js", "el." + "innerHTML" + " = x;\n")
        self.assertEqual(r["status"], "WARN")
        self.assertEqual(r["findings"][0]["rule"], "xss-sink")
        self.assertEqual(r["findings"][0]["severity"], "medium")
        r = self.scan("w.jsx", "<div " + "dangerouslySet" + "InnerHTML={{__html: h}} />\n")
        self.assertIn("xss-sink", self.rules(r))

    def test_sql_interpolation(self):
        src = "\n".join([
            "const q = `" + SQ + " * FROM t WHERE id = ${id}`;",
            "q = f\"" + SQ + " * FROM t WHERE id = {uid}\"",
            "q = \"" + SQ + " * FROM t WHERE id = {}\".format(uid)",
            "cur.execute(\"" + SQ + " * FROM t WHERE id = %s\", (uid,))",
            "const ok = `" + SQ + " * FROM t WHERE id = $1`;",
            "",
        ])
        r = self.scan("s.py", src)
        self.assertEqual([f["line"] for f in r["findings"]], [1, 2, 3])
        self.assertEqual(self.rules(r), {"sql-interpolation"})

    def test_binary_and_skip_lists(self):
        write(self.root, "blob.dat", b"\x00" + (EV + "(x)").encode(), binary=True)
        write(self.root, "node_modules/p/i.js", f"{EV}(x)\n")
        write(self.root, "package-lock.json", f'"token": "abcdefghijk"\n')
        write(self.root, "img.png", EV.encode() + b"(x)", binary=True)
        r = ad.audit(self.root, all_files=True)
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")
        self.assertEqual(r["files_scanned"], 0)

    def test_base_validation(self):
        with self.assertRaises(ValueError):
            ad.audit(self.root, base="--output=/tmp/x")

    def test_invalid_base_revision_raises(self):
        self.git_repo()
        write(self.root, "a.js", "1\n")
        sh(self.root, "add", "."); sh(self.root, "commit", "-qm", "init")
        with self.assertRaises(ValueError):
            ad.audit(self.root, base="nonexistent_ref_xyz")

    def test_symlinks_skipped(self):
        with tempfile.TemporaryDirectory() as outside:
            write(outside, "bad.js", f"{EV}(x)\n")
            os.symlink(os.path.join(outside, "bad.js"), os.path.join(self.root, "link.js"))
            r = ad.audit(self.root, all_files=True)
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")

    def test_own_source_is_clean(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        r = ad.audit(os.path.join(here, "factory"), all_files=True)
        mine = {"audit_diff.py", "hygiene.py", "detect.py"}
        self.assertEqual([f for f in r["findings"] if f["file"] in mine], [])


class GitModeTests(Base):
    def test_only_changed_files_scanned(self):
        self.git_repo()
        write(self.root, "old.js", f"{EV}(x)\n")
        sh(self.root, "add", "."); sh(self.root, "commit", "-qm", "init")
        write(self.root, "new.js", "const a = 1;\n")
        r = ad.audit(self.root)
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")
        self.assertEqual(r["files_scanned"], 1)
        write(self.root, "sub/bad.js", f"{EV}(x)\n")  # untracked in subdir (-uall)
        r = ad.audit(self.root)
        self.assertEqual([f["file"] for f in r["findings"]], ["sub/bad.js"])

    def test_base_diff_includes_committed_changes(self):
        self.git_repo()
        write(self.root, "a.js", "1\n")
        sh(self.root, "add", "."); sh(self.root, "commit", "-qm", "init")
        write(self.root, "b.js", f"{EV}(x)\n")
        sh(self.root, "add", "."); sh(self.root, "commit", "-qm", "two")
        self.assertEqual(ad.audit(self.root)["status"], "APPROVE_CANDIDATE")
        r = ad.audit(self.root, base="HEAD~1")
        self.assertEqual(r["status"], "FLAGGED")

    def test_deleted_file_ignored_and_allow_paths(self):
        self.git_repo()
        write(self.root, "gone.js", "1\n")
        sh(self.root, "add", "."); sh(self.root, "commit", "-qm", "init")
        os.remove(os.path.join(self.root, "gone.js"))
        write(self.root, "src/a.js", "1\n")
        write(self.root, "other/b.js", "1\n")
        r = ad.audit(self.root, allow_paths=["src/**"])
        self.assertEqual([(f["rule"], f["file"]) for f in r["findings"]],
                         [("slice-boundary-violation", "other/b.js")])
        self.assertEqual(r["status"], "FLAGGED")

    def test_scoped_to_subdir_root(self):
        self.git_repo()
        write(self.root, "pkg/a.js", "1\n")
        write(self.root, "top.js", f"{EV}(x)\n")
        r = ad.audit(os.path.join(self.root, "pkg"))
        self.assertEqual(r["status"], "APPROVE_CANDIDATE")
        self.assertEqual(r["files_scanned"], 1)


class GlobTests(unittest.TestCase):
    def test_matches(self):
        m = ad.matches_allowed_path
        self.assertTrue(m("src/a/b.js", ["src/**"]))
        self.assertTrue(m("src", ["src/**"]))
        self.assertTrue(m("src/a.js", ["src/*"]))
        self.assertTrue(m("src/a.js", ["src"]))
        self.assertTrue(m("src/a.js", ["src/"]))
        self.assertTrue(m("./src/a.js", ["./src"]))
        self.assertFalse(m("srcx/a.js", ["src"]))
        self.assertTrue(m("x", ["**"]))
        self.assertTrue(m("a/b.test.js", ["**/*.test.js"]))
        self.assertTrue(m("b.test.js", ["**/*.test.js"]))  # zero-depth **/
        self.assertFalse(m("a/b.js", ["*.js"]))
        self.assertTrue(m("b.js", ["*.js"]))
        self.assertTrue(m("a/b.js", ["a/?.js"]))
        self.assertFalse(m("other/b.js", ["src/**", "docs"]))
        self.assertFalse(m("a.js", []))


class FormatterTests(Base):
    def test_check_sarif_markdown(self):
        r = self.scan("u.js", f"{EV}(x);\nel." + "innerHTML" + " = y;\n")
        c = ad.to_check(r)
        self.assertEqual((c.id, c.status), ("audit-diff", "FAIL"))
        self.assertEqual(len(c.details), 2)
        s = ad.to_sarif(r)
        self.assertEqual(s["version"], "2.1.0")
        self.assertEqual(s["runs"][0]["tool"]["driver"]["name"], "factory")
        levels = [x["level"] for x in s["runs"][0]["results"]]
        self.assertEqual(levels, ["error", "warning"])
        self.assertEqual(s["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"], 1)
        json.dumps(s)
        md = ad.to_markdown(r)
        self.assertIn("FLAGGED", md)
        self.assertIn("`dangerous-exec`", md)
        self.assertIn("`u.js:1`", md)

    def test_check_pass_variants(self):
        self.assertEqual(ad.to_check(self.scan("a.js", "1\n")).status, "PASS")
        warn = self.scan("b.js", "el." + "innerHTML" + " = y;\n")
        c = ad.to_check(warn)
        self.assertEqual((warn["status"], c.status), ("WARN", "PASS"))
        self.assertEqual(len(c.details), 1)


if __name__ == "__main__":
    unittest.main()
