#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$WorkspaceId,
    [Parameter(Mandatory)][guid]$OntologyId,
    [string]$TenantId,
    [switch]$BuildOnly,
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\artifacts\AuditDataAgent.request.json')
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force
$root = Split-Path $PSScriptRoot -Parent
$validation = Get-Content -Raw -LiteralPath (Join-Path $root 'data\expected-validation.json') | ConvertFrom-Json
$instructions = Get-Content -Raw -LiteralPath (Join-Path $root 'agent\instructions.txt')
$entityNames = @{
    customers='Customer'; accounts='Account'; transactions='FinancialTransaction'
    invoices='Invoice'; payments='Payment'; audit_engagements='AuditEngagement'
    controls='AuditControl'; control_tests='ControlTest'; findings='AuditFinding'
    evidence_documents='EvidenceDocument'
}
$elements = @(
    foreach ($table in $validation.tables) {
        $entityName = $entityNames[$table.name]
        @{
            id = $entityName
            is_selected = $true
            display_name = $entityName
            type = 'ontology.entity'
            description = $table.columns.name -join ','
            children = @()
        }
    }
)
$parts = [Collections.Generic.List[object]]::new()
function Add-Part([string]$Path, [object]$Value) {
    $json = ConvertTo-Json -InputObject $Value -Depth 50 -Compress
    $parts.Add(@{
        path = $Path
        payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
        payloadType = 'InlineBase64'
    })
}
Add-Part 'Files/Config/data_agent.json' @{
    '$schema' = 'https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataAgent/2.1.0/schema.json'
}
Add-Part 'Files/Config/draft/stage_config.json' @{
    '$schema' = 'https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/stageConfiguration/1.0.0/schema.json'
    aiInstructions = $instructions
}
# This is the ontology source shape exported from the working Fabric UI.
Add-Part 'Files/Config/draft/ontologies/AuditOntology/ontology.json' @{
    '$schema' = 'https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/ontology/1.0.0/schema.json'
    artifactId = $OntologyId.ToString()
    workspaceId = $WorkspaceId.ToString()
    displayName = 'AuditOntology'
    elements = $elements
    entitiesWithUserAuthoredDescriptions = @()
}
$body = @{
    displayName = 'AuditDataAgent'
    description = 'Synthetic financial customer audit assistant grounded in AuditOntology.'
    definition = @{ parts = $parts.ToArray() }
}
$outputDirectory = Split-Path ([IO.Path]::GetFullPath($OutputPath)) -Parent
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$body | ConvertTo-Json -Depth 80 | Set-Content -LiteralPath $OutputPath -Encoding utf8
if ($BuildOnly) {
    Write-Output 'Built draft Data Agent request with 10 selected ontology entities and audit instructions.'
    return
}
$headers = Get-FabricHeaders -TenantId $TenantId
$base = "/v1/workspaces/$WorkspaceId"
$source = Invoke-FabricRequest -Method GET -Path "$base/ontologies/$OntologyId" -Headers $headers
if ($source.displayName -ne 'AuditOntology') {
    throw 'This demo expects an ontology named AuditOntology. Check the supplied OntologyId.'
}
$items = Invoke-FabricRequest -Method GET -Path "$base/dataAgents" -Headers $headers
do {
    if (@($items.value | Where-Object displayName -eq 'AuditDataAgent').Count) {
        throw 'AuditDataAgent already exists. Inspect it before creating or updating.'
    }
    $next = $items.continuationUri
    if ($next) { $items = Invoke-FabricRequest -Method GET -Path $next -Headers $headers }
} while ($next)
$item = Invoke-FabricRequest -Method POST -Path "$base/dataAgents" -Headers $headers -Body $body
$item | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $outputDirectory 'agent-item.json') -Encoding utf8
$verified = Invoke-FabricRequest -Method POST -Path "$base/dataAgents/$($item.id)/getDefinition" -Headers $headers
$verified | ConvertTo-Json -Depth 80 | Set-Content -LiteralPath (Join-Path $outputDirectory 'agent-definition.json') -Encoding utf8
$savedStage = @($verified.definition.parts | Where-Object path -eq 'Files/Config/draft/stage_config.json')
$savedSource = @($verified.definition.parts | Where-Object path -eq 'Files/Config/draft/ontologies/AuditOntology/ontology.json')
if ($savedStage.Count -ne 1 -or $savedSource.Count -ne 1) { throw 'Agent definition is missing its draft instructions or ontology source.' }
$stage = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($savedStage[0].payload)) | ConvertFrom-Json
$ontology = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($savedSource[0].payload)) | ConvertFrom-Json
if ($stage.aiInstructions -cne $instructions -or $ontology.artifactId -ne $OntologyId.ToString() -or
    @($ontology.elements | Where-Object is_selected).Count -ne 10) {
    throw 'Saved Data Agent instructions or ontology source do not match the requested configuration.'
}
$item | ConvertTo-Json -Depth 10
Write-Output 'Verified draft configuration. Run the five examples and publish in the Fabric UI; see README.md.'
