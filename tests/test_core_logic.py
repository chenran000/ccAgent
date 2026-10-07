"""核心纯逻辑模块单测(标准库 unittest,无需额外依赖)

运行: python -m unittest discover tests -v
覆盖: 凭据加密 / 项目记忆 / 路径围栏与工具 / 规则引擎 / 上下文压缩 / 文本回退解析。
全部为纯逻辑测试,不访问网络、不需要 API Key。
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import agent_tools, memory, workspace as ws_mod
from app.credential_cipher import decrypt_credential, encrypt_credential
from app import inspector


def _tmpdir():
    d = tempfile.mkdtemp(prefix="ta_test_")
    return d


class TestCredentialCipher(unittest.TestCase):
    """AES-256-GCM 凭据加密"""

    def test_roundtrip(self):
        enc = encrypt_credential("sk-test-1234567890")
        self.assertTrue(enc.startswith("enc:v1:"))
        self.assertEqual(decrypt_credential(enc), "sk-test-1234567890")

    def test_empty_and_plaintext_passthrough(self):
        self.assertEqual(encrypt_credential(""), "")
        # 历史明文原样返回(读旧库不炸)
        self.assertEqual(decrypt_credential("plain-key"), "plain-key")

    def test_encrypt_idempotent(self):
        once = encrypt_credential("secret")
        self.assertEqual(encrypt_credential(once), once)

    def test_tampered_ciphertext_rejected(self):
        enc = encrypt_credential("secret-value")
        body = list(enc)
        body[-3] = "A" if body[-3] != "A" else "B"
        with self.assertRaises(ValueError):
            decrypt_credential("".join(body))

    def test_different_secret_cannot_decrypt(self):
        enc = encrypt_credential("secret-value")
        with mock.patch.dict(os.environ, {"TESTASSISTANT_CREDENTIAL_SECRET": "other-machine"}):
            with self.assertRaises(ValueError):
                decrypt_credential(enc)


class TestMemory(unittest.TestCase):
    """项目记忆:读写/去重/截断"""

    def setUp(self):
        self._patcher = mock.patch.object(memory, "DATA_DIR", Path(_tmpdir()))
        self._patcher.start()
        self.ws = _tmpdir()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.ws, ignore_errors=True)

    def test_read_missing_returns_empty(self):
        self.assertEqual(memory.read_memory(self.ws), "")

    def test_write_read_roundtrip(self):
        memory.write_memory(self.ws, "项目使用 FastAPI")
        self.assertIn("FastAPI", memory.read_memory(self.ws))

    def test_write_truncates_to_limit(self):
        memory.write_memory(self.ws, "x" * (memory.MEMORY_MAX_CHARS + 100))
        self.assertEqual(len(memory.read_memory(self.ws)), memory.MEMORY_MAX_CHARS)

    def test_append_dedup(self):
        memory.append_memory(self.ws, "使用 ruff 做格式化")
        once = memory.read_memory(self.ws)
        memory.append_memory(self.ws, "使用 ruff 做格式化")
        self.assertEqual(memory.read_memory(self.ws), once)
        self.assertIn("使用 ruff 做格式化", once)

    def test_append_adds_date_prefix(self):
        from datetime import date
        memory.append_memory(self.ws, "一条事实")
        self.assertIn(date.today().strftime("%Y-%m-%d"), memory.read_memory(self.ws))

    def test_append_empty_is_noop(self):
        self.assertEqual(memory.append_memory(self.ws, "  "), "")


class TestWorkspaceFence(unittest.TestCase):
    """路径围栏:_resolve 必须把一切路径限制在工作区内"""

    def setUp(self):
        self.ws = _tmpdir()
        self.state = Path(_tmpdir()) / "workspace.json"
        self._patcher = mock.patch.object(ws_mod, "WORKSPACE_FILE", self.state)
        self._patcher.start()
        ws_mod.set_current_workspace(self.ws)
        os.makedirs(os.path.join(self.ws, "src"), exist_ok=True)
        Path(self.ws, "src", "a.py").write_text("keyword_here = 1\n", encoding="utf-8")
        Path(self.ws, "notes.log").write_text("keyword_here in log\n", encoding="utf-8")

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.state.parent, ignore_errors=True)

    def test_relative_resolves_into_workspace(self):
        self.assertEqual(agent_tools._resolve("src/a.py"),
                         os.path.join(self.ws, "src", "a.py"))

    def test_dot_returns_workspace_root(self):
        self.assertEqual(agent_tools._resolve("."), self.ws)

    def test_absolute_inside_ok(self):
        self.assertEqual(agent_tools._resolve(os.path.join(self.ws, "src")),
                         os.path.join(self.ws, "src"))

    def test_parent_escape_rejected(self):
        with self.assertRaises(ValueError):
            agent_tools._resolve("../outside.txt")

    def test_absolute_outside_rejected(self):
        with self.assertRaises(ValueError):
            agent_tools._resolve(os.path.join(_tmpdir(), "evil.py"))

    def test_no_workspace_rejected(self):
        ws_mod.clear_workspace()
        with self.assertRaises(ValueError):
            agent_tools._resolve("a.py")
        ws_mod.set_current_workspace(self.ws)


class TestAgentTools(unittest.TestCase):
    """工具行为:搜索范围/写文件备份/未知工具"""

    def setUp(self):
        self.ws = _tmpdir()
        self.state = Path(_tmpdir()) / "workspace.json"
        self._patcher = mock.patch.object(ws_mod, "WORKSPACE_FILE", self.state)
        self._patcher.start()
        ws_mod.set_current_workspace(self.ws)
        Path(self.ws, "code.py").write_text("token = 'abc'\n", encoding="utf-8")
        Path(self.ws, "run.log").write_text("token in log\n", encoding="utf-8")

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.ws, ignore_errors=True)
        shutil.rmtree(self.state.parent, ignore_errors=True)

    def test_search_code_default_skips_non_code_files(self):
        out = agent_tools._tool_search_code({"query": "token"})["output"]
        self.assertIn("code.py", out)
        self.assertNotIn("run.log", out)

    def test_search_code_glob_overrides_default(self):
        out = agent_tools._tool_search_code({"query": "token", "glob": "log"})["output"]
        self.assertIn("run.log", out)

    def test_write_file_creates_backup_chain(self):
        rel = "code.py"
        agent_tools._tool_write_file({"path": rel, "content": "v1\n"})
        agent_tools._tool_write_file({"path": rel, "content": "v2\n"})
        agent_tools._tool_write_file({"path": rel, "content": "v3\n"})
        self.assertEqual(Path(self.ws, rel).read_text(encoding="utf-8"), "v3\n")
        self.assertEqual(Path(self.ws, rel + ".bak").read_text(encoding="utf-8"), "v2\n")
        self.assertEqual(Path(self.ws, rel + ".bak.1").read_text(encoding="utf-8"), "v1\n")

    def test_restore_backup_roundtrip(self):
        agent_tools._tool_write_file({"path": "code.py", "content": "old\n"})
        agent_tools._tool_write_file({"path": "code.py", "content": "new\n"})
        rel = agent_tools.restore_backup("code.py", ".bak")
        self.assertEqual(rel.replace(os.sep, "/"), "code.py")
        self.assertEqual(Path(self.ws, "code.py").read_text(encoding="utf-8"), "old\n")
        # 恢复前的内容(new)已入备份链,恢复本身可再撤销
        self.assertEqual(Path(self.ws, "code.py.bak").read_text(encoding="utf-8"), "new\n")

    def test_unknown_tool_fails_gracefully(self):
        result = agent_tools.execute_tool("no_such_tool", {})
        self.assertFalse(result["success"])
        self.assertIn("未知工具", result["output"])


class TestInspectorRules(unittest.TestCase):
    """规则引擎:命中/豁免/降级"""

    def setUp(self):
        self.ws = _tmpdir()
        # 隔离用户自定义规则,保证断言只针对内置规则
        self._patcher = mock.patch.object(inspector, "CUSTOM_RULES_PATH",
                                          Path(_tmpdir()) / "no_rules.json")
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.ws, ignore_errors=True)

    def _write(self, rel: str, text: str):
        full = os.path.join(self.ws, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        Path(full).write_text(text, encoding="utf-8")

    def _scan(self):
        return {(i["rule_id"], i["file"], i["line"]) for i in inspector.rule_scan(self.ws)}

    def test_secret_and_dangerous_hits(self):
        self._write("app.py", 'API_KEY = "sk-abcdefghijklmnopqrstuvwxyz"\n'
                              "eval(user_input)\n"
                              "print(debug_value)\n")
        hits = self._scan()
        self.assertIn(("SECRET_SK_KEY", "app.py", 1), hits)
        self.assertIn(("DANGEROUS_EVAL", "app.py", 2), hits)
        self.assertIn(("DEBUG_PRINT", "app.py", 3), hits)

    def test_comment_line_exempt(self):
        self._write("app.py", "# eval(x) 只是注释\n")
        self.assertNotIn(("DANGEROUS_EVAL", "app.py", 1), self._scan())

    def test_code_only_rules_skipped_in_docs(self):
        self._write("notes.md", "eval(x)\n")
        self.assertNotIn(("DANGEROUS_EVAL", "notes.md", 1), self._scan())

    def test_severity_demoted_in_test_files(self):
        self._write("tests/test_x.py", 'KEY = "sk-abcdefghijklmnopqrstuvwxyz"\n')
        sev = [i["severity"] for i in inspector.rule_scan(self.ws)
               if i["rule_id"] == "SECRET_SK_KEY"]
        self.assertEqual(sev, ["medium"])

    def test_health_score_floor_zero(self):
        issues = [{"severity": "critical"}] * 20
        self.assertEqual(inspector.health_score(issues), 0)
        self.assertEqual(inspector.health_score([]), 100)

    def test_parse_line(self):
        self.assertEqual(inspector._parse_line("L42"), 42)
        self.assertEqual(inspector._parse_line(""), 0)
        self.assertEqual(inspector._parse_line(None), 0)


class TestContextCompaction(unittest.TestCase):
    """agent_loop._compact:只保留最近 N 条工具结果"""

    def test_old_tool_results_replaced(self):
        from app.agent_loop import _compact, MAX_TOOL_RESULTS_IN_CONTEXT
        messages = [{"role": "system", "content": "sys"}]
        for i in range(MAX_TOOL_RESULTS_IN_CONTEXT + 5):
            messages.append({"role": "user", "content": f"u{i}"})
            messages.append({"role": "tool", "content": f"result-{i}"})
        out = _compact(messages)
        tool_contents = [m["content"] for m in out if m["role"] == "tool"]
        self.assertEqual(len(tool_contents), MAX_TOOL_RESULTS_IN_CONTEXT + 5)
        self.assertIn("result-0", tool_contents[0])  # 最早的被替换为占位
        self.assertTrue(tool_contents[0].startswith("(早期工具结果已省略"))
        self.assertEqual(tool_contents[-1], f"result-{MAX_TOOL_RESULTS_IN_CONTEXT + 4}")
        self.assertEqual(out[0]["content"], "sys")  # system 消息原样保留


class TestTextFallbackParser(unittest.TestCase):
    """create_structured 的纯文本回退解析(不发网络请求)"""

    class _Model(unittest.mock.MagicMock):
        pass

    def test_strip_code_fence(self):
        from app.llm import _strip_code_fence
        self.assertEqual(_strip_code_fence("```json\n{\"a\":1}\n```"), '{"a":1}')
        self.assertEqual(_strip_code_fence("```\n{\"a\":1}\n```"), '{"a":1}')
        self.assertEqual(_strip_code_fence('{"a":1}'), '{"a":1}')

    def test_parse_text_to_model(self):
        from pydantic import BaseModel

        class Pair(BaseModel):
            a: int = 0
            b: str = ""

        from app.llm import _parse_text_to_model
        parsed = _parse_text_to_model('前置说明\n```json\n{"a": 3, "b": "x"}\n```', Pair)
        self.assertEqual((parsed.a, parsed.b), (3, "x"))

    def test_parse_garbage_raises(self):
        from pydantic import BaseModel

        class Pair(BaseModel):
            a: int = 0

        from app.llm import _parse_text_to_model
        with self.assertRaises(ValueError):
            _parse_text_to_model("完全不是 JSON 的输出", Pair)


if __name__ == "__main__":
    unittest.main()
