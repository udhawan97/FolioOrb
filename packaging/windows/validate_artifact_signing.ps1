$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$required = @{
    AZURE_ARTIFACT_SIGNING_CLIENT_ID = $env:AZURE_ARTIFACT_SIGNING_CLIENT_ID
    AZURE_ARTIFACT_SIGNING_TENANT_ID = $env:AZURE_ARTIFACT_SIGNING_TENANT_ID
    AZURE_ARTIFACT_SIGNING_SUBSCRIPTION_ID = $env:AZURE_ARTIFACT_SIGNING_SUBSCRIPTION_ID
    AZURE_ARTIFACT_SIGNING_ENDPOINT = $env:AZURE_ARTIFACT_SIGNING_ENDPOINT
    AZURE_ARTIFACT_SIGNING_ACCOUNT_NAME = $env:AZURE_ARTIFACT_SIGNING_ACCOUNT_NAME
    AZURE_ARTIFACT_SIGNING_CERTIFICATE_PROFILE_NAME = $env:AZURE_ARTIFACT_SIGNING_CERTIFICATE_PROFILE_NAME
}
$missing = @(
    $required.GetEnumerator() |
        Where-Object { [string]::IsNullOrWhiteSpace([string]$_.Value) } |
        Select-Object -ExpandProperty Key
)
if ($missing.Count -ne 0) {
    throw "Artifact Signing requires all Azure identity and signing profile variables; missing: $($missing -join ', ')."
}

$endpoint = [Uri]$env:AZURE_ARTIFACT_SIGNING_ENDPOINT
if (
    $endpoint.Scheme -ne "https" -or
    $endpoint.Host -notlike "*.codesigning.azure.net" -or
    $endpoint.AbsolutePath -ne "/" -or
    $endpoint.Query -or
    $endpoint.Fragment
) {
    throw "AZURE_ARTIFACT_SIGNING_ENDPOINT must use an HTTPS *.codesigning.azure.net endpoint root."
}
if ([string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNER_SUBJECT)) {
    throw "WINDOWS_SIGNER_SUBJECT must be the exact expected Authenticode subject."
}

Write-Host "Artifact Signing configuration is complete for $($endpoint.Host)."
