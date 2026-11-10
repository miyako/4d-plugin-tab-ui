# Tab UI ownership audit

## Provenance and complete tracked native inventory

Baseline: `b195649d3229792cf55ff8652cb3dbea51af381e` on `master`.
The ownership guidance was read from `miyako/skills`,
`4d-skills/skills/4dplugin/SKILL.md` at immutable commit
`e6b492fcb81e5e1a7f7db723594b420e63bf6eb9`.
The synthetic engine model is adapted from `miyako/4d-plugin-system-beep`
at `d357fdcfef0e825e5d3a44aaaa8eae98a7b43d09`, not its test results.

The entire baseline native source inventory is the seven SDK files below,
`4DPlugin-tab-ui.{cpp,h}`, and `support/4DPlugin-JSON.{cpp,h}`.
There is no Classes/pluginClasses directory, CPicture, C_TEXT, CBytes,
createCopy, pointer-reference constructor, worker, or owning user-defined
C++ wrapper here. Those other repositories' defects and fixes do not apply
by analogy. `CUTF16String` and `CUTF8String` are value-owning standard
basic_string typedefs; the other local buffer wrapper is standard vector.

Unchanged bundled SDK Git blobs (not inferred from API names or version):

| File under `4D Plugin API/` | Git blob |
|---|---|
| 4DPluginAPI.c | `4910d0a7b2c74a531833978776f9ac4be1c2aff3` |
| 4DPluginAPI.h | `be252f746417cb1302af1078b82892a4f89bc2bc` |
| 4DPluginAPI.def | `5bbdb82fb724b6f8e307feb01d9f158b802de89d` |
| EntryPoints.h | `4ae62f8ede4c7817caa5a32b12ea8a34c8c2e110` |
| Flags.h | `7a5a35539f27430a3fd9cb711d6b789051316471` |
| PrivateTypes.h | `a3098cb662cdbc43ba574fdef72a059c4c6d1cd4` |
| PublicTypes.h | `9ae20b001bff9128f690fff3e6c3f873b6238333` |

`4DPluginAPI.c` says rev v14, the headers rev v13; neither identifies a
verified upstream release. SDK Readme blob is
`c48263032a5a4ab4a7749b48a3c9e7c6062231ef`.
Baseline plugin source/header blobs are
`f3342e90ef95a4d1c15f1d3d4dc48a1ec1353840` /
`a8f0be32bb76b69f6b0dc6ab04d579f490c35aef`;
JSON source/header blobs are
`a5122d68e881476b97332a6a4f40a7b3e3adeb3f` /
`80aa1f1332655244c4ad4ff09197cb38dcd63912`.

The root manifest and prebuilt bundle manifest are identical blob
`cb545b99a9522532cbfd8a6db408ff5d61345c92`: selectors 1-7,
six void commands and scalar Text result on selector 2, Longint inputs
plus scalar Text input on selector 3, all declared threadSafe. No array
parameter/result is declared. This is not the reason to exclude arrays:
the full SDK array implementation and all internal helper paths were also
examined and array-transfer controls execute the actual SDK.

Xcode's Sources phase compiles all three translation units: complete SDK,
dispatcher, and JSON. Visual Studio lists only SDK and dispatcher, not JSON;
the dispatcher imports Cocoa unconditionally. No Windows/native-ABI
validation is claimed. Every JSON helper is compiled by the regression even
though the actual seven dispatcher commands do not call JSON. The observed
JSON leaks are latent helper defects, not a proven production command leak.
The dispatcher window-identifier snapshot is command-reachable.

Complete JSON helper inventory: `json_wconv`; picture setter; both UTF-8
string setters; wide-string and CUTF16String setters; wide/narrow object
setters; collection setter; wide/narrow real setters; integer and boolean
setters; wide/narrow null setters; property existence; string, boolean,
real, collection and object getters; JSON stringify. The harness executes
every overload. There are no additional native sources, wrappers, export
lists, project source memberships, or internal callback helpers in the
tracked baseline. Tracked prebuilt binaries/signatures and 4D test project
data were inventoried by name only, not loaded, run, or modified.

