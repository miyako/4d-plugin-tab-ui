# 4d-plugin-tab-ui

Window tabbing API for macOS. It gives 4D direct access to the native macOS window-tabbing
feature (the same tab bar/tab groups you get in Finder, Safari, TextEdit, etc.) for any window
in your 4D application — read or set a window's tab group, show or hide the tab bar, merge
windows into one tabbed window, and step through tabs — all built on `NSWindow`'s tabbing API.
Results are `Longint` and `Text` values; there's no picture, blob, or object result type used
anywhere in this plugin.

| Command | Returns | Purpose |
|---|---|---|
| [`TOGGLE WINDOW TAB OVERVIEW`](#toggle-window-tab-overview) | — | Show/dismiss the tab overview (thumbnail view of all tabs) |
| [`Get window tab id`](#get-window-tab-id) | Text | Read a window's current tab (tabbing) identifier |
| [`SET WINDOW TAB ID`](#set-window-tab-id) | — | Assign a window's tab identifier and tabbing mode |
| [`TOGGLE WINDOW TAB BAR`](#toggle-window-tab-bar) | — | Show/hide the tab bar |
| [`MERGE ALL WINDOWS`](#merge-all-windows) | — | Merge compatible windows into one tabbed window |
| [`SELECT NEXT WINDOW TAB`](#select-next-window-tab) | — | Switch to the next tab in the window's tab group |
| [`SELECT PREVIOUS WINDOW TAB`](#select-previous-window-tab) | — | Switch to the previous tab in the window's tab group |

**Platforms:** macOS (Cocoa) only. There is no Windows or Carbon build of this plugin — don't
call these commands in a Windows-hosted 4D application. Minimum macOS version is 10.12
(Sierra); `TOGGLE WINDOW TAB OVERVIEW` specifically additionally requires macOS 10.13 (High
Sierra).

---

## Requirements & platform notes

- **macOS only.** This plugin ships a Cocoa/macOS build exclusively — there's no Windows
  equivalent of native window tabbing, and no Windows binary is built for this plugin at all.
- **Minimum OS version, per command:**
  - `TOGGLE WINDOW TAB OVERVIEW` requires **macOS 10.13 (High Sierra)** or later.
  - All other commands require **macOS 10.12 (Sierra)** or later.
  - On an older macOS, the affected command silently does nothing — no 4D error, no visual
	change. If a command appears to have no effect, check the OS version first.
- **Every command's first parameter is a window reference number** — the same kind of
  `Longint` value 4D's own `Frontmost window` command returns (see the examples below, which are
  taken directly from the plugin's own test method). Passing a stale or invalid window number is
  not validated by the plugin; it resolves to no window internally and each command degrades
  gracefully (a no-op for the toggle/select/merge commands, an empty string for
  `Get window tab id`) rather than raising an error or crashing.
- **The five "action" commands are asynchronous / fire-and-forget:** `TOGGLE WINDOW TAB
  OVERVIEW`, `TOGGLE WINDOW TAB BAR`, `MERGE ALL WINDOWS`, `SELECT NEXT WINDOW TAB`, and
  `SELECT PREVIOUS WINDOW TAB` queue their window operation and return control to your 4D
  method immediately, before the operation necessarily runs. Don't write 4D code on the very
  next line that assumes the tab bar/overview/selection has already changed.
- **`Get window tab id` and `SET WINDOW TAB ID` are synchronous** — they wait for the actual
  window operation to finish before returning, since one of them needs to hand back a real
  result.

---

## TOGGLE WINDOW TAB OVERVIEW

### Syntax
```
TOGGLE WINDOW TAB OVERVIEW ( windowNumber )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number of the window to affect |
| Result | — | (no return value) |

### Description
Shows (or, if already showing, dismisses) the tab overview for `windowNumber`'s tab group — the
same Mission Control–style grid of tab thumbnails you get from the Window menu's "Show All
Tabs," or from the small tab-overview control macOS adds to a tabbed window's title bar.

Requires macOS 10.13+; does nothing on earlier systems. Runs asynchronously — see
[Requirements & platform notes](#requirements--platform-notes).

### Example
From the plugin's own test method (`test.4dm`):
```4d
TOGGLE WINDOW TAB OVERVIEW (Frontmost window:C447)
```

A generic version, toggling the overview for a specific window you've stored a reference to:
```4d
var $winRef : Longint
$winRef:=Open window(100;100;600;400)
TOGGLE WINDOW TAB OVERVIEW ($winRef)
```

---

## Get window tab id

### Syntax
```
Get window tab id ( windowNumber ) -> Function result
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number to query |
| Result | Text | The window's current tabbing identifier |

### Description
Returns the tabbing identifier currently assigned to `windowNumber` — the string macOS uses to
decide which windows are allowed to share a tab group. Two windows can only be merged into the
same tab group if they have the same tabbing identifier (and a compatible tabbing mode; see
[`SET WINDOW TAB ID`](#set-window-tab-id)).

Returns an empty string if the window has no tabbing identifier assigned (for example, after
`SET WINDOW TAB ID` disabled tabbing for it), or if `windowNumber` doesn't refer to a currently
open window.

### Example
From the plugin's own test method (`test.4dm`):
```4d
$id:=Get window tab id (Frontmost window:C447)  //4D Forms and Methods
```

Checking whether the frontmost window currently belongs to any tab group:
```4d
var $tabID : Text
$tabID:=Get window tab id (Frontmost window:C447)
If ($tabID#"")
	ALERT("This window's tab group is: "+$tabID)
Else
	ALERT("This window has no tab identifier assigned.")
End if
```

---

## SET WINDOW TAB ID

### Syntax
```
SET WINDOW TAB ID ( windowNumber ; tabID ; tabbingMode )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number to modify |
| `tabID` | Text | Tab (tabbing) identifier to assign. Pass an empty string to disable tabbing for this window entirely |
| `tabbingMode` | Longint | `0` = automatic (system decides, following the user's General preference for "Prefer tabs..."); any non-zero value = preferred (favor grouping into a tab). Ignored when `tabID` is an empty string |
| Result | — | (no return value) |

### Description
Assigns a tabbing identifier and tabbing mode to `windowNumber`, mirroring `NSWindow`'s own
`tabbingIdentifier`/`tabbingMode` properties:

- **When `tabID` is non-empty:** the window is given that identifier, and its tabbing mode is
  set to *preferred* (non-zero `tabbingMode`) or *automatic* (zero). Any other open window that
  is later given the **exact same** `tabID` becomes eligible to be grouped into the same tab
  group as this one.
- **When `tabID` is an empty string:** the window's identifier is cleared and its tabbing mode
  is set to *disallowed* — this window can never be tabbed with any other window, regardless of
  what `tabbingMode` was passed (that parameter is simply ignored in this case).

Runs synchronously — see [Requirements & platform notes](#requirements--platform-notes).

### Example
Give two windows the same tab identifier so they can be merged into one tabbed window:
```4d
var $win1; $win2 : Longint
$win1:=Open window(100;100;600;400)
SET WINDOW TAB ID ($win1;"my-report-windows";1)  // preferred

$win2:=Open window(150;150;600;400)
SET WINDOW TAB ID ($win2;"my-report-windows";1)

MERGE ALL WINDOWS ($win1)
```

Prevent a specific window from ever being tabbed:
```4d
SET WINDOW TAB ID (Frontmost window:C447;"";0)  // tabID empty => tabbing disallowed
```

---

## TOGGLE WINDOW TAB BAR

### Syntax
```
TOGGLE WINDOW TAB BAR ( windowNumber )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number of the window to affect |
| Result | — | (no return value) |

### Description
Shows the tab bar for `windowNumber`'s tab group if it's currently hidden, or hides it if it's
currently showing — the same effect as the Window menu's "Show Tab Bar"/"Hide Tab Bar" item.
Requires macOS 10.12+. Runs asynchronously — see
[Requirements & platform notes](#requirements--platform-notes).

### Example
```4d
TOGGLE WINDOW TAB BAR (Frontmost window:C447)
```

---

## MERGE ALL WINDOWS

### Syntax
```
MERGE ALL WINDOWS ( windowNumber )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number to use as the anchor/target window |
| Result | — | (no return value) |

### Description
Merges the app's open windows that share a compatible tabbing identifier into a single tabbed
window, anchored on `windowNumber` — the same effect as the Window menu's "Merge All Windows."
This only pulls together windows that were actually made tab-compatible via
[`SET WINDOW TAB ID`](#set-window-tab-id) (or the system default, if you never called it);
calling this command doesn't force unrelated windows to share a tab group. Requires macOS
10.12+. Runs asynchronously — see [Requirements & platform notes](#requirements--platform-notes).

### Example
```4d
MERGE ALL WINDOWS (Frontmost window:C447)
```

---

## SELECT NEXT WINDOW TAB

### Syntax
```
SELECT NEXT WINDOW TAB ( windowNumber )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number belonging to the tab group to step through |
| Result | — | (no return value) |

### Description
Switches `windowNumber`'s tab group to the next tab, wrapping around to the first tab after the
last — the same effect as the Window menu's "Select Next Tab" (⌘⇧]). Requires macOS 10.12+. Runs
asynchronously — see [Requirements & platform notes](#requirements--platform-notes).

### Example
```4d
SELECT NEXT WINDOW TAB (Frontmost window:C447)
```

---

## SELECT PREVIOUS WINDOW TAB

### Syntax
```
SELECT PREVIOUS WINDOW TAB ( windowNumber )
```

| Parameter | Type | Description |
|---|---|---|
| `windowNumber` | Longint | Window reference number belonging to the tab group to step through |
| Result | — | (no return value) |

### Description
Switches `windowNumber`'s tab group to the previous tab, wrapping around to the last tab before
the first — the same effect as the Window menu's "Select Previous Tab" (⌘⇧[). Requires macOS
10.12+. Runs asynchronously — see [Requirements & platform notes](#requirements--platform-notes).

### Example
```4d
SELECT PREVIOUS WINDOW TAB (Frontmost window:C447)
```

---

## Error handling & troubleshooting

- **No 4D error is ever raised by any command in this plugin.** There's no parameter
  validation; an invalid or stale `windowNumber` degrades to a harmless no-op (for the
  toggle/select/merge commands) or an empty-string result (for `Get window tab id`) instead of
  failing loudly.
- **A command that appears to silently do nothing is almost always an OS-version issue.**
  `TOGGLE WINDOW TAB OVERVIEW` needs macOS 10.13+; every other command needs macOS 10.12+.
  There's no other failure mode that produces "nothing happened."
- **An empty `tabID` in `SET WINDOW TAB ID` disables tabbing outright** (`tabbingMode` is
  ignored in that case) — it doesn't reset the window to the system default. If you want default
  behavior restored, pass a real `tabID` with `tabbingMode` set to `0` (automatic) instead of an
  empty string.
- **`MERGE ALL WINDOWS` only merges windows that already share a tabbing identifier.** If
  windows aren't merging the way you expect, confirm both windows were given the exact same
  `tabID` via `SET WINDOW TAB ID` first — `Get window tab id` is the quickest way to check.
- **The action commands are asynchronous.** Because `TOGGLE WINDOW TAB OVERVIEW`, `TOGGLE
  WINDOW TAB BAR`, `MERGE ALL WINDOWS`, `SELECT NEXT WINDOW TAB`, and `SELECT PREVIOUS WINDOW
  TAB` queue their work and return immediately, a 4D method that calls one of them and then
  immediately checks UI state (or calls `Get window tab id`) on the next line is racing the
  actual change. If you need to observe the result, add a short pause or trigger the check from
  a subsequent user action instead of the very next statement.

---

## Quick reference

```4d
// Read/set a window's tab identifier
var $id : Text
$id:=Get window tab id (Frontmost window:C447)
SET WINDOW TAB ID (Frontmost window:C447;"my-tab-group";1)  // 1 = preferred, 0 = automatic
SET WINDOW TAB ID (Frontmost window:C447;"";0)              // "" => tabbing disallowed

// Tab bar / tab group actions (all fire-and-forget)
TOGGLE WINDOW TAB OVERVIEW (Frontmost window:C447)  // macOS 10.13+
TOGGLE WINDOW TAB BAR (Frontmost window:C447)       // macOS 10.12+
MERGE ALL WINDOWS (Frontmost window:C447)           // macOS 10.12+
SELECT NEXT WINDOW TAB (Frontmost window:C447)      // macOS 10.12+
SELECT PREVIOUS WINDOW TAB (Frontmost window:C447)  // macOS 10.12+
```
