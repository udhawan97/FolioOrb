[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedSubject
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$resolved = Resolve-Path -LiteralPath $Path -ErrorAction Stop
if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
    throw "Authenticode target is not a file: $Path"
}
if ([string]::IsNullOrWhiteSpace($ExpectedSubject)) {
    throw "ExpectedSubject must be the exact expected Authenticode signer subject."
}

$signature = Get-AuthenticodeSignature -LiteralPath $resolved
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Signature status is not Valid for ${resolved}: $($signature.Status) — $($signature.StatusMessage)"
}
if ($signature.SignatureType -ne [System.Management.Automation.SignatureType]::Authenticode) {
    throw "Signature is not embedded Authenticode for ${resolved}: $($signature.SignatureType)."
}
if ($null -eq $signature.SignerCertificate) {
    throw "No signer certificate was returned for $resolved."
}
if ($signature.SignerCertificate.Subject -cne $ExpectedSubject) {
    throw "Signer subject '$($signature.SignerCertificate.Subject)' does not match expected subject '$ExpectedSubject'."
}

$codeSigningOid = "1.3.6.1.5.5.7.3.3"
$ekuExtension = $signature.SignerCertificate.Extensions |
    Where-Object { $_.Oid.Value -eq "2.5.29.37" } |
    Select-Object -First 1
if ($null -eq $ekuExtension) {
    throw "Signer certificate has no Enhanced Key Usage extension."
}
$hasCodeSigningEku = $false
foreach ($usage in $ekuExtension.EnhancedKeyUsages) {
    if ($usage.Value -eq $codeSigningOid) {
        $hasCodeSigningEku = $true
        break
    }
}
if (-not $hasCodeSigningEku) {
    throw "Signer certificate does not contain the Code Signing EKU ($codeSigningOid)."
}
if ($null -eq $signature.TimeStamperCertificate) {
    throw "Authenticode signature has no RFC 3161 timestamp certificate."
}

$signTool = Get-Command "signtool.exe" -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty Source -First 1
if (-not $signTool) {
    $sdkRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $signTool = Get-ChildItem -Path $sdkRoot -Filter "signtool.exe" -File -Recurse |
        Where-Object { $_.DirectoryName -like "*\x64" } |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName -First 1
}
if (-not $signTool) {
    throw "signtool.exe was not found; signature verification cannot continue."
}

& $signTool @("verify", "/pa", "/all", "/tw", "/v", $resolved.Path)
if ($LASTEXITCODE -ne 0) {
    throw "signtool verify failed for $resolved with exit code $LASTEXITCODE."
}

Write-Host "Verified Authenticode signer: $($signature.SignerCertificate.Subject)"
Write-Host "Verified timestamp authority: $($signature.TimeStamperCertificate.Subject)"
