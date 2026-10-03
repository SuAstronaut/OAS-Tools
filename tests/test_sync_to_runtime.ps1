#Requires -Version 5.1
# All fixtures and all Apply calls stay inside a disposable synthetic workspace.
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$scriptUnderTest = Join-Path (Split-Path $PSScriptRoot -Parent) 'sync_to_runtime.ps1'
$tempParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$testRoot = Join-Path $tempParent ('OAS-Tools-sync-tests-' + [guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($testRoot)
$encoding = New-Object Text.UTF8Encoding($false)

function Assert-True([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAIL: $Message" }
}
function Write-Synthetic([string]$Path, [string]$Text) {
    [void][IO.Directory]::CreateDirectory((Split-Path $Path -Parent))
    [IO.File]::WriteAllText($Path, $Text, $encoding)
}
function Invoke-TestGit([string]$Root, [string[]]$GitArguments) {
    $output = & git -C $Root -c core.hooksPath=disabled-test-hooks @GitArguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Synthetic Git command failed: $output" }
}
function New-Workspace([string]$Name) {
    $base = Join-Path $testRoot $Name
    $source = Join-Path $base 'OAS-Tools'
    $runtime = Join-Path $base 'scripts/utils'
    $tools = @(
        @{ Name='account_order_fixer'; Runtime='OAS_account_order_fixer'; File='main.py' },
        @{ Name='excel_importer'; Runtime='OAS_excel_importer'; File='core.py' },
        @{ Name='diagnostic_assistant'; Runtime='OAS_diagnostic_assistant'; File='parser.py' },
        @{ Name='click_analyzer'; Runtime='OAS_click_analyzer'; File='core.js' }
    )
    foreach ($tool in $tools) {
        Write-Synthetic (Join-Path $source ('tools/' + $tool.Name + '/' + $tool.File)) 'SYNTHETIC SOURCE v1'
        Write-Synthetic (Join-Path $runtime ($tool.Runtime + '/' + $tool.File)) 'SYNTHETIC SOURCE v1'
    }
    Invoke-TestGit $source @('init','-b','main')
    Invoke-TestGit $source @('config','core.autocrlf','false')
    Invoke-TestGit $source @('add','--','tools')
    Invoke-TestGit $source @('-c','user.name=Synthetic Test','-c','user.email=synthetic@example.invalid','commit','-m','Synthetic fixture')
    return [pscustomobject]@{ Source=$source; Runtime=$runtime }
}
function Snapshot([string]$Root) {
    return ((Get-ChildItem -LiteralPath $Root -Recurse -Force -File | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Root.Length) + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }) -join "`n")
}
function Run-Sync($Workspace, [switch]$Apply) {
    return & $scriptUnderTest -SourceRoot $Workspace.Source -RuntimeRoot $Workspace.Runtime -Apply:$Apply -PassThru -WarningAction SilentlyContinue
}
function Assert-Rejected($Workspace, [string]$Runtime = $Workspace.Runtime) {
    $before = Snapshot $Workspace.Runtime
    $rejected = $false
    try { $null = & $scriptUnderTest -SourceRoot $Workspace.Source -RuntimeRoot $Runtime -Apply -PassThru -WarningAction SilentlyContinue }
    catch { $rejected = $true }
    Assert-True $rejected 'unsafe Apply must be rejected'
    Assert-True ((Snapshot $Workspace.Runtime) -eq $before) 'rejected Apply must not write any runtime file'
}

try {
    $w = New-Workspace '01 identical'
    $before = Snapshot $w.Runtime
    $result = Run-Sync $w
    Assert-True ($result.Mode -eq 'DRY_RUN' -and $result.Counts.UPDATE -eq 0 -and $result.Counts.NEW -eq 0 -and $result.Counts.UNCHANGED -eq 4) 'Case 1: identical files'
    Assert-True ((Snapshot $w.Runtime) -eq $before) 'Case 1: default does not write'
    Write-Host 'PASS 1: identical files, zero updates'

    $w = New-Workspace '02 hash comparison'
    $source = Join-Path $w.Source 'tools/account_order_fixer/main.py'
    $target = Join-Path $w.Runtime 'OAS_account_order_fixer/main.py'
    Write-Synthetic $source 'SYNTHETIC SOURCE v2'
    (Get-Item -LiteralPath $source).LastWriteTimeUtc = (Get-Item -LiteralPath $target).LastWriteTimeUtc
    $before = Snapshot $w.Runtime
    $result = Run-Sync $w
    Assert-True ($result.Counts.UPDATE -eq 1 -and $result.Copied -eq 0) 'Case 2: SHA256 detects equal-size, equal-time change'
    Assert-True ((Snapshot $w.Runtime) -eq $before) 'Case 2: dry-run preserves target'
    Write-Host 'PASS 2: dry-run detects changed bytes despite identical timestamp'

    $sourceBefore = (Get-FileHash $source).Hash
    $result = Run-Sync $w -Apply
    Assert-True ($result.Copied -eq 1 -and (Get-FileHash $source).Hash -eq $sourceBefore -and
        (Get-FileHash $target).Hash -eq $sourceBefore) 'Case 3: one-way Apply updates runtime and never source'
    Assert-True (@(Get-ChildItem $w.Runtime -Recurse -Force -Filter '.oas-tools-sync-*.tmp').Count -eq 0) 'Case 3: no temporary residue'
    Write-Host 'PASS 3: Apply copies and verifies changed source'

    $w = New-Workspace '04 local data'
    $localPaths = @('OAS_account_order_fixer/backup/private.json','OAS_excel_importer/settings.json',
        'OAS_excel_importer/backup/private.json','OAS_excel_importer/__pycache__/core.pyc',
        'OAS_diagnostic_assistant/reports/private.md','OAS_click_analyzer/examples/private.csv',
        'OAS_click_analyzer/output/private.json','OAS_coop_statistics/keep.txt','OAS_patch_installer/keep.txt','OAS_local_patch/keep.txt')
    foreach ($relative in $localPaths) { Write-Synthetic (Join-Path $w.Runtime $relative) 'SYNTHETIC LOCAL STATE' }
    $localBefore = @{}
    foreach ($relative in $localPaths) { $localBefore[$relative] = (Get-FileHash (Join-Path $w.Runtime $relative)).Hash }
    Write-Synthetic (Join-Path $w.Source 'tools/excel_importer/core.py') 'SYNTHETIC SOURCE v2'
    # Even tracked local-data and unlisted code must never expand the whitelist.
    Write-Synthetic (Join-Path $w.Source 'tools/excel_importer/settings.json') 'SYNTHETIC DO NOT DEPLOY'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/unlisted.py') 'SYNTHETIC UNLISTED'
    Invoke-TestGit $w.Source @('add','--','tools')
    $result = Run-Sync $w -Apply
    Assert-True ($result.Copied -eq 1 -and $result.LocalFilesAffected -eq 0 -and $result.FilesToDelete -eq 0) 'Case 4: only one whitelisted source copied'
    foreach ($relative in $localPaths) { Assert-True ((Get-FileHash (Join-Path $w.Runtime $relative)).Hash -eq $localBefore[$relative]) "Case 4: preserved $relative" }
    Assert-True (-not (Test-Path (Join-Path $w.Runtime 'OAS_account_order_fixer/unlisted.py'))) 'Case 4: tracked unlisted file not deployed'
    Write-Host 'PASS 4: backups, settings, reports, outputs, caches and other tools preserved'

    $w = New-Workspace '05 deleted source'
    Invoke-TestGit $w.Source @('rm','--','tools/account_order_fixer/main.py')
    $before = Snapshot $w.Runtime
    $result = Run-Sync $w -Apply
    Assert-True ($result.Copied -eq 0 -and $result.Counts.RUNTIME_ONLY -eq 1 -and $result.FilesToDelete -eq 0) 'Case 5: source removal has no delete action'
    Assert-True ((Snapshot $w.Runtime) -eq $before) 'Case 5: runtime source remains byte-identical'
    Write-Host 'PASS 5: deleted repository source never deletes runtime file'

    $w = New-Workspace '06 invalid path'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/main.py') 'SYNTHETIC SOURCE v2'
    Assert-Rejected $w (Join-Path $testRoot 'wrong-runtime')
    Remove-Item -LiteralPath (Join-Path $w.Runtime 'OAS_click_analyzer/core.js')
    Remove-Item -LiteralPath (Join-Path $w.Runtime 'OAS_click_analyzer')
    Assert-Rejected $w
    Write-Host 'PASS 6: wrong runtime path and missing tool directory reject Apply'

    $w = New-Workspace '07 dirty source'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/main.py') 'SYNTHETIC SOURCE v2'
    $warnings = @()
    $result = & $scriptUnderTest -SourceRoot $w.Source -RuntimeRoot $w.Runtime -PassThru -WarningVariable warnings -WarningAction SilentlyContinue
    Assert-True ($result.Dirty -and $result.Counts.UPDATE -eq 1) 'Case 7: dirty source allowed'
    Assert-True (($warnings -join ' ') -like '*OAS-Tools working tree is not clean.*') 'Case 7: visible dirty warning'
    Write-Host 'PASS 7: dirty repository warns and dry-run works'

    $w = New-Workspace '08 new tracked file'
    $new = Join-Path $w.Source 'tools/account_order_fixer/tests_mirror.py'
    Write-Synthetic $new 'SYNTHETIC NEW TEST'
    $result = Run-Sync $w -Apply
    Assert-True ($result.Copied -eq 0 -and @($result.Items | Where-Object Status -eq 'SKIPPED_NOT_TRACKED').Count -eq 1) 'Case 8: untracked whitelist file is skipped'
    Invoke-TestGit $w.Source @('add','--','tools/account_order_fixer/tests_mirror.py')
    $result = Run-Sync $w -Apply
    Assert-True ($result.Counts.NEW -eq 1 -and $result.Copied -eq 1) 'Case 8: tracked whitelist NEW file copied'
    Assert-True ((Get-FileHash $new).Hash -eq (Get-FileHash (Join-Path $w.Runtime 'OAS_account_order_fixer/tests_mirror.py')).Hash) 'Case 8: new file SHA256'
    Write-Host 'PASS 8: only explicitly whitelisted and Git-tracked new files deploy'

    $w = New-Workspace '09 preflight'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/main.py') 'SYNTHETIC SOURCE v2'
    Remove-Item -LiteralPath (Join-Path $w.Runtime 'OAS_click_analyzer/core.js')
    [void][IO.Directory]::CreateDirectory((Join-Path $w.Runtime 'OAS_click_analyzer/core.js'))
    Assert-Rejected $w
    Write-Host 'PASS 9: later invalid target stops all writes during preflight'

    $w = New-Workspace '10 git boundary'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/main.py') 'SYNTHETIC SOURCE v2'
    $gitPath = [IO.Path]::GetFullPath((Join-Path $w.Source '.git'))
    Assert-True ($gitPath.StartsWith($testRoot + '\', [StringComparison]::OrdinalIgnoreCase)) 'Case 10: synthetic Git path is confined'
    Remove-Item -LiteralPath $gitPath -Recurse -Force
    Assert-Rejected $w
    Write-Host 'PASS 10: source without its own Git repository rejects Apply'

    $w = New-Workspace '11 invalid parent'
    Write-Synthetic (Join-Path $w.Source 'tools/account_order_fixer/main.py') 'SYNTHETIC SOURCE v2'
    Write-Synthetic (Join-Path $w.Source 'tools/excel_importer/tests/test_mirror.py') 'SYNTHETIC NEW TEST'
    Invoke-TestGit $w.Source @('add','--','tools/excel_importer/tests/test_mirror.py')
    Write-Synthetic (Join-Path $w.Runtime 'OAS_excel_importer/tests') 'SYNTHETIC LOCAL FILE'
    Assert-Rejected $w
    Write-Host 'PASS 11: a file in place of a parent directory rejects all writes'

    Write-Host 'PASS: 11 synthetic sync cases; no production runtime access or writes.'
}
finally {
    # Verify the absolute target before recursively removing our test workspace.
    $cleanup = [IO.Path]::GetFullPath($testRoot)
    if (-not $cleanup.StartsWith($tempParent + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [IO.Path]::GetFileName($cleanup) -notlike 'OAS-Tools-sync-tests-*') {
        throw 'Refusing unsafe test cleanup path.'
    }
    Remove-Item -LiteralPath $cleanup -Recurse -Force
}