## Exact SDK contracts and surgical changes

SDK source lines 265-307 create/dispose/content-set engine-backed strings.
Lines 3920-4070 allocate an empty string or picture when creating those
variable kinds. Lines 4254-4285 shallow-assign string/picture descriptors
without clearing old owners. The four JSON string setters and picture
setter now start Undefined before adopting their supplied descriptor;
their existing final variable clear stays. Picture/object/collection
setter input ownership behavior is preserved, not redefined as borrowed.
Object variables start null, so their initial state does not leak.

SDK lines 637-653 explicitly require clearing a successful property
variable. String/boolean/real getters now clear every successful result,
including mismatched owning values. Object/collection getters clear only
successful mismatches, handing the matching owned reference to the caller
as before. Their caller must dispose the returned reference.

Immediately capture `PA_GetLastError` after property or command retrieval,
before kind inspection, argument cleanup, adoption, or other SDK calls.
An error return's payload is unspecified and is neither interpreted nor
cleared. Raw fType zero is especially unsafe: `UnifyVarKind` at 1713-1739
normalizes it to string. Stringify checks duplication before proceeding,
captures stringify's error before clearing its independent synchronous
argument, and clears successful string or mismatched results exactly once.
The original object's ownership is independent of the duplicated argument.

The window getter formerly returned a borrowed NSString from its protected
main-thread block and then read it on the caller thread. It now copies all
UTF-16 units into an owned vector inside that block; the buffer, including
its zero-initialized terminator, remains live across `PA_ReturnString`.
No new Objective-C owner or exception/error channel is introduced.
The setter consumes its borrowed 4D parameter synchronously, creates an
independent NSString for the window setter, and releases it after use.
Five asynchronous action commands capture a window, not a string.

SDK lines 4738-4755 return a borrowed array string; 4933-4950 dispose the old
element then shallow-transfer the supplied descriptor, including index zero.
Wrong kind, null data, negative/out-of-range index, and null descriptor
reject assignment without consuming it. Array tests copy borrowed content
before replacement, never dispose transferred aliases, exercise replace,
allocator churn, shrink and final clear, and clean rejected owned inputs.
There is no plugin array insertion path to change.

`PA_SetStringField` explicitly remains non-owning. `PA_SetStringVariable`
is not the engine-backed content setter used by `PA_ReturnString`.
`PA_ConvertCharsetToCharset` returns bytes per source line 5296, but there
is no caller here: no invented byte-to-unit repair. Actual text conversion
uses CoreFoundation on macOS, with UTF-32 wchar_t inputs, UTF-16 lengths in
code units, and UTF-8 output lengths in bytes. Tests assert exact ASCII,
BMP and surrogate-pair content, UTF-16 lengths, termination, and both
allocated and null empty engine strings.

## Validation and named baseline failures

Run `python3 .github/tests/test_ownership.py` on macOS.
It compiles the entire unmodified SDK, entire JSON helper source, and actual
dispatcher together with an isolated host. No SDK fragment, replacement
SDK function, extracted production function, Xcode project build, plugin
bundle, or real 4D process is used.

Before any compilation/dispatch, a force-included header substitutes
NSWindow, NSThread, main queue lookup, sync/async dispatch, and SDK graphics
operations. The fake window implements only the expected tab selectors;
unexpected Objective-C messages fail via the runtime, engine selectors
and drawing operations fail explicitly. The import gate denies native
window/view/control/application/thread/process/file/network/system
boundaries and allows only NSObject/NSString/NSMutableString class imports.
Foundation string conversion/allocation and test-runner temporary files
are used; no actual UI creation, mutation, enumeration, event loop, system
setting, private data, or native platform action occurs.

The same final harness compiles fixed sources or a separate immutable
`git archive b195649d3229792cf55ff8652cb3dbea51af381e` of the complete native
source tree using `OWNERSHIP_SOURCE_ROOT`. AddressSanitizer and
UndefinedBehaviorSanitizer are enabled, excluding alignment checks for the
unchanged SDK's explicitly packed ABI. LeakSanitizer is disabled on macOS;
explicit registries require zero strings, pictures, handles, objects and
collections, with retain/release balances and duplicate-free checks.

