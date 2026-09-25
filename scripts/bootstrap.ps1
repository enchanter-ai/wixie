# bootstrap.ps1 - Windows PowerShell mirror of bootstrap.sh.
#
# Same semantics and CLI as scripts/bootstrap.sh (see that file for the full
# WIX-INSTALL-002 spec: pinned vs floating mode, materialization into
# .vis-cache/vis/, the sibling vis checkout is never mutated).
#
# Modes:
#   .\scripts\bootstrap.ps1                     - pinned bootstrap, write .vis-lock
#   .\scripts\bootstrap.ps1 -Verify             - pinned verify (read-only, no network)
#   .\scripts\bootstrap.ps1 -Floating           - floating bootstrap (opt-in, dev only)
#   .\scripts\bootstrap.ps1 -Floating -Verify   - floating verify
#
# ---------------------------------------------------------------------------
# WIX-INSTALL-001: supported PowerShell contract
# ---------------------------------------------------------------------------
# Supported : Windows PowerShell 5.1 (Desktop edition). Verified live on
#             5.1.26100.9444: this file parses with 0 tokenizer errors and
#             every code path below (pinned/floating bootstrap and --verify,
#             success and failure) runs to its documented terminal state.
# Supported, unverified here : PowerShell 7+ (pwsh, Core edition). Nothing in
#             this script is known to be 5.1-only, but this host has no pwsh
#             installation (`command -v pwsh` -> not found) and none was
#             installed to check this box, per the remediation's "do not
#             install or download anything" constraint. Left explicitly
#             UNKNOWN rather than claimed. If you run this under pwsh and it
#             works (or doesn't), update this line with what you observed.
# Rejected before execution : PowerShell 2/3/4 (Major -lt 5) -- the version
#             gate below exits before touching git, .vis-versions or
#             CLAUDE.md, naming scripts/bootstrap.sh as the documented
#             cross-platform alternative.
# Non-Windows / no PowerShell at all : use scripts/bootstrap.sh.
#
# Encoding: this file is ASCII-only (0 bytes >= 0x80) AND carries a UTF-8 BOM
# (EF BB BF), belt-and-suspenders. Either alone would already fix the
# original defect (WIX-INSTALL-001: an em-dash and other non-ASCII characters
# with no BOM made Windows PowerShell 5.1's tokenizer decode this file under
# the legacy ANSI code page and choke on multi-byte sequences -- 10 parser
# errors, exit 1, before a single line executed). ASCII-only means the parser
# never has a multi-byte sequence to misinterpret in the first place, so
# encoding stops mattering; the BOM is kept anyway so a future edit that
# reintroduces non-ASCII text (an em-dash pasted from prose, a curly quote)
# still parses correctly instead of silently reintroducing this exact defect.
# ASCII-only was chosen over "just add a BOM and allow UTF-8 content" because
# a BOM is fragile on its own: any editor or tool that re-saves the file
# without preserving it (common; BOMs are easy to strip accidentally) puts
# WIX-INSTALL-001 right back. ASCII content has no such single point of
# failure. Keep new edits to this file ASCII; if non-ASCII text is genuinely
# needed, verify parsing under real Windows PowerShell 5.1 before committing.
# ---------------------------------------------------------------------------

[CmdletBinding()]
param(
    [switch]$Verify,
    [switch]$Floating
)

if ($PSVersionTable.PSVersion.Major -lt 5) {
    [Console]::Error.WriteLine(
        "unsupported PowerShell version: $($PSVersionTable.PSVersion) " +
        "(need Major -ge 5). Use Windows PowerShell 5.1+ / pwsh 7+, " +
        "or run scripts/bootstrap.sh instead.")
    exit 1
}

# "Continue", not "Stop": this script drives every control-flow decision off
# explicit $LASTEXITCODE / Test-Path checks and its own Fail() calls, several
# of which deliberately redirect an external git command's stderr (e.g. a
# rev-list on a tag that may legitimately not exist yet). Under "Stop",
# PowerShell promotes that redirected stderr into a terminating
# NativeCommandError even when git's own exit code is handled correctly,
# which would crash the script with a raw exception instead of this script's
# own curated "tag missing in vis: ..." message.
$ErrorActionPreference = "Continue"

$PluginDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VisDir = (Resolve-Path (Join-Path $PluginDir "..")).Path + "\vis"
$VisRepo = if ($env:VIS_REPO) { $env:VIS_REPO } else { "https://github.com/enchanter-ai/vis" }
$VersionsFile = Join-Path $PluginDir ".vis-versions"
$LockFile = Join-Path $PluginDir ".vis-lock"
$ClaudeMd = Join-Path $PluginDir "CLAUDE.md"
$CacheRoot = Join-Path $PluginDir ".vis-cache"
$CacheDir = Join-Path $CacheRoot "vis"
$Mode = if ($Floating) { "floating" } else { "pinned" }

function Fail([string]$msg) {
    [Console]::Error.WriteLine($msg)
    exit 1
}

# WIX-SEC-CLONE-001: VIS_REPO allowlist, mirroring bootstrap.sh exactly. See
# that file for the full rationale (two independent layers: this allowlist,
# plus `--` immediately before $VisRepo at every git invocation that takes
# it, so an option-shaped value can never be parsed as an option by git even
# if this allowlist were somehow bypassed).
function Test-VisRepo([string]$v) {
    if ($v.StartsWith("-")) {
        [Console]::Error.WriteLine("VIS_REPO looks like a command-line option, not a repository: $v")
        return $false
    }
    if ($v -match '^(https?|ssh)://') { return $true }
    if ($v -match '^git@[^:]+:') { return $true }
    if ($v.StartsWith("/")) { return $true }               # absolute POSIX path
    if ($v -match '^[A-Za-z]:[\\/]') { return $true }       # absolute Windows path
    [Console]::Error.WriteLine("VIS_REPO is not a supported source form: $v")
    [Console]::Error.WriteLine("  supported: https://..., http://..., ssh://..., git@host:path, or an absolute local path")
    return $false
}

if (-not (Test-Path $VersionsFile)) {
    Fail "missing $VersionsFile - every sibling plugin must pin vis packages"
}
if (-not (Test-Path $ClaudeMd)) {
    Fail "missing $ClaudeMd - bootstrap verifies @-imports against this file"
}

if ($Verify) {
    if (-not (Test-Path (Join-Path $VisDir ".git"))) {
        Fail "vis sibling missing - run ./scripts/bootstrap.sh"
    }
} else {
    if (-not (Test-Path (Join-Path $VisDir ".git"))) {
        if (-not (Test-VisRepo $VisRepo)) { exit 1 }
        [Console]::Error.WriteLine("vis sibling missing at $VisDir - cloning")
        & git clone -- $VisRepo $VisDir
        if ($LASTEXITCODE -ne 0) { Fail "clone failed - set VIS_REPO or clone manually" }
    }
    & git -C $VisDir fetch --tags --quiet 2>$null
    if ($LASTEXITCODE -ne 0) {
        [Console]::Error.WriteLine("note: git fetch --tags failed or unavailable (offline?) - continuing with local refs")
    }
}

# --- parse .vis-versions --------------------------------------------
$pkgs = @()
$vers = @()
Get-Content $VersionsFile | ForEach-Object {
    $line = ($_ -replace '#.*$', '').Trim()
    if (-not $line) { return }
    if ($line -match '^([a-z]+):\s*"?([~^]?[0-9][^"\s]+)"?\s*$') {
        $pkgs += $matches[1]
        $vers += ($matches[2] -replace '^[~^]', '')
    } else {
        [Console]::Error.WriteLine("warning: unparsed line in .vis-versions: $line")
    }
}

if ($pkgs.Count -eq 0) {
    Fail "no packages parsed from $VersionsFile"
}

# --- resolve per-package pin (pinned mode only) ------------------------------
$tagNames = @()
$tagCommits = @()
if ($Mode -eq "pinned") {
    for ($i = 0; $i -lt $pkgs.Count; $i++) {
        $tag = "enchanter-$($pkgs[$i])--v$($vers[$i])"
        $sha = & git -C $VisDir rev-list -n 1 "refs/tags/$tag" -- 2>$null
        if (-not $sha) {
            Fail "tag missing in vis: $tag"
        }
        $tagNames += $tag
        $tagCommits += $sha.Trim()
    }
}

function Get-PkgIndex([string]$name) {
    for ($i = 0; $i -lt $pkgs.Count; $i++) {
        if ($pkgs[$i] -eq $name) { return $i }
    }
    return -1
}

