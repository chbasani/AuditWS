Set-StrictMode -Version Latest

function Get-FabricHeaders {
    [CmdletBinding()]
    param([string]$TenantId)

    $arguments = @('account', 'get-access-token', '--resource', 'https://api.fabric.microsoft.com', '--output', 'json')
    if ($TenantId) { $arguments += @('--tenant', $TenantId) }
    $token = & az @arguments
    if ($LASTEXITCODE -ne 0) {
        throw 'Fabric authentication failed. Run az login for the target tenant; see README.md.'
    }
    $parsed = ($token -join "`n") | ConvertFrom-Json
    if (-not $parsed.accessToken) { throw 'Azure CLI returned no Fabric access token.' }
    return @{ Authorization = "Bearer $($parsed.accessToken)" }
}

function Invoke-FabricRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ValidateSet('GET', 'POST', 'DELETE')][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][hashtable]$Headers,
        [object]$Body,
        [int]$TimeoutSeconds = 900
    )

    $base = [uri]'https://api.fabric.microsoft.com'
    $uri = [uri]::new($base, $Path)
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne $base.Host) {
        throw "Unexpected Fabric API host: $($uri.Host)"
    }
    $parameters = @{
        Method = $Method
        Uri = $uri.AbsoluteUri
        Headers = $Headers
        SkipHttpErrorCheck = $true
        ErrorAction = 'Stop'
    }
    if ($PSBoundParameters.ContainsKey('Body')) {
        $parameters.ContentType = 'application/json'
        $parameters.Body = ConvertTo-Json -InputObject $Body -Depth 100 -Compress
    }
    $response = Invoke-WebRequest @parameters
    $status = [int]$response.StatusCode
    if ($status -ge 400) { throw "Fabric HTTP $status $Method $Path : $($response.Content)" }
    if ($status -eq 202) {
        $rawLocation = @($response.Headers['Location'])[0]
        if (-not $rawLocation) { throw 'Accepted response did not contain an operation Location.' }
        $location = [uri]::new($base, [string]$rawLocation)
        if ($location.Scheme -ne 'https' -or $location.AbsolutePath -notmatch '^/v1/operations/[0-9a-fA-F-]{36}$') {
            throw "Unexpected operation Location: $location"
        }
        # Regional Location headers use the same operation ID on the public endpoint.
        $operationPath = $location.AbsolutePath
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        Write-Verbose "Waiting for $operationPath"
        do {
            Start-Sleep -Seconds 5
            $operation = Invoke-FabricRequest -Method GET -Path $operationPath -Headers $Headers
            if ($operation.status -in @('Failed', 'Cancelled', 'Canceled')) {
                throw "Fabric operation $operationPath failed: $($operation | ConvertTo-Json -Depth 30 -Compress)"
            }
        } until ($operation.status -eq 'Succeeded' -or (Get-Date) -ge $deadline)
        if ($operation.status -ne 'Succeeded') {
            throw "Timed out waiting for $operationPath. Inspect that operation before retrying a create."
        }
        return Invoke-FabricRequest -Method GET -Path "$operationPath/result" -Headers $Headers
    }
    if ($status -ne 204 -and $response.Content) {
        return $response.Content | ConvertFrom-Json
    }
}

Export-ModuleMember -Function Get-FabricHeaders, Invoke-FabricRequest
