# shellcheck shell=bash
# Portable fake "browser" executables for the html-to-pdf tests (WIX-PDF-001). Source it; do not
# execute it.
#
# D27 (test-pdf-browser-fallback, test-pdf-fix-round1, test-pdf-fix-round2): the stubs used to be
# Windows-only .bat files, which POSIX cannot execute (EACCES). The same two shapes are now written
# per platform, with the same behaviour:
#   Windows (Git Bash/MSYS/Cygwin): NAME.bat, run by cmd.exe, exactly the previous stub bodies.
#   POSIX:                          NAME.sh, #!/bin/sh, chmod +x.
#
#   WIXIE_FAKE_BROWSER_EXT          .bat or .sh; a stub's path is "$dir/$name$WIXIE_FAKE_BROWSER_EXT".
#   wixie_fake_browser DIR NAME     wrapper that forwards its argv to DIR/NAME.py (written by the
#                                   caller) and exits with that script's exit code.
#   wixie_fake_browser_hang DIR NAME
#                                   hangs forever as a pure in-process busy loop that spawns no
#                                   child, so a timeout has only the one tracked process to bound
#                                   (a wrapper that runs `python hang.py` would leave a grandchild
#                                   holding the output pipes open; see test-pdf-browser-fallback.sh).

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) WIXIE_FAKE_BROWSER_EXT=.bat ;;
  *) WIXIE_FAKE_BROWSER_EXT=.sh ;;
esac

wixie_fake_browser() {
  local dir="$1" name="$2" f="$1/$2$WIXIE_FAKE_BROWSER_EXT"
  mkdir -p "$dir"
  if [ "$WIXIE_FAKE_BROWSER_EXT" = .bat ]; then
    printf '@echo off\npython "%%~dp0%s.py" %%*\n' "$name" > "$f"
  else
    printf '#!/bin/sh\nexec python "$(dirname "$0")/%s.py" "$@"\n' "$name" > "$f"
    chmod +x "$f"
  fi
}

wixie_fake_browser_hang() {
  local dir="$1" name="$2" f="$1/$2$WIXIE_FAKE_BROWSER_EXT"
  mkdir -p "$dir"
  if [ "$WIXIE_FAKE_BROWSER_EXT" = .bat ]; then
    printf '@echo off\r\nfor /L %%%%i in (1,1,2000000000) do rem\r\n' > "$f"
  else
    printf '#!/bin/sh\nwhile :; do :; done\n' > "$f"
    chmod +x "$f"
  fi
}
