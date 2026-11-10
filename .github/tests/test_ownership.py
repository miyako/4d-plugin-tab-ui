"""Actual dispatcher/helpers and complete unchanged SDK; synthetic UI only."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get("OWNERSHIP_SOURCE_ROOT", ROOT)).resolve()
SDK = {
    "4DPluginAPI.c": "4910d0a7b2c74a531833978776f9ac4be1c2aff3",
    "4DPluginAPI.h": "be252f746417cb1302af1078b82892a4f89bc2bc",
    "4DPluginAPI.def": "5bbdb82fb724b6f8e307feb01d9f158b802de89d",
    "EntryPoints.h": "4ae62f8ede4c7817caa5a32b12ea8a34c8c2e110",
    "Flags.h": "7a5a35539f27430a3fd9cb711d6b789051316471",
    "PrivateTypes.h": "a3098cb662cdbc43ba574fdef72a059c4c6d1cd4",
    "PublicTypes.h": "9ae20b001bff9128f690fff3e6c3f873b6238333",
}


@unittest.skipUnless(sys.platform == "darwin", "macOS synthetic host")
class OwnershipTests(unittest.TestCase):
    runs = 0
    passes = 0

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="tab-ui-ownership-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binary = Path(cls.temp.name) / "ownership"
        api = SOURCE / "4D Plugin API"
        for name, expected in SDK.items():
            contents = (api / name).read_bytes()
            blob = hashlib.sha1(f"blob {len(contents)}\0".encode() + contents).hexdigest()
            if blob != expected:
                raise AssertionError(f"Re-audit changed SDK: {name}: {blob}")
        result = subprocess.run([
            "clang++", "-std=c++14", "-x", "objective-c++", "-fblocks",
            "-include", str(ROOT / ".github/tests/ownership_platform.h"),
            "-I", str(api), "-I", str(SOURCE),
            "-fsanitize=address,undefined", "-fno-sanitize=alignment",
            "-fno-omit-frame-pointer", "-g",
            "-Wno-deprecated-declarations", "-Wno-return-type-c-linkage",
            "-Wno-ignored-attributes", "-Wno-writable-strings",
            str(api / "4DPluginAPI.c"),
            str(SOURCE / "support/4DPlugin-JSON.cpp"),
            str(SOURCE / "4DPlugin-tab-ui.cpp"),
            str(ROOT / ".github/tests/ownership_host.mm"),
            "-framework", "Cocoa", "-o", str(cls.binary),
        ], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        imports = subprocess.check_output(["nm", "-u", str(cls.binary)], text=True)
        linked = {line.split()[-1] for line in imports.splitlines() if line.split()}
        denied = {
            "_OBJC_CLASS_$_NSWindow", "_OBJC_CLASS_$_NSThread",
            "_OBJC_CLASS_$_NSView", "_OBJC_CLASS_$_NSControl",
            "_OBJC_CLASS_$_NSApplication", "_OBJC_CLASS_$_NSWorkspace",
            "_OBJC_CLASS_$_NSFileManager", "_OBJC_CLASS_$_NSProcessInfo",
            "_OBJC_CLASS_$_NSAppleScript", "_OBJC_CLASS_$_NSURL", "_NSApp",
            "_dispatch_sync", "_dispatch_async", "_dispatch_get_main_queue",
            "_system", "_popen", "_execve", "_posix_spawn", "_kill",
            "_open", "_fopen", "_socket", "_connect", "_getenv",
        } & linked
        denied |= {name for name in linked if name.startswith((
            "_Audio", "_AVAudio", "_CGContext", "_IOService", "_IOPM", "_IOPS",
        ))}
        allowed_classes = {
            "_OBJC_CLASS_$_NSObject", "_OBJC_CLASS_$_NSString",
            "_OBJC_CLASS_$_NSMutableString",
        }
        denied |= {name for name in linked if name.startswith("_OBJC_CLASS_$_")
                   and name not in allowed_classes}
        if denied:
            raise AssertionError(f"Real platform boundary linked: {denied}")

    @classmethod
    def tearDownClass(cls):
        print(f"LEAF runs={cls.runs} passed={cls.passes} "
              f"failed={cls.runs - cls.passes}", file=sys.stderr)

    def case(self, name, text="ASCII", empty="allocated", kind="string"):
        type(self).runs += 1
        result = subprocess.run(
            [str(self.binary), name, text, empty, kind],
            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0",
                 "UBSAN_OPTIONS": "halt_on_error=1"},
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            type(self).passes += 1
        self.assertEqual(result.returncode, 0, f"{name}/{text}/{empty}/{kind}: "
                         f"{result.stdout}{result.stderr}")
        self.assertIn("strings=0 pictures=0 handles=0 objects=0 collections=0", result.stdout)

    def test_setter_empty_owner_overwrite(self):
        for setter in ("set-narrow", "set-wide", "set-wchars", "set-utf16"):
            for text in ("ASCII", "\u65e5", "\U0001f600", ""):
                for empty in ("allocated", "null"):
                    with self.subTest(setter=setter, text=text, empty=empty):
                        self.case(setter, text, empty)
        self.case("set-picture")

    def test_getter_success_owners_and_mismatches(self):
        for getter in ("get-a", "get-b", "get-n", "get-c", "get-o"):
            for kind in ("string", "picture", "object", "collection", "boolean", "real"):
                for empty in ("allocated", "null"):
                    with self.subTest(getter=getter, kind=kind, empty=empty):
                        self.case(getter, "\u65e5\U0001f600", empty, kind)
            for empty in ("allocated", "null"):
                with self.subTest(getter=getter, empty=empty, text=""):
                    self.case(getter, "", empty, "string")

    def test_failed_unspecified_returns_and_stringify(self):
        for text in ("ASCII", "\u65e5", "\U0001f600", ""):
            for empty in ("allocated", "null"):
                with self.subTest(text=text, empty=empty):
                    self.case("stringify", text, empty)
        for kind in ("picture", "object", "collection", "boolean", "real"):
            with self.subTest(kind=kind):
                self.case("stringify", kind=kind)
        for case in ("get-a", "get-b", "get-n", "get-c", "get-o", "stringify"):
            for kind in ("error-poison", "error-kind0"):
                with self.subTest(case=case, kind=kind):
                    self.case(case, kind=kind)
        for kind in ("error-handle", "error-copy"):
            with self.subTest(case="stringify", kind=kind):
                self.case("stringify", kind=kind)

    def test_actual_dispatcher_and_array_controls(self):
        for empty in ("allocated", "null"):
            for text in ("ASCII", "\u65e5", "\U0001f600", ""):
                for name in ("dispatch-main", "dispatch-worker", "dispatch-nil", "array"):
                    with self.subTest(name=name, text=text, empty=empty):
                        self.case(name, text, empty)
                with self.subTest(snapshot=text, empty=empty):
                    self.case("dispatch-worker", text, empty, "invalidate")
        for case in ("sdk-failures", "values", "null-controls", "missing"):
            with self.subTest(case=case):
                self.case(case)


if __name__ == "__main__":
    unittest.main()
