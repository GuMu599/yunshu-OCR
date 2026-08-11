param(
    [string]$Output = "tmp/pdf2md-models-v1.zip",
    [string]$Manifest = "models/models.lock.json",
    [string]$SourceRoot = ""
)

$arguments = @(
    "-m", "pdf2md.models", "build-release",
    "--manifest", $Manifest,
    "--output", $Output
)
if ($SourceRoot) {
    $arguments += @("--source-root", $SourceRoot)
}

& python @arguments
exit $LASTEXITCODE
