# bootstrap.ps1 - Windows PowerShell mirror of bootstrap.sh.
#
# Same semantics and CLI as scripts/bootstrap.sh (see that file for the full
# WIX-INSTALL-002 spec: pinned vs floating mode, materialization into
# .vis-cache/vis/, the sibling vis checkout is never mutated, no fetch, the
# whole repo tree is scanned for @.vis-cache/vis/... imports, --verify
# re-derives every expected file from the pin and enforces exact schema and
# entry-set equality). This file must produce a BYTE-IDENTICAL .vis-lock to
# bash's for the same inputs (see the lock writer below) since the lock is
# committed to a repo other platforms also verify against.
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
# Keep new edits to this file ASCII; if non-ASCII text is genuinely needed,
# verify parsing under real Windows PowerShell 5.1 before committing.
#
# NOTE: the BOM/ASCII rule above is about THIS SCRIPT FILE. The .vis-lock
# it WRITES is a different file with its own, narrower rule: no BOM, LF-only
# line endings, ASCII content -- see the lock writer below.
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
# own curated error message.
$ErrorActionPreference = "Continue"

$LockSchemaVersion = "2"
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

# WIX-SEC-CLONE-001: VIS_REPO allowlist, mirroring bootstrap.sh exactly (see
# that file for the full rationale, including why an embedded double quote
# is refused: PowerShell 5.1 splits such a value into several native argv
# entries when invoking an external command, verified live).
function Test-VisRepo([string]$v) {
    if ($v.StartsWith("-")) {
        [Console]::Error.WriteLine("VIS_REPO looks like a command-line option, not a repository: $v")
        return $false
    }
    if ($v.Contains('"')) {
        [Console]::Error.WriteLine("VIS_REPO contains a double quote, which no supported source form needs: $v")
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

if (-not (Test-Path (Join-Path $VisDir ".git"))) {
    if ($Verify) {
        Fail "vis sibling missing - run ./scripts/bootstrap.sh"
    }
    # Creating a NEW sibling (nothing existing to mutate) is not the same as
    # fetching into one that's already there -- see the no-fetch note below.
    if (-not (Test-VisRepo $VisRepo)) { exit 1 }
    [Console]::Error.WriteLine("vis sibling missing at $VisDir - cloning")
    & git clone -- $VisRepo $VisDir
    if ($LASTEXITCODE -ne 0) { Fail "clone failed - set VIS_REPO or clone manually" }
}

# No `git fetch` here, ever, in either mode, against an existing sibling.
# `git fetch --tags` writes FETCH_HEAD, fast-forwards refs/remotes/origin/*,
# can add new tags, and can trigger background maintenance -- all real
# mutations of a checkout other repos/sessions may share. This script only
# ever reads: refs/tags/* resolution (rev-list) and blob content (show),
# both plumbing, neither one writes anything. If a needed tag is not present
# in the sibling's LOCAL refs, that is reported as an explicit failure
# telling the operator to fetch it themselves or wait for the vis owner to
# cut it -- this script will not do it silently on their behalf.

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

# --- resolve per-package pin (pinned mode only; read-only, local refs only) --
$tagNames = @()
$tagCommits = @()
if ($Mode -eq "pinned") {
    for ($i = 0; $i -lt $pkgs.Count; $i++) {
        $tag = "enchanter-$($pkgs[$i])--v$($vers[$i])"
        $sha = & git -C $VisDir rev-list -n 1 "refs/tags/$tag" -- 2>$null
        if (-not $sha) {
            [Console]::Error.WriteLine("vis tag $tag not found locally.")
            [Console]::Error.WriteLine("  This script never fetches automatically (to avoid mutating the shared vis sibling).")
            [Console]::Error.WriteLine("  Either fetch it yourself:  git -C $VisDir fetch --tags")
            [Console]::Error.WriteLine("  or the vis owner has not cut this release yet - wait for it.")
            [Console]::Error.WriteLine("  Only bump .vis-versions if you intend to pin a different, already-released version.")
            exit 1
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

# --- strict .vis-lock parser (-Verify only), mirroring bootstrap.sh's
# lock_strict_parse exactly. Parses the lock against the schema, not just
# well-enough-to-extract specific fields: rejects an unknown top-level key,
# an unknown key inside a package block or a conduct_files entry, a
# duplicate top-level key, a duplicate package block (even with a forged
# tag_commit), and a duplicate conduct_files entry (even with a bogus sha1).
# On success returns a hashtable: TopField, PkgNames, PkgField ("pkg:field"),
# ConductPaths, ConductSha1. On any violation, calls Fail() (exits 1).
function ConvertFrom-StrictLock([string]$text) {
    $topField = @{}
    $topSeen = @{}
    $pkgNames = New-Object System.Collections.Generic.List[string]
    $pkgSeen = @{}
    $pkgField = @{}
    $conductPaths = New-Object System.Collections.Generic.List[string]
    $conductSeen = @{}
    $conductSha1 = @{}

    $state = "top"
    $curPkg = $null
    $curPkgKeysSeen = @{}
    $curPath = $null
    $curPathHasSha1 = $false
    $lineno = 0

    $lines = $text -split "`r?`n"
    foreach ($line in $lines) {
        $lineno++
        if ($line.Length -eq 0) { continue }
        if ($line.StartsWith('#')) { continue }

        $topMatch = [regex]::Match($line, '^([A-Za-z_][A-Za-z0-9_]*):\s?(.*)$')
        if ($topMatch.Success) {
            $key = $topMatch.Groups[1].Value
            $val = $topMatch.Groups[2].Value
            if ($state -eq "conduct" -and $curPath -and -not $curPathHasSha1) {
                Fail "conduct entry incomplete (missing sha1) for path: $curPath (line $lineno)"
            }
            if ($key -notin @('lock_version','mode','resolved_at','packages','conduct_files','vis_head')) {
                Fail "unknown top-level key in lock: $key (line $lineno)"
            }
            if ($topSeen.ContainsKey($key)) {
                Fail "duplicate top-level key in lock: $key (line $lineno)"
            }
            $topSeen[$key] = $true
            if ($key -eq "packages") {
                $state = "packages"
            } elseif ($key -eq "conduct_files") {
                $state = "conduct"
                $curPath = $null
                $curPathHasSha1 = $false
            } else {
                $state = "top"
                $topField[$key] = $val
            }
            continue
        }

        if ($state -eq "packages" -or $state -eq "pkgblock") {
            if ($state -eq "pkgblock") {
                $fieldMatch = [regex]::Match($line, '^    ([a-z_]+):\s?(.*)$')
                if ($fieldMatch.Success) {
                    $fkey = $fieldMatch.Groups[1].Value
                    $fval = $fieldMatch.Groups[2].Value
                    if ($fkey -notin @('version','tag','tag_commit')) {
                        Fail "unknown key in package '$curPkg' block: $fkey (line $lineno)"
                    }
                    if ($curPkgKeysSeen.ContainsKey($fkey)) {
                        Fail "duplicate key '$fkey' in package '$curPkg' block (line $lineno)"
                    }
                    $curPkgKeysSeen[$fkey] = $true
                    $pkgField["$curPkg`:$fkey"] = $fval
                    continue
                }
            }
            $pkgMatch = [regex]::Match($line, '^  ([a-z][a-zA-Z0-9_]*):\s*$')
            if ($pkgMatch.Success) {
                $pkgname = $pkgMatch.Groups[1].Value
                if ($pkgSeen.ContainsKey($pkgname)) {
                    Fail "duplicate package block in lock: $pkgname (line $lineno)"
                }
                $pkgSeen[$pkgname] = $true
                $pkgNames.Add($pkgname)
                $curPkg = $pkgname
                $curPkgKeysSeen = @{}
                $state = "pkgblock"
                continue
            }
            Fail "malformed line under 'packages:' (line $lineno): $line"
        }

        if ($state -eq "conduct") {
            $pathMatch2 = [regex]::Match($line, '^  - path:\s?(.*)$')
            if ($pathMatch2.Success) {
                if ($curPath -and -not $curPathHasSha1) {
                    Fail "conduct entry incomplete (missing sha1) for path: $curPath (line $lineno)"
                }
                $p = $pathMatch2.Groups[1].Value
                if ($conductSeen.ContainsKey($p)) {
                    Fail "duplicate conduct_files entry for path: $p (line $lineno)"
                }
                $conductSeen[$p] = $true
                $conductPaths.Add($p)
                $curPath = $p
                $curPathHasSha1 = $false
                continue
            }
            $ckeyMatch = [regex]::Match($line, '^    ([a-z0-9_]+):\s?(.*)$')
            if ($ckeyMatch.Success) {
                $ckey = $ckeyMatch.Groups[1].Value
                $cval = $ckeyMatch.Groups[2].Value
                if (-not $curPath) {
                    Fail "conduct entry field '$ckey' with no preceding '- path:' (line $lineno)"
                }
                if ($ckey -eq "sha1") {
                    if ($curPathHasSha1) {
                        Fail "duplicate 'sha1' key for conduct entry: $curPath (line $lineno)"
                    }
                    $conductSha1[$curPath] = $cval
                    $curPathHasSha1 = $true
                } else {
                    Fail "unknown key in conduct_files entry '$curPath': $ckey (line $lineno)"
                }
                continue
            }
            Fail "malformed line under 'conduct_files:' (line $lineno): $line"
        }

        Fail "malformed line (line $lineno): $line"
    }

    if ($state -eq "conduct" -and $curPath -and -not $curPathHasSha1) {
        Fail "conduct entry incomplete (missing sha1) for path: $curPath (end of file)"
    }

    return @{
        TopField     = $topField
        PkgNames     = $pkgNames
        PkgField     = $pkgField
        ConductPaths = $conductPaths
        ConductSha1  = $conductSha1
    }
}

# --- enumerate every @-import across the WHOLE repo, by RESOLUTION ----------
# Not just CLAUDE.md, and not a literal "@.vis-cache/vis/" string match:
# every @<relpath> token in every *.md file is resolved relative to the FILE
# THAT CONTAINS IT (any number of ../ segments, any spelling), exactly like
# plugins/deep-research/agents/ciber.md's @../../../vis/... form. A resolved
# path landing inside the materialized cache is a real import that needs
# coverage; one landing directly in the raw sibling vis (not yet repointed to
# the cache) is a hard error.
#
# Exclusion of .git/.vis-cache/state/node_modules is applied to path
# components RELATIVE TO $PluginDir only -- never via a substring match
# against the FULL path, which would also match an ANCESTOR directory of the
# repo with one of those names (e.g. the repo checked out under
# ...\state\wixie) and silently exclude everything. That was the WIX-INSTALL-002
# fix-round-2 defect: PS materialized 0 files and exited 0 under such a
# parent directory, and -Verify exited 0 against a correct lock too.
# Byte-order (ordinal) unique + sort -- NOT Sort-Object's default culture
# comparison -- so entry order is identical to bash's `LC_ALL=C sort -u`
# for the same inputs (every path here is ASCII, so ordinal == C-locale).
$excludeNames = @('.git', '.vis-cache', 'state', 'node_modules')
$allMdFiles = Get-ChildItem -Path $PluginDir -Recurse -Filter '*.md' -File -ErrorAction SilentlyContinue
$mdFiles = @()
foreach ($f in $allMdFiles) {
    $rel = $f.FullName.Substring($PluginDir.Length).TrimStart('\', '/')
    $parts = $rel -split '[\\/]'
    $excluded = $false
    foreach ($p in $parts) { if ($excludeNames -contains $p) { $excluded = $true; break } }
    if (-not $excluded) { $mdFiles += $f }
}

$AtImportRegex = '@((?:\.\./)+|\.[A-Za-z0-9._-]*/|[a-z][A-Za-z0-9_-]*/)[A-Za-z0-9._/-]*\.[A-Za-z0-9]+'
$sep = [System.IO.Path]::DirectorySeparatorChar

$importSet = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
$unpinnedFound = $false
foreach ($f in $mdFiles) {
    $text = Get-Content $f.FullName -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }
    $fdir = $f.DirectoryName
    foreach ($m in [regex]::Matches($text, $AtImportRegex)) {
        $tok = $m.Value.Substring(1)
        try { $resolved = [System.IO.Path]::GetFullPath((Join-Path $fdir $tok)) } catch { continue }
        if ($resolved -eq $CacheDir -or $resolved.StartsWith($CacheDir + $sep)) {
            $key = ($resolved.Substring($CacheDir.Length).TrimStart('\', '/')) -replace '\\', '/'
            [void]$importSet.Add($key)
        } elseif ($resolved -eq $VisDir -or $resolved.StartsWith($VisDir + $sep)) {
            [Console]::Error.WriteLine("unpinned @-import: $($f.FullName) references @$tok, which resolves directly into the vis sibling ($resolved) instead of the materialized cache ($CacheDir...). Repoint it to the correct relative path into .vis-cache/vis/.")
            $unpinnedFound = $true
        }
    }
}
if ($unpinnedFound) {
    Fail "one or more @-imports resolve directly into the vis sibling instead of the materialized cache - the vis sibling is unchanged; nothing was written"
}

$importPaths = New-Object string[] ($importSet.Count)
$importSet.CopyTo($importPaths)
[Array]::Sort($importPaths, [System.StringComparer]::Ordinal)

if ($importPaths.Count -eq 0) {
    Fail "no @-imports resolving into the materialized cache were found anywhere in $PluginDir - refusing to bootstrap/verify an empty expected set (this is the failure mode a broken exclusion filter produces)"
}

# Fail-closed sanity floor, independent of the whole-repo walk above: CLAUDE.md
# alone is always found (it is a required top-level file, checked earlier) and
# its own imports must always be a subset of the final set.
$claudeOnlyCount = 0
$claudeText2 = Get-Content $ClaudeMd -Raw -ErrorAction SilentlyContinue
if ($claudeText2) {
    $claudeOnlySeen = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($m in [regex]::Matches($claudeText2, $AtImportRegex)) {
        $tok = $m.Value.Substring(1)
        try { $resolved = [System.IO.Path]::GetFullPath((Join-Path $PluginDir $tok)) } catch { continue }
        if ($resolved -eq $CacheDir -or $resolved.StartsWith($CacheDir + $sep)) {
            $key = ($resolved.Substring($CacheDir.Length).TrimStart('\', '/')) -replace '\\', '/'
            if ($claudeOnlySeen.Contains($key)) { continue }
            [void]$claudeOnlySeen.Add($key)
            $claudeOnlyCount++
            if (-not $importSet.Contains($key)) {
                Fail "sanity check failed: CLAUDE.md imports $key but the whole-repo import walk did not find it - an exclusion filter is likely too broad (e.g. matching an ANCESTOR directory of the repo, not just directories inside it)"
            }
        }
    }
}
if ($importPaths.Count -lt $claudeOnlyCount) {
    Fail "sanity check failed: whole-repo import walk found $($importPaths.Count) entries, fewer than CLAUDE.md alone ($claudeOnlyCount) - refusing a short expected set"
}

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
                # bash's `git show ... > file` writes.
                $psi = New-Object System.Diagnostics.ProcessStartInfo
                $psi.FileName = "git"
                $psi.Arguments = "-C `"$VisDir`" show $($sha):$($rel) --"
                $psi.RedirectStandardOutput = $true
                $psi.UseShellExecute = $false
                $gitProc = [System.Diagnostics.Process]::Start($psi)
                $ms2 = New-Object System.IO.MemoryStream
                $gitProc.StandardOutput.BaseStream.CopyTo($ms2)
                $gitProc.WaitForExit()
                if ($gitProc.ExitCode -ne 0) {
                    [Console]::Error.WriteLine("import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ $($tagNames[$idx]) = $sha)")
                    $missing = $true
                    continue
                }
                [System.IO.File]::WriteAllBytes($dest, $ms2.ToArray())
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

    # --- write .vis-lock: MUST be byte-identical to bash's output for the
    # same inputs (modulo resolved_at). ASCII, LF-only, no BOM -- WriteAllText
    # with an explicit "`n"-joined string bypasses Set-Content/Out-File's
    # platform-newline and BOM behavior entirely, which is what caused the
    # original CRLF/culture-sort drift between the two entry points.
    $iso = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("# .vis-lock - auto-generated by scripts/bootstrap.sh")
    $lines.Add("# Do not edit by hand. Run ./scripts/bootstrap.sh to refresh.")
    $lines.Add("lock_version: $LockSchemaVersion")
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
    $content = ($lines -join "`n") + "`n"
    [System.IO.File]::WriteAllText($LockFile, $content, (New-Object System.Text.ASCIIEncoding))

    Write-Output "bootstrapped ($Mode): $($pkgs.Count) packages, $($hashPaths.Count) conduct files"
    Write-Output "materialized: $CacheDir"
    Write-Output "wrote $LockFile"
    exit 0
}

# ============================================================================
# -Verify: re-derive everything from the pin; never trust the cache alone.
# ============================================================================

if (-not (Test-Path $LockFile)) {
    Fail "vis not bootstrapped - run ./scripts/bootstrap.sh"
}

$lockText = [System.IO.File]::ReadAllText($LockFile)
$parsed = ConvertFrom-StrictLock $lockText
$lockTopField = $parsed.TopField
$lockPkgNamesList = $parsed.PkgNames
$lockPkgField = $parsed.PkgField
$lockConductPathsList = $parsed.ConductPaths
$lockConductSha1 = $parsed.ConductSha1

$lockVersionField = $lockTopField['lock_version']
$lockMode = $lockTopField['mode']
if (-not $lockMode -or -not $lockVersionField) {
    Fail "lock is stale or wrong-schema (missing 'mode:' or 'lock_version:') - run ./scripts/bootstrap.sh"
}
if ($lockVersionField -ne $LockSchemaVersion) {
    Fail "lock_version mismatch: lock says $lockVersionField, this bootstrap understands $LockSchemaVersion - run ./scripts/bootstrap.sh to rewrite it, or you are looking at a lock from an incompatible bootstrap version"
}
if ($lockMode -ne $Mode) {
    Fail "lock mode mismatch: lock says $lockMode, verify requested $Mode - re-run bootstrap in that mode first"
}

if (-not (Test-Path $CacheDir)) {
    Fail "vis not bootstrapped - run ./scripts/bootstrap.sh"
}

function Get-SortedUnique([string[]]$arr) {
    $s = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::Ordinal)
    foreach ($x in $arr) { [void]$s.Add($x) }
    $out = New-Object string[] ($s.Count)
    $s.CopyTo($out)
    [Array]::Sort($out, [System.StringComparer]::Ordinal)
    return $out
}

if ($Mode -eq "pinned") {
    # --- exact package-block set: no extra, none missing (the parser already
    # rejected a duplicate block outright) -------------------------------------
    $observedPkgSet = Get-SortedUnique @($lockPkgNamesList)
    $expectedPkgSet = Get-SortedUnique $pkgs
    if (-not (@(Compare-Object $observedPkgSet $expectedPkgSet -SyncWindow 0).Count -eq 0)) {
        [Console]::Error.WriteLine("package block set in lock does not match .vis-versions exactly:")
        [Console]::Error.WriteLine("  lock has: $($observedPkgSet -join ' ')")
        [Console]::Error.WriteLine("  expected: $($expectedPkgSet -join ' ')")
        Fail "  (an extra or unexpected package block is refused just like a missing one)"
    }

    # --- per-package: version, tag, tag_commit ALL re-derived and compared -----
    for ($i = 0; $i -lt $pkgs.Count; $i++) {
        $pkg = $pkgs[$i]
        $expectedVersion = "v$($vers[$i])"
        $expectedTag = $tagNames[$i]
        $expectedCommit = $tagCommits[$i]

        $observedVersion = $lockPkgField["$pkg`:version"]
        $observedTag = $lockPkgField["$pkg`:tag"]
        $observedCommit = $lockPkgField["$pkg`:tag_commit"]

        if (-not $observedVersion -or -not $observedTag -or -not $observedCommit) {
            Fail "package ${pkg}: lock block incomplete (missing version/tag/tag_commit) - run ./scripts/bootstrap.sh"
        }
        if ($observedVersion -ne $expectedVersion) {
            Fail "package ${pkg}: lock 'version:' is $observedVersion, .vis-versions currently declares $expectedVersion - forged field or stale lock. Run ./scripts/bootstrap.sh"
        }
        if ($observedTag -ne $expectedTag) {
            Fail "package ${pkg}: lock 'tag:' is $observedTag, expected $expectedTag - forged field or stale lock. Run ./scripts/bootstrap.sh"
        }
        if ($observedCommit -ne $expectedCommit) {
            Fail "package ${pkg}: recorded tag/version no longer resolves to the same content (lock $observedCommit, tag now resolves to $expectedCommit) - a moved/retagged pin, or .vis-versions changed without re-bootstrapping. Run ./scripts/bootstrap.sh"
        }
    }

    # --- exact conduct_files entry set: no extra, none missing (the parser
    # already rejected a duplicate entry outright) ------------------------------
    $observedFileSet = Get-SortedUnique @($lockConductPathsList)
    $expectedFileSet = Get-SortedUnique $importPaths
    if (-not (@(Compare-Object $observedFileSet $expectedFileSet -SyncWindow 0).Count -eq 0)) {
        [Console]::Error.WriteLine("conduct_files entry set in lock does not match what this repo currently imports:")
        foreach ($p in $observedFileSet) { if ($expectedFileSet -notcontains $p) { [Console]::Error.WriteLine("  unexpected entry in lock (no longer imported): $p") } }
        foreach ($p in $expectedFileSet) { if ($observedFileSet -notcontains $p) { [Console]::Error.WriteLine("  missing from lock (imported but not covered): $p") } }
        Fail "Run ./scripts/bootstrap.sh"
    }

    # --- per-file: re-derive from the pin, compare against lock AND cache ------
    foreach ($rel in $importPaths) {
        if ($rel -notmatch '^packages/([^/]+)/') {
            Fail "import path does not belong to a package/: @.vis-cache/vis/$rel"
        }
        $pkg = $matches[1]
        $idx = Get-PkgIndex $pkg
        if ($idx -lt 0) {
            Fail "import references package '$pkg' not declared in $VersionsFile`: @.vis-cache/vis/$rel"
        }
        $sha = $tagCommits[$idx]

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "git"
        $psi.Arguments = "-C `"$VisDir`" show $($sha):$($rel) --"
        $psi.RedirectStandardOutput = $true
        $psi.UseShellExecute = $false
        $gitProc = [System.Diagnostics.Process]::Start($psi)
        $ms3 = New-Object System.IO.MemoryStream
        $gitProc.StandardOutput.BaseStream.CopyTo($ms3)
        $gitProc.WaitForExit()
        if ($gitProc.ExitCode -ne 0) {
            Fail "import resolves to missing file at pin: @.vis-cache/vis/$rel (package $pkg @ $($tagNames[$idx]) = $sha) - run ./scripts/bootstrap.sh"
        }
        $sha1alg = [System.Security.Cryptography.SHA1]::Create()
        $pinHash = [System.BitConverter]::ToString($sha1alg.ComputeHash($ms3.ToArray())).Replace("-", "").ToLower()

        $lockHash = $lockConductSha1[$rel]
        if (-not $lockHash) { Fail "conduct file not in lock: $rel - run ./scripts/bootstrap.sh" }

        $cacheFile = Join-Path $CacheDir ($rel -replace '/', '\')
        if (-not (Test-Path $cacheFile)) {
            Fail "import resolves to missing file in cache: @.vis-cache/vis/$rel - run ./scripts/bootstrap.sh"
        }
        $cacheHash = (Get-FileHash $cacheFile -Algorithm SHA1).Hash.ToLower()

        if ($pinHash -ne $lockHash) {
            Fail "conduct file ${rel}: lock sha1 ($lockHash) does not match content freshly re-derived from the pinned commit ($pinHash) - forged lock, or the lock (and possibly the cache) came from a different commit. Run ./scripts/bootstrap.sh"
        }
        if ($cacheHash -ne $lockHash) {
            Fail "conduct file $rel modified in the materialized cache since bootstrap ($cacheHash != $lockHash) - re-bootstrap or revert .vis-cache/"
        }
    }
} else {
    # --- floating mode: unchanged from the previous design ---------------------
    $observedFileSet = Get-SortedUnique @($lockConductPathsList)
    $expectedFileSet = Get-SortedUnique $importPaths
    if (-not (@(Compare-Object $observedFileSet $expectedFileSet -SyncWindow 0).Count -eq 0)) {
        Fail "conduct_files entry set in lock does not match what this repo currently imports - run ./scripts/bootstrap.sh -Floating"
    }

    $lockHead = $lockTopField['vis_head']
    $liveHead = (& git -C $VisDir rev-parse HEAD).Trim()
    if ($lockHead -ne $liveHead) {
        Fail "vis drift (floating mode): lock says $lockHead, checkout is $liveHead - run ./scripts/bootstrap.ps1 -Floating to re-resolve"
    }

    foreach ($rel in $importPaths) {
        $full = Join-Path $CacheDir ($rel -replace '/', '\')
        if (-not (Test-Path $full)) {
            Fail "import resolves to missing file in cache: @.vis-cache/vis/$rel - run ./scripts/bootstrap.sh -Floating"
        }
        $observed = (Get-FileHash $full -Algorithm SHA1).Hash.ToLower()
        $expected = $lockConductSha1[$rel]
        if ($observed -ne $expected) {
            Fail "conduct file $rel modified in the materialized cache since bootstrap - re-bootstrap or revert .vis-cache/"
        }
    }
}

# Fail-closed: the number of entries actually verified must equal the
# expected set size, and the expected set itself must be non-trivial (the
# earlier $importPaths sanity checks already refuse empty/short; this
# re-confirms nothing was skipped between enumeration and the loops above).
if ($importPaths.Count -eq 0 -or $lockConductPathsList.Count -ne $importPaths.Count) {
    Fail "verified entry count ($($lockConductPathsList.Count)) does not equal the expected set size ($($importPaths.Count)) - refusing"
}

Write-Output "verified ($Mode): $($importPaths.Count) conduct files, $($pkgs.Count) packages, re-derived from the pin"
exit 0
