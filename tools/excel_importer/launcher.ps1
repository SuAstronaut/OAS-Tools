# OAS 小号 Excel 导入工具 - 便携启动器
# 功能：读取 settings.json 中的 OAS 路径；若无则让用户选择；
#       用 <OAS>\toolkit\python.exe 启动 main.py。不依赖本机任何预装 Python。
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$settingsPath = Join-Path $scriptDir 'settings.json'
$oasPath = ''
$savedOasPath = ''

function Test-OasRoot {
    param([string]$Path)

    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Container)) {
        return $false
    }
    $hasConfig = Test-Path -LiteralPath (Join-Path $Path 'config') -PathType Container
    $hasModule = Test-Path -LiteralPath (Join-Path $Path 'module') -PathType Container
    $hasTasks = Test-Path -LiteralPath (Join-Path $Path 'tasks') -PathType Container
    $hasServer = Test-Path -LiteralPath (Join-Path $Path 'server.py') -PathType Leaf
    $hasGui = Test-Path -LiteralPath (Join-Path $Path 'gui.py') -PathType Leaf
    return $hasConfig -and $hasModule -and $hasTasks -and ($hasServer -or $hasGui)
}

# 1) 尝试从 settings.json 读取已保存的 OAS 路径
if (Test-Path -LiteralPath $settingsPath) {
    try {
        $s = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($s.oas_path) {
            $savedOasPath = [string]$s.oas_path
            if (Test-OasRoot $savedOasPath) {
                $oasPath = $savedOasPath
            }
        }
    } catch { $oasPath = '' }
}

# 2) 没有有效路径 -> 弹窗选择 OAS 根目录
if (-not $oasPath) {
    if ($savedOasPath) {
        Write-Host '已保存的 OAS 路径无效，请重新选择 OAS 根目录。'
    }
    $f = New-Object System.Windows.Forms.FolderBrowserDialog
    $f.Description = '请选择 OAS 根目录（包含 config、module、tasks，及 server.py 或 gui.py）'
    $f.ShowNewFolderButton = $false
    if ($f.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host '已取消。'
        exit 1
    }
    $oasPath = $f.SelectedPath
    if (-not (Test-OasRoot $oasPath)) {
        Write-Host '所选目录不是有效的 OAS 根目录（需要 config、module、tasks，及 server.py 或 gui.py）。'
        Read-Host '按回车键退出'
        exit 1
    }
}

# 3) 验证 toolkit python 存在
$py = Join-Path $oasPath 'toolkit\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    Write-Host ('未找到 OAS toolkit Python：' + $py)
    Read-Host '按回车键退出'
    exit 1
}

# 4) 保存/更新 settings.json（仅路径与位置映射，不含任何账号内容）
$data = [ordered]@{ oas_path = $oasPath; position_mapping = @{} }
if (Test-Path -LiteralPath $settingsPath) {
    try {
        $old = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($old.position_mapping) { $data.position_mapping = $old.position_mapping }
    } catch {}
}
$data | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $settingsPath -Encoding UTF8

# 5) 用 OAS toolkit Python 启动 GUI
$main = Join-Path $scriptDir 'main.py'
& $py $main
if ($LASTEXITCODE -ne 0) {
    Read-Host '程序异常退出，按回车键关闭'
}
