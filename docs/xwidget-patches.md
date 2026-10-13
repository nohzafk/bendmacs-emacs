# The xwidget patches: why, and how

This repository ships the emacs-plus UI patches and, on top of them, a
small set of local patches to Emacs's xwidget support on macOS. This
document is the reasoning behind the local ones: what we wanted, what in
Emacs stood in the way, what each patch changes and why it changes it that
way. The README's *Patches Applied* lists what is applied; this file says
why. The mechanics of applying patches (the lock file, SHA-256, `-F0`) are
in the README and `scripts/emacs-patches.sh`.

## What we wanted

Emacs is the interface for a coding agent here. The transcript, the prompt
and the files are text buffers, which is the point of using Emacs; but
some of what an agent produces is not text: a diagram, a large table, a
streaming tool window, a status card. For those we wanted a block *inside
a buffer* that is drawn by a modern renderer and still behaves as part of
the buffer: inserted with text, scrolled with text, clipped at the window
edge, hidden when scrolled away, answered from the keyboard without leaving
Emacs.

Emacs already has most of this. An xwidget is a glyph: `xwidget-insert`
puts it into the `display` property of a character, redisplay lays it out
like an image, and on every redraw `src/xwidget.c` computes the clip
rectangle and `src/nsxwidget.m` moves an `NSView` container to the glyph's
position. What Emacs does not have is any xwidget type but WebKit.

Two things made WebKit alone insufficient, both measured on this build:

- **Cost.** Every `xwidget-webkit` block is its own WebContent process:
  about 11 MB of physical footprint for a static page, 60 MB for a
  WebAssembly application, 150 to 250 MB for a page that has loaded a
  large JavaScript library. Twenty blocks in one buffer were 22 processes
  and, for application content, over a gigabyte. A transcript that lives
  for hours cannot hold many of them.
- **Reach.** A native view drawn with Metal costs about a megabyte and no
  process, draws at the display's refresh rate without a bridge, and can
  take Lisp values straight from a dynamic module instead of JSON over a
  loopback HTTP server. Emacs's dynamic-module API exposes no display at
  all, so a module can draw a view but cannot place it; redisplay can
  place a view but only a WebKit one.

The join is a one-line idea: let `make-xwidget` take a view the module
made. Everything else in the xwidget machinery already works for any
`NSView`.

## native-xwidget

`patches/emacs-31/native-xwidget.patch`. NS (Cocoa) only.

**What it adds.** `make-xwidget` accepts the type `native`. Its ARGUMENTS
parameter is then a user pointer, created by a dynamic module, whose
pointer is an `NSView` the module made and holds a reference to. Emacs
retains the view for the widget's life, puts it in the widget's container
(`xwWindow`) exactly where a `WKWebView` would go, and releases it in
`nsxwidget_kill`. From there on the view is placed, resized, clipped,
scrolled and hidden by the same code as a WebKit view: nothing in
redisplay knows the difference. The `xwidget-webkit-*` functions already
check the widget's type and signal "Not a WebKit widget" for a native one.
GTK and PGTK builds are untouched; there `native` is still a bad type.

**Why a user pointer and not a new C API.** The module API has user
pointers with finalizers and nothing else that can carry a native object;
the C side reads it with the macros `lisp.h` already has. The module keeps
its own reference, Emacs takes another, and the view survives whichever of
the two is dropped first. That was checked both ways.

**Why hide with `hidden` and not by moving off-screen.** Emacs hides a
WebKit view by moving its container to (10000, 10000), which WebKit copes
with. A native view has a render thread, and a view that keeps drawing out
of sight burns a core for nothing; with the move it would never learn it
was hidden. Setting the container's `hidden` property makes AppKit send
the module's view `viewDidHide` and `viewDidUnhide`, so it pauses and
resumes on its own. Measured: zero frames while hidden, 0.2 % of a core
for a static view at idle, where an always-drawing view cost 25 %. The
WebKit view keeps the move, so nothing changes for it.

**Two fixes that ride along**, found while checking the type and worth
having on their own:

