#Requires -Version 5.1
<#
One-way, explicit-file synchronization. No Git mutations or runtime deletion.
Alternate roots are for isolated tests and must use the same sibling layout.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$SourceRoot = $PSScriptRoot,
    [string]$RuntimeRoot,
    [switch]$PassThru
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NormalPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { throw 'Empty path is not allowed.' }
    $full = [IO.Path]::GetFullPath($Path)
    if ($full.StartsWith('\\')) { throw 'Network paths are not supported.' }
    return $full.TrimEnd([IO.Path]::DirectorySeparatorChar)
}

function Assert-NoReparse([string]$Path) {
    $full = Get-NormalPath $Path
    $drive = [IO.Path]::GetPathRoot($full)
    $current = $drive
    foreach ($part in $full.Substring($drive.Length).Split([IO.Path]::DirectorySeparatorChar)) {
        if (-not $part) { continue }
        $current = Join-Path $current $part
        $pathErrors = @()
        $node = Get-Item -LiteralPath $current -Force -ErrorAction SilentlyContinue -ErrorVariable pathErrors
        if ($null -ne $node) {
            if (($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Reparse point is not allowed in a sync path: $current"
            }
            if (-not $current.Equals($full, [StringComparison]::OrdinalIgnoreCase) -and -not $node.PSIsContainer) {
                throw "Non-directory parent in a sync path: $current"
            }
        }
        elseif (@($pathErrors | Where-Object { $_.CategoryInfo.Category -ne 'ObjectNotFound' }).Count -gt 0) {
            throw "Cannot safely inspect sync path: $current"
        }
    }
}

function Get-ChildPath([string]$Root, [string]$Relative) {
    if ([IO.Path]::IsPathRooted($Relative) -or $Relative.Split([char[]]'/\') -contains '..') {
        throw 'Invalid whitelist entry.'
    }
    $path = Get-NormalPath (Join-Path $Root $Relative)
    if (-not $path.StartsWith($Root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Whitelist path escaped its root.'
    }
    Assert-NoReparse $path
    return $path
}

function Read-Git([string]$Arguments) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = 'git'
    $info.Arguments = "-C `"$SourceRoot`" $Arguments"
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    $info.EnvironmentVariables['GIT_OPTIONAL_LOCKS'] = '0'
    $info.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    try {
        [void]$process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            throw 'Git inspection timed out.'
        }
        $output = $stdout.GetAwaiter().GetResult()
        $errorText = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw "Git inspection failed: $errorText" }
        return $output
    }
    finally { $process.Dispose() }
}

function Get-OptionalHash([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Expected a file: $Path" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

# Deliberately explicit: adding a tracked file alone does not expand deployment.
$mappings = @(
    @{ Name = 'account_order_fixer'; Runtime = 'OAS_account_order_fixer'; Files = @(
        'main.py', 'tests.py', 'tests_mirror.py', 'README.md', '启动.bat'
    ) },
    @{ Name = 'excel_importer'; Runtime = 'OAS_excel_importer'; Files = @(
        'main.py', 'core.py', 'launcher.ps1', '启动.bat', 'README.md',
        'settings.example.json', 'OAS账号导入模板.xlsx', 'tests/test_mirror.py'
    ) },
    @{ Name = 'diagnostic_assistant'; Runtime = 'OAS_diagnostic_assistant'; Files = @(
        'catalog.py', 'main.py', 'models.py', 'parser.py', 'reader.py', 'report.py', 'README.md',
        'tests/test_catalog.py', 'tests/test_diagnostic.py',
        'fixtures/sample_oas/log/2026-10-02_backend.txt',
        'fixtures/sample_oas/log/2026-10-02_badjson.txt',
        'fixtures/sample_oas/log/2026-10-02_crossday.txt',
        'fixtures/sample_oas/log/2026-10-02_demo_alpha.txt',
        'fixtures/sample_oas/log/2026-10-02_demo_beta.txt',
        'fixtures/sample_oas/log/2026-10-02_extra.txt',
        'fixtures/sample_oas/log/2026-10-02_folded.txt',
        'fixtures/sample_oas/log/2026-10-02_logger_ui.txt',
        'fixtures/sample_oas/log/2026-10-02_normal.txt',
        'fixtures/sample_oas/log/2026-10-02_plan.txt',
        'fixtures/sample_oas/log/2026-10-02_taskend.txt',
        'fixtures/sample_oas/log/2026-10-02_truncated.txt',
        'fixtures/sample_oas/log/error/1790928000000/log.txt'
    ) },
    @{ Name = 'click_analyzer'; Runtime = 'OAS_click_analyzer'; Files = @(
        'core.js', 'app.js', 'style.css', 'index.template.html', 'build.js',
        'preview.js', 'test.js', 'validate-local.js', 'README.md', '验证说明.md', '点击分布分析器.html'
    ) }
)

$SourceRoot = Get-NormalPath $SourceRoot
if ([IO.Path]::GetFileName($SourceRoot) -cne 'OAS-Tools') { throw 'Source directory must be named OAS-Tools.' }
Assert-NoReparse $SourceRoot
$expectedRuntime = Get-NormalPath (Join-Path (Split-Path $SourceRoot -Parent) 'scripts/utils')
if (-not $RuntimeRoot) { $RuntimeRoot = $expectedRuntime }
$RuntimeRoot = Get-NormalPath $RuntimeRoot
if (-not $RuntimeRoot.Equals($expectedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Runtime must be the sibling scripts\utils directory: $expectedRuntime"
}
Assert-NoReparse $RuntimeRoot
if (-not (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) { throw 'Runtime directory does not exist.' }
$gitRoot = Get-NormalPath ((Read-Git 'rev-parse --show-toplevel').Trim())
if (-not $gitRoot.Equals($SourceRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Source must be its own Git repository root.' }
$dirty = -not [string]::IsNullOrWhiteSpace((Read-Git 'status --porcelain=v1 --untracked-files=normal'))
$tracked = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($entry in (Read-Git '-c core.quotepath=false ls-files -z').Split([char]0)) {
    if ($entry) { [void]$tracked.Add($entry) }
}

$items = New-Object 'Collections.Generic.List[object]'
$plan = New-Object 'Collections.Generic.List[object]'
$protectedDirectories = @('backup','reports','examples','output','__pycache__','.pytest_cache','.git','.candidate')
foreach ($mapping in $mappings) {
    $sourceTool = Get-ChildPath $SourceRoot ('tools/' + $mapping.Name)
    $runtimeTool = Get-ChildPath $RuntimeRoot $mapping.Runtime
    if ((Test-Path -LiteralPath $sourceTool) -and -not (Test-Path -LiteralPath $sourceTool -PathType Container)) {
        throw "Expected a source tool directory: $sourceTool"
    }
    if (-not (Test-Path -LiteralPath $runtimeTool -PathType Container)) {
        throw "Missing expected tool directory: $($mapping.Runtime)"
    }
    $managed = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($relative in $mapping.Files) {
        $parts = $relative.Split([char[]]'/\')
        if (@($parts | Where-Object { $_ -in $protectedDirectories }).Count -gt 0 -or
            $parts[-1] -eq 'settings.json') { throw 'Local data cannot be added to the sync whitelist.' }
        if (-not $managed.Add($relative)) { throw 'Duplicate whitelist entry.' }
        $source = Get-ChildPath $sourceTool $relative
        $destination = Get-ChildPath $runtimeTool $relative
        $label = $mapping.Name + '/' + $relative
        $sourceHash = Get-OptionalHash $source
        $destinationHash = Get-OptionalHash $destination
        if ($null -eq $sourceHash) {
            $status = if ($null -eq $destinationHash) { 'SKIPPED_MISSING_SOURCE' } else { 'RUNTIME_ONLY' }
        }
        elseif (-not $tracked.Contains('tools/' + $mapping.Name + '/' + $relative)) { $status = 'SKIPPED_NOT_TRACKED' }
        elseif ($null -eq $destinationHash) { $status = 'NEW' }
        elseif ($sourceHash -eq $destinationHash) { $status = 'UNCHANGED' }
        else { $status = 'UPDATE' }
        $items.Add([pscustomobject]@{ Status = $status; Path = $label })
        if ($status -in @('UPDATE','NEW')) {
            $plan.Add([pscustomobject]@{ Source = $source; Destination = $destination; SourceHash = $sourceHash; DestinationHash = $destinationHash })
        }
    }
    # Inventory only the four tool trees; collapse private/cache directories.
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($runtimeTool)
    while ($pending.Count -gt 0) {
        $directory = $pending.Pop()
        foreach ($node in (Get-ChildItem -LiteralPath $directory -Force)) {
            $relative = $node.FullName.Substring($runtimeTool.Length + 1).Replace('\','/')
            if ($managed.Contains($relative)) { continue }
            $label = $mapping.Name + '/' + $relative
            $local = ($node.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0 -or
                ($node.PSIsContainer -and $node.Name -in $protectedDirectories) -or
                (-not $node.PSIsContainer -and ($node.Name -eq 'settings.json' -or
                    $node.Extension -in @('.json','.csv','.log','.pyc','.tmp') -or $node.Name -in @('Thumbs.db','.DS_Store')))
            if ($local) {
                if ($node.PSIsContainer) { $label += '/' }
                $items.Add([pscustomobject]@{ Status = 'SKIPPED_LOCAL_DATA'; Path = $label })
            }
            elseif ($node.PSIsContainer) { $pending.Push($node.FullName) }
            else { $items.Add([pscustomobject]@{ Status = 'RUNTIME_ONLY'; Path = $label }) }
        }
    }
}

$counts = [ordered]@{ UNCHANGED = 0; UPDATE = 0; NEW = 0; RUNTIME_ONLY = 0; SKIPPED = 0 }
foreach ($item in $items) {
    if ($item.Status.StartsWith('SKIPPED')) { $counts.SKIPPED++ }
    else { $counts[$item.Status]++ }
}
Write-Host 'OAS-Tools -> Runtime synchronization'
Write-Host "Source:  $SourceRoot"
Write-Host "Runtime: $RuntimeRoot"
Write-Host $(if ($Apply) { 'APPLY' } else { 'DRY RUN' })
if ($dirty) { Write-Warning 'OAS-Tools working tree is not clean.' }
foreach ($item in $items) { Write-Host "[$($item.Status)] $($item.Path)" }
Write-Host "Files to copy: $($plan.Count)"
Write-Host 'Runtime local files affected: 0'
Write-Host 'Files to delete: 0'
Write-Host ('Counts: ' + (($counts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '))

$copied = 0
if ($Apply) {
    # Revalidate the complete plan before any write, then each file at replacement.
    foreach ($entry in $plan) {
        Assert-NoReparse $entry.Source
        Assert-NoReparse $entry.Destination
        if ((Get-OptionalHash $entry.Source) -ne $entry.SourceHash -or
            (Get-OptionalHash $entry.Destination) -ne $entry.DestinationHash) {
            throw 'A file changed after planning; nothing has been copied. Run dry-run again.'
        }
    }
    foreach ($entry in $plan) {
        Assert-NoReparse $entry.Source
        Assert-NoReparse $entry.Destination
        $parent = Split-Path $entry.Destination -Parent
        [void][IO.Directory]::CreateDirectory($parent)
        Assert-NoReparse $entry.Destination
        $temporary = Join-Path $parent ('.oas-tools-sync-' + [guid]::NewGuid().ToString('N') + '.tmp')
        $ownsTemporary = $false
        try {
            $writer = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            $ownsTemporary = $true
            try {
                $reader = [IO.File]::OpenRead($entry.Source)
                try { $reader.CopyTo($writer) }
                finally { $reader.Dispose() }
            }
            finally { $writer.Dispose() }
            Assert-NoReparse $temporary
            Assert-NoReparse $entry.Destination
            if ((Get-OptionalHash $temporary) -ne $entry.SourceHash -or
                (Get-OptionalHash $entry.Destination) -ne $entry.DestinationHash) {
                throw 'A file changed during copying; its runtime file was not replaced.'
            }
            if ($null -eq $entry.DestinationHash) { [IO.File]::Move($temporary, $entry.Destination) }
            else { [IO.File]::Replace($temporary, $entry.Destination, [NullString]::Value) }
            $copied++
            if ((Get-OptionalHash $entry.Destination) -ne $entry.SourceHash) { throw 'Post-copy SHA256 verification failed.' }
        }
        finally {
            # Only remove this invocation's newly created temporary file.
            if ($ownsTemporary -and (Test-Path -LiteralPath $temporary)) {
                Assert-NoReparse $temporary
                Remove-Item -LiteralPath $temporary -Force
            }
        }
    }
    Write-Host "Copied and verified: $copied. Runtime-only files preserved."
}
else { Write-Host 'No files were modified.' }
if ($PassThru) {
    [pscustomobject]@{ Mode = $(if ($Apply) { 'APPLY' } else { 'DRY_RUN' }); Dirty = $dirty;
        Counts = [pscustomobject]$counts; Copied = $copied; FilesToDelete = 0;
        LocalFilesAffected = 0; Items = $items.ToArray() }
}