Identical final harness SHA-256 fingerprints for both runs:
`ownership_host.mm` =
`549ceb394d12f80cd7eed64174520148ecb9bc1c2ce94d06370c0a267f46a21f`;
`ownership_platform.h` =
`8fc7cc9c471453159f77ca404178dd483be54a837f1873eff0b68390cf9f0609`;
`test_ownership.py` =
`1e5916d4174133e889046113c6b50916351b0dad8cd9c119203601e296c690ca`.

| Named group | Cases | Baseline pass/fail | Fixed pass/fail |
|---|---:|---:|---:|
| setter_empty_owner_overwrite | 33 | 16 / 17 | 33 / 0 |
| getter_success_owners_and_mismatches | 70 | 29 / 41 | 70 / 0 |
| failed_unspecified_returns_and_stringify | 27 | 17 / 10 | 27 / 0 |
| actual_dispatcher_and_array_controls | 44 | 36 / 8 | 44 / 0 |
| **Total** | **174** | **98 / 76** | **174 / 0** |

The 17 setter failures are the four setters times four text fixtures with
allocated engine empties, plus the picture's overwritten creation owner.
The 41 getter failures are owning successful values not cleared (matching
string or mismatches); scalar matches, null empty strings and matching
object/collection handoffs supply passing controls.
Six poison-error cases trigger UBSan invalid-enum loads in the real SDK's
kind normalization; raw-zero string-getter/stringify and command-handle
failures trigger invalid string access checks; duplicate-object failure
triggers a dead-argument check. Eight snapshot cases detect borrowed
identifier invalidation after synthetic sync completion, before caller
encoding, using a mutable NSString test double; this is a deterministic
lifetime model, not an actual AppKit race/crash reproduction.
The remaining controls cover both main/worker queue branches, nil window,
all seven selectors, scalar setter modes, default/unknown selector no-op,
array accepted/rejected transfers, null/missing properties, successful
stringify and mismatched owning return cleanup.

## Limits, deferred gaps, and release isolation

No Windows build, native 4D host execution, AppKit window operation, exact
Windows crash reproduction, or native engine ABI certification was done.
The full SDK calls an engine; string-content-copy and returned property
reference semantics at that boundary remain explicit host-model contracts,
not inferred proof of every possible engine version.

Handle creation/resize failure predicates are exercised with an explicitly
preserving synthetic handle implementation. This does not certify SDK
resize failure preservation or OOM safety: bundled resize logic can update
metadata after failed resizing. No SDK/OOM rewrite is authorized here.
CoreFoundation conversion allocation failures and vector allocation throws
remain existing gaps, not covered success claims. Returned string getter
conversion failure after a successful property retrieval is not hardened
by speculative SDK cleanup contracts.

Failed helper outputs retain the existing false/zero/null or unchanged
output behavior (`ob_get_a` still reports existence). Key/argument cleanup
can overwrite the global last error. These helpers have no established
error-reporting channel; this narrow ownership fix adds none and does not
advertise those defaults as successful retrieval. Callback cancellation,
async window lifetime, invalid window-handle guarantees and unrelated
platform behavior are not certified by the synthetic synchronous actions.

Existing workflows, release/source-version scripts, pre-push hook, lifecycle
tests, both project files and scheme were inspected for side effects.
Build and Bump version are manual only. Xcode's shell phase signs, packages
and notarizes even outside a release workflow, so it was not run; the
scheme also names a real 4D application. No release script/lifecycle
publication simulation, tag, signing, notarization, install, dependency
install, manual dispatch, rerun, release, packaging or upload was executed.
Existing projects, SDK, manifests, versions, binaries and release workflows
are unchanged. The new read-only unsigned workflow is push-only, relevant
paths only, exact audit branch `miyako-tab-ui-ownership` plus `master`,
with no publishing or artifact-upload steps.
