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
#   wixie_posix_pid_gone PID [TRIES]
#                                   POSIX only. D28 (WIX-PDF-POSIX-TREEKILL-001): true once PID is no
#                                   longer a live process, polling every 0.1s for at most TRIES
#                                   (default 50, i.e. 5s) polls; false if it is still alive after that.
#                                   A zombie (state Z in /proc/PID/stat: exited, only awaiting its
#                                   reaper) counts as gone; without /proc the check is `kill -0`.

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

wixie_posix_pid_gone() {
  local pid="$1" tries="${2:-50}" i=0 state
  while [ "$i" -lt "$tries" ]; do
    if [ -d /proc/self ]; then
      # field 3 of /proc/PID/stat is the state; strip "PID (comm) " first (comm may contain spaces)
      state="$(sed -E 's/^[0-9]+ \(.*\) ([A-Za-z]).*/\1/' "/proc/$pid/stat" 2>/dev/null)" || state=""
      { [ -z "$state" ] || [ "$state" = Z ]; } && return 0
    else
      kill -0 "$pid" 2>/dev/null || return 0
    fi
    sleep 0.1
    i=$((i + 1))
  done
  return 1
}
