[CmdletBinding()]
param(
    [string]$Output = "dist/yunshu-OCR-v1.0.0-source.zip",
    [string]$Prefix = "yunshu-OCR-v1.0.0",
    [string]$Ref = "HEAD"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $repo $Output))
$outputDir = Split-Path -Parent $outputPath

if (-not (Test-Path (Join-Path $repo ".git"))) {
    throw "Not a Git checkout: $repo"
}

$dirty = git -C $repo status --porcelain --untracked-files=no
if ($dirty) {
    throw "Working tree has tracked changes. Commit them before building a source Release."
}

New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
if (Test-Path $outputPath) { Remove-Item -LiteralPath $outputPath -Force }

git -C $repo archive --format=zip --prefix="$Prefix/" --output="$outputPath" $Ref
if ($LASTEXITCODE -ne 0) { throw "git archive failed with exit code $LASTEXITCODE" }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead($outputPath)
try {
    $names = @($zip.Entries | ForEach-Object { $_.FullName })
    $forbidden = @($names | Where-Object {
        $_ -match '(^|/)(tests|tmp|\.pytest_cache|\.ruff_cache)(/|$)' -or
        $_ -match '(^|/)test_[^/]*\.py$' -or
        $_ -match '\.(pdf|pth|pt|onnx|ttf)$' -or
        $_ -match '(^|/)requirements-dev(-lock)?\.txt$' -or
        $_ -match '(^|/)scripts/gen_table_benchmark\.py$'
    })
    if ($forbidden.Count -gt 0) {
        throw "Source Release contains forbidden entries:`n$($forbidden -join "`n")"
    }
}
finally {
    $zip.Dispose()
}

$hash = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $outputPath).Length
Write-Output "source_release=$outputPath"
Write-Output "size=$size"
Write-Output "sha256=$hash"
