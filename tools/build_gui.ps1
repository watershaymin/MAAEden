param(
    [string]$Python = 'python',
    [string]$Proxy = '',
    [string]$Output = '',
    [switch]$Run
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$sourceRoot = Join-Path $repoRoot 'deps/MFAAvalonia'
$publishRoot = Join-Path $repoRoot 'install'
if ($Output) {
    $publishRoot = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $repoRoot $Output }
    $publishRoot = [System.IO.Path]::GetFullPath($publishRoot)
    if ((Test-Path -LiteralPath $publishRoot) -and (Get-ChildItem -LiteralPath $publishRoot -Force)) {
        throw '指定的输出目录必须为空，请为发布构建选择新目录。'
    }
}
$applicationIcon = Join-Path $repoRoot 'assets/logo.ico'
$guiCommit = '4f11c8122de4f43eafc818a368c9956e3b06249c'
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program 失败，退出码 $LASTEXITCODE" }
}
$oldHttpsProxy = $env:HTTPS_PROXY
$oldHttpProxy = $env:HTTP_PROXY
try {
    if ($Proxy) { $env:HTTPS_PROXY = $Proxy; $env:HTTP_PROXY = $Proxy }
    if (Get-Process MFAAvalonia -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $publishRoot 'MFAAvalonia.exe') }) {
        throw '请先关闭此运行包的 GUI，再重新构建。'
    }
    New-Item -ItemType Directory -Force (Join-Path $repoRoot 'deps') | Out-Null
    $gitOptions = @()
    if ($Proxy) { $gitOptions = @('-c', "http.proxy=$Proxy") }
    if (-not (Test-Path (Join-Path $sourceRoot '.git'))) {
        Invoke-Checked git ($gitOptions + @('clone','--depth','1','--branch','v2.16.1','https://github.com/MaaXYZ/MFAAvalonia.git',$sourceRoot))
    }
    $actualCommit = & git -C $sourceRoot rev-parse HEAD
    if ($actualCommit -ne $guiCommit) { throw 'GUI 源码版本与固定版本不符。' }
    if (& git -C $sourceRoot status --porcelain) { throw 'GUI 上游源码有本地改动，请先检查。' }
    $archive = Join-Path $repoRoot 'deps/python-3.12.10-embed-amd64.zip'
    if (-not (Test-Path $archive)) {
        $download = @{ Uri='https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'; OutFile=$archive }
        if ($Proxy) { $download.Proxy = $Proxy }
        Invoke-WebRequest @download
    }
    Invoke-Checked $Python @('-c','import sys; assert sys.version_info[:2] == (3,12), "构建需要 Python 3.12"')
    Invoke-Checked $Python @((Join-Path $PSScriptRoot 'configure.py'))
    Invoke-Checked $Python @('-m','pip','install','--upgrade','--target',(Join-Path $repoRoot 'deps/gui-python-packages'),'-r',(Join-Path $PSScriptRoot 'gui-requirements.txt'))
    $agentPatch = Join-Path $PSScriptRoot 'patches/gui-agent-temp.patch'
    Invoke-Checked git @('-C',$sourceRoot,'apply','--check',$agentPatch)
    Invoke-Checked git @('-C',$sourceRoot,'apply',$agentPatch)
    try {
        Invoke-Checked dotnet @('publish',(Join-Path $sourceRoot 'MFAAvalonia.Desktop/MFAAvalonia.Desktop.csproj'),'-c','Release','-r','win-x64','--self-contained','true','-o',$publishRoot,"-p:ApplicationIcon=$applicationIcon",'-p:Version=2.16.1','-p:FileVersion=2.16.1.0','-p:AssemblyVersion=2.16.1.0','-p:InformationalVersion=2.16.1','--nologo')
    } finally {
        Invoke-Checked git @('-C',$sourceRoot,'apply','--reverse',$agentPatch)
    }
    Invoke-Checked $Python @((Join-Path $PSScriptRoot 'package_gui.py'),'--output',$publishRoot)
    Invoke-Checked (Join-Path $publishRoot 'python/python.exe') @('-X','utf8',(Join-Path $PSScriptRoot 'check_gui_agent.py'),'--package',$publishRoot)
    if ($Run) { Start-Process -FilePath (Join-Path $publishRoot 'MFAAvalonia.exe') -WorkingDirectory $publishRoot }
} finally {
    $env:HTTPS_PROXY = $oldHttpsProxy
    $env:HTTP_PROXY = $oldHttpProxy
}