# --- walk CLAUDE.md for @-imports under the cache prefix ---------------------
$claudeText = Get-Content $ClaudeMd -Raw
$importMatches = [regex]::Matches($claudeText, '@\.vis-cache/vis/packages/[a-z]+/[A-Za-z0-9._/-]+\.[a-zA-Z]+')
$importPaths = $importMatches | ForEach-Object { $_.Value -replace '^@\.vis-cache/vis/', '' } | Sort-Object -Unique

# --- materialize into a staging dir, never touching the sibling's checkout ---
$stageDir = Join-Path $CacheRoot (".stage-{0}" -f $PID)
$hashPaths = @()
$hashValues = @()
$missing = $false

if (-not $Verify) {
    if (Test-Path $stageDir) { Remove-Item -Recurse -Force $stageDir }
    New-Item -ItemType Directory -Force -Path $stageDir | Out-Null

    try {
        foreach ($rel in $importPaths) {
            $dest = Join-Path $stageDir ($rel -replace '/', '\')
            New-Item -ItemType Directory -Force -Path (Split-Path $dest -Parent) | Out-Null

            if ($Mode -eq "pinned") {
                if ($rel -notmatch '^packages/([^/]+)/') {
                    [Console]::Error.WriteLine("import path does not belong to a package/: @.vis-cache/vis/$rel")
                    $missing = $true
                    continue
                }
                $pkg = $matches[1]
                $idx = Get-PkgIndex $pkg
                if ($idx -lt 0) {
                    [Console]::Error.WriteLine("import references package '$pkg' not declared in $VersionsFile`: @.vis-cache/vis/$rel")
                    $missing = $true
                    continue
                }
                $sha = $tagCommits[$idx]
                # Raw byte capture (not a PowerShell text pipeline): a text
                # pipeline splits into lines and rejoins with the platform
                # newline, which would silently rewrite LF to CRLF and change
                # the file's bytes (and therefore its hash) relative to what
                # bash's `git show ... > file` writes. Read git's stdout as a
                # byte stream instead, so pinned/floating cache content and
                # its sha1 are byte-identical to the bash entry point.
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = "git"
                $psi.Arguments = "-C `"$VisDir`" show $($sha):$($rel) --"
                $psi.RedirectStandardOutput = $true
                $psi.UseShellExecute = $false
                $gitProc = [System.Diagnostics.Process]::Start($psi)
                $ms = New-Object System.IO.MemoryStream
                $gitProc.StandardOutput.BaseStream.CopyTo($ms)
                $gitProc.WaitForExit()
                if ($gitProc.ExitCode -ne 0) {
                    [Console]::Error.WriteLine("import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ $($tagNames[$idx]) = $sha)")
                    $missing = $true
                    continue
                }
                [System.IO.File]::WriteAllBytes($dest, $ms.ToArray())
            } else {
                $src = Join-Path $VisDir ($rel -replace '/', '\')
                if (-not (Test-Path $src)) {
                    [Console]::Error.WriteLine("import resolves to missing file: @.vis-cache/vis/$rel (floating, vis working tree)")
                    $missing = $true
                    continue
                }
                Copy-Item -Path $src -Destination $dest -Force
            }

            $h = (Get-FileHash $dest -Algorithm SHA1).Hash.ToLower()
            $hashPaths += $rel
            $hashValues += $h
        }

        if ($missing) {
            Fail "one or more @-imports unresolved - the vis sibling is unchanged; nothing was written"
        }

        if (Test-Path $CacheDir) { Remove-Item -Recurse -Force $CacheDir }
        New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null
        Move-Item -Path $stageDir -Destination $CacheDir
    } finally {
        if (Test-Path $stageDir) { Remove-Item -Recurse -Force $stageDir -ErrorAction SilentlyContinue }
    }
} else {
    if (-not (Test-Path $CacheDir) -or -not (Test-Path $LockFile)) {
        Fail "vis not bootstrapped - run ./scripts/bootstrap.sh"
    }
    foreach ($rel in $importPaths) {
        $full = Join-Path $CacheDir ($rel -replace '/', '\')
        if (-not (Test-Path $full)) {
            [Console]::Error.WriteLine("import resolves to missing file in cache: @.vis-cache/vis/$rel - run ./scripts/bootstrap.sh")
            $missing = $true
            continue
        }
        $h = (Get-FileHash $full -Algorithm SHA1).Hash.ToLower()
        $hashPaths += $rel
        $hashValues += $h
    }
    if ($missing) { exit 1 }
}

# --- write or verify .vis-lock ------------------------------------------------
function Write-Lock {
    $iso = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# .vis-lock - auto-generated by scripts/bootstrap.sh")
    $lines.Add("# Do not edit by hand. Run ./scripts/bootstrap.sh to refresh.")
    $lines.Add("lock_version: 2")
    $lines.Add("mode: $Mode")
    $lines.Add("resolved_at: $iso")
    if ($Mode -eq "pinned") {
        $lines.Add("packages:")
        for ($i = 0; $i -lt $pkgs.Count; $i++) {
            $lines.Add("  $($pkgs[$i]):")
            $lines.Add("    version: v$($vers[$i])")
            $lines.Add("    tag: $($tagNames[$i])")
            $lines.Add("    tag_commit: $($tagCommits[$i])")
        }
    } else {
        $visHead = (& git -C $VisDir rev-parse HEAD).Trim()
        $lines.Add("vis_head: $visHead")
    }
    $lines.Add("conduct_files:")
    for ($i = 0; $i -lt $hashPaths.Count; $i++) {
        $lines.Add("  - path: $($hashPaths[$i])")
        $lines.Add("    sha1: $($hashValues[$i])")
    }
    Set-Content -Path $LockFile -Value $lines -Encoding ASCII
}

if (-not $Verify) {
    Write-Lock
    Write-Output "bootstrapped ($Mode): $($pkgs.Count) packages, $($hashPaths.Count) conduct files"
    Write-Output "materialized: $CacheDir"
    Write-Output "wrote $LockFile"
    exit 0
}

# -Verify path (both modes)
$lockText = Get-Content $LockFile -Raw

$lockMode = ([regex]::Match($lockText, '(?m)^mode:\s*(\S+)').Groups[1].Value)
if (-not $lockMode) {
    Fail "lock is stale or wrong-schema (missing 'mode:') - run ./scripts/bootstrap.sh"
}
if ($lockMode -ne $Mode) {
    Fail "lock mode mismatch: lock says $lockMode, verify requested $Mode - re-run bootstrap in that mode first"
}

if ($Mode -eq "pinned") {
    for ($i = 0; $i -lt $pkgs.Count; $i++) {
        $pkg = $pkgs[$i]
        $expected = $tagCommits[$i]
        $rx = "(?ms)^  $([regex]::Escape($pkg)):\s*$.*?^    tag_commit:\s*(\S+)"
        $m = [regex]::Match($lockText, $rx)
        if (-not $m.Success) { Fail "package $pkg missing from lock - run ./scripts/bootstrap.sh" }
        $observed = $m.Groups[1].Value
        if ($observed -ne $expected) {
            Fail "package ${pkg}: recorded tag/version no longer resolves to the same content (lock $observed, tag now resolves to $expected) - a moved/retagged pin, or .vis-versions changed without re-bootstrapping. Run ./scripts/bootstrap.sh"
        }
    }
} else {
    $lockHead = ([regex]::Match($lockText, '(?m)^vis_head:\s*(\S+)').Groups[1].Value)
    $liveHead = (& git -C $VisDir rev-parse HEAD).Trim()
    if ($lockHead -ne $liveHead) {
        Fail "vis drift (floating mode): lock says $lockHead, checkout is $liveHead - run ./scripts/bootstrap.ps1 -Floating to re-resolve"
    }
}

for ($i = 0; $i -lt $hashPaths.Count; $i++) {
    $rel = $hashPaths[$i]
    $expected = $hashValues[$i]
    $rx = "(?ms)^  - path:\s*$([regex]::Escape($rel))\s*$.*?^    sha1:\s*(\S+)"
    $m = [regex]::Match($lockText, $rx)
    if (-not $m.Success) { Fail "conduct file not in lock: $rel - run ./scripts/bootstrap.sh" }
    $observed = $m.Groups[1].Value
    if ($observed -ne $expected) {
        Fail "conduct file $rel modified in the materialized cache since bootstrap - re-bootstrap or revert .vis-cache/"
    }
}

Write-Output "verified ($Mode): $($hashPaths.Count) conduct files, $($pkgs.Count) packages"
exit 0