- *Clipping.* Redisplay clips a widget by sizing its per-window container,
  and relies on AppKit clipping subviews to it. AppKit stopped doing that
  by default for programs linked against macOS 14 or later. On this build
  a WebKit xwidget cut by the window's bottom edge drew past it: the
  container was 600 × 108 points and the view's visible rectangle was the
  whole Emacs view. The container now sets `clipsToBounds`, for both
  types.
- *Double kill.* On NS, `kill-xwidget` never clears the widget's buffer, so
  a second call passes the liveness check, reaches `nsxwidget_kill` again
  and releases the container twice. `nsxwidget_kill` now returns early for
  a widget already killed. Found by reading the source, not reproduced.

**Limits it keeps.** One view per widget: the same buffer in two windows
shows the widget in one of them, for `native` as for WebKit. Keyboard
focus is the view's business: the module's view forwards keys to the
Emacs view unless it has been told to take them, and `C-g` always reaches
Emacs. Two AppKit facts a module author needs: Emacs's menu answers
`performKeyEquivalent:` for every key with a modifier before the first
responder sees it, so a view that wants `C-g` must implement that method;
and with the application deactivated AppKit never asks the view, so the
module also watches key events with a local monitor.

## ns-xwidget-scroll

`patches/emacs-31/ns-xwidget-scroll.patch`. NS only; touches only
`src/nsterm.m`. The defect it fixes was found by measurement and is not
caused by the patch above: it is in stock Emacs and affects WebKit
xwidgets equally.

Redisplay places a widget's view when it draws the glyph's row. When it
scrolls instead, moving rows that are already on screen by copying pixels
(`scroll_run_hook`), no row is drawn and no view moves. On X,
`x_scroll_run` in `src/xterm.c` has a `HAVE_XWIDGETS` branch that moves the
widgets' windows along with the scrolled area. `ns_scroll_run` in
`src/nsterm.m` moves no subview. So on macOS every one-line scroll, which
is what a mouse wheel does, leaves an xwidget's view where its row was
last drawn: 14 pixels per line on this build, 280 pixels after twenty
lines, the same for a WebKit view and a native one; `pixel-scroll-precision-mode`
shows it on every step. Only a redraw of the row, or `redraw-frame`, puts
the view back.

The patch ports that branch: when `ns_scroll_run` moves a run of rows, it
moves the views of the xwidgets inside the run by the same amount. A view
is selected by its widget's whole rectangle, not its clipped part, so a
widget clipped to nothing, or sitting in a row partly outside the text
area, moves with its row as well.

## What the patches do not do

- They do not change what the module draws or how; that is the module's
  side, outside this repository.
- They do not add a GTK or PGTK native type. The idea transfers (a
  `GtkWidget` instead of an `NSView`), but nothing here needs it.
- They do not report a crashed WebContent process to Emacs:
  `src/nsxwidget.m` implements no `webViewWebContentProcessDidTerminate:`,
  so a WebKit xwidget whose process died is a blank view Emacs knows
  nothing about. A candidate for a later patch.
- They do not add the `xwidget-webkit-title-change-hook` that some
  WebKit-based packages listen on. It does not exist in stock Emacs, and
  nothing here needs it: a page reaches Emacs through a loopback HTTP
  request instead.

## Upstream

The clipping fix and the double-kill fix are bugs in stock Emacs on
current macOS and are the natural candidates to send to emacs-devel. The
`native` type itself removes the one place where the xwidget machinery is
hard-wired to WebKit, in about sixty lines; whether to propose it is
open. The scroll-run port restores on macOS what X already does.

## Verifying a change here

`python3 tests/test_ui_patches.py` enumerates the patch set and asserts
each patch's order and intended effect, so a patch that stops doing what
this document says fails there. With `EBUILD_UI_TARGETS` pointing at a
pristine checkout it also applies the whole set at `-F0`. `python3
tests/test_source_pin.py` needs `BASH_ENV` unset (`env -u BASH_ENV`), as
noted in the repository's friction log. A local build of only Emacs is
`scripts/build.sh emacs` with `OUT` set to a new path: the script refuses
to overwrite an app built from a different patch set.
