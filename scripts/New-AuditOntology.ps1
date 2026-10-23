#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][guid]$WorkspaceId,
    [Parameter(Mandatory)][guid]$LakehouseId,
    [string]$TenantId,
    [Alias('Name')][string]$OntologyName = 'AuditOntology',
    [switch]$BuildOnly,
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\artifacts\AuditOntology.request.json')
)
$ErrorActionPreference = 'Stop'
$workspaceId = $WorkspaceId.ToString()
$lakehouseId = $LakehouseId.ToString()
$root = Split-Path $PSScriptRoot -Parent
$validation = Get-Content -LiteralPath (Join-Path $root 'data\expected-validation.json') -Raw | ConvertFrom-Json
Import-Module (Join-Path $PSScriptRoot 'FabricApi.psm1') -Force
$base = "https://api.fabric.microsoft.com/v1/workspaces/$workspaceId"
$parts = [System.Collections.Generic.List[object]]::new()
function Add-Part([string]$Path, $Value) {
    $json = ConvertTo-Json -InputObject $Value -Depth 40 -Compress
    $parts.Add(@{path=$Path; payload=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json)); payloadType='InlineBase64'})
}
Add-Part 'definition.json' @{}
$entities = @{}
$names = @{
    customers='Customer'; accounts='Account'; transactions='FinancialTransaction'
    invoices='Invoice'; payments='Payment'; audit_engagements='AuditEngagement'
    controls='AuditControl'; control_tests='ControlTest'; findings='AuditFinding'
    evidence_documents='EvidenceDocument'
}
$primaryKeys = @{
    customers='CustomerId'; accounts='AccountId'; transactions='TransactionId'
    invoices='InvoiceId'; payments='PaymentId'; audit_engagements='EngagementId'
    controls='ControlId'; control_tests='TestId'; findings='FindingId'; evidence_documents='EvidenceId'
}
$i = 0
foreach ($table in $validation.tables) {
    $i++
    $entityId = [string](1000 + $i)
    $properties = [System.Collections.Generic.List[object]]::new()
    $bindings = [System.Collections.Generic.List[object]]::new()
    $propertyIds = @{}
    $j = 0
    foreach ($column in $table.columns) {
        $j++
        $propertyId = [string](100000 + $i * 100 + $j)
        $propertyIds[$column.name] = $propertyId
        $valueType = switch -Regex ($column.type) {
            '^string$' {'String'; break}
            '^boolean$' {'Boolean'; break}
            '^(date|timestamp)' {'DateTime'; break}
            '^(int|bigint|smallint|tinyint|long)' {'BigInt'; break}
            '^(decimal|double|float)' {'Double'; break}
            default {throw "Unsupported ontology column type: $($column.type)"}
        }
        $properties.Add(@{id=$propertyId; name=$column.name; redefines=$null; baseTypeNamespaceType=$null; valueType=$valueType})
        $bindings.Add(@{sourceColumnName=$column.name; targetPropertyId=$propertyId})
    }
    $key = $propertyIds[$primaryKeys[$table.name]]
    $display = if ($table.name -eq 'customers') {$propertyIds['CustomerName']} else {$key}
    Add-Part "EntityTypes/$entityId/definition.json" @{
        '$schema'='https://developer.microsoft.com/json-schemas/fabric/item/ontology/entityType/1.0.0/schema.json'
        id=$entityId; namespace='usertypes'; baseEntityTypeId=$null; name=$names[$table.name]
        entityIdParts=@($key); displayNamePropertyId=$display; namespaceType='Custom'; visibility='Visible'
        properties=$properties.ToArray(); timeseriesProperties=@(); untypedProperties=@()
    }
    $bindingId = [guid]::NewGuid().ToString()
    Add-Part "EntityTypes/$entityId/DataBindings/$bindingId.json" @{
        '$schema'='https://developer.microsoft.com/json-schemas/fabric/item/ontology/dataBinding/1.0.0/schema.json'
        id=$bindingId
        dataBindingConfiguration=[ordered]@{
            dataBindingType='NonTimeSeries'; propertyBindings=$bindings.ToArray()
            sourceTableProperties=[ordered]@{sourceType='LakehouseTable'; workspaceId=$workspaceId; itemId=$lakehouseId; sourceTableName=$table.name; sourceSchema='dbo'}
        }
    }
    $entities[$table.name] = @{id=$entityId; properties=$propertyIds}
}
$i = 0
foreach ($relation in $validation.relationships) {
    $i++
    $child, $pk, $fk, $parent, $parentPk, $name = $relation
    $relationshipId = [string](2000 + $i)
    Add-Part "RelationshipTypes/$relationshipId/definition.json" @{
        '$schema'='https://developer.microsoft.com/json-schemas/fabric/item/ontology/relationshipType/1.0.0/schema.json'
        namespace='usertypes'; id=$relationshipId; name=$name; namespaceType='Custom'
        source=@{entityTypeId=$entities[$child].id}; target=@{entityTypeId=$entities[$parent].id}
    }
    $contextId = [guid]::NewGuid().ToString()
    Add-Part "RelationshipTypes/$relationshipId/Contextualizations/$contextId.json" @{
        '$schema'='https://developer.microsoft.com/json-schemas/fabric/item/ontology/contextualization/1.0.0/schema.json'
        id=$contextId
        dataBindingTable=[ordered]@{sourceType='LakehouseTable'; workspaceId=$workspaceId; itemId=$lakehouseId; sourceTableName=$child; sourceSchema='dbo'}
        sourceKeyRefBindings=@(@{sourceColumnName=$pk; targetPropertyId=$entities[$child].properties[$pk]})
        targetKeyRefBindings=@(@{sourceColumnName=$fk; targetPropertyId=$entities[$parent].properties[$parentPk]})
    }
}
$body = @{
    displayName=$OntologyName
    type='Ontology'
    description='Synthetic financial customer audit domain: 10 Lakehouse-bound entity types and 17 relationships. Reporting currency USD; audit as-of 2026-10-22. No real customer data.'
    definition=@{parts=$parts.ToArray()}
}
$outputDirectory = Split-Path ([IO.Path]::GetFullPath($OutputPath)) -Parent
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$body | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Output "Entity types: $($entities.Count); relationships: $($validation.relationships.Count); parts: $($parts.Count)"
if ($BuildOnly) { return }
$headers = Get-FabricHeaders -TenantId $TenantId
# Query by type/name to detect duplicates without depending on list pagination.
$existing = Invoke-FabricRequest -Method GET -Path "$base/ontologies" -Headers $headers
do {
    if (@($existing.value | Where-Object displayName -eq $OntologyName).Count -gt 0) {
        throw "$OntologyName already exists. Inspect it before creating or updating."
    }
    $next = $existing.continuationUri
    if ($next) { $existing = Invoke-FabricRequest -Method GET -Path $next -Headers $headers }
} while ($next)
$item = Invoke-FabricRequest -Method POST -Path "$base/ontologies" -Headers $headers -Body $body
$item | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath (Join-Path $outputDirectory 'ontology-item.json') -Encoding utf8
$verified = Invoke-FabricRequest -Method POST -Path "$base/items/$($item.id)/getDefinition" -Headers $headers
$verified | ConvertTo-Json -Depth 80 | Set-Content -LiteralPath (Join-Path $outputDirectory 'ontology-definition.json') -Encoding utf8
$paths = @($verified.definition.parts.path)
if (@($paths | Where-Object { $_ -match '^EntityTypes/[^/]+/definition.json$' }).Count -ne 10 -or
    @($paths | Where-Object { $_ -match '/DataBindings/' }).Count -ne 10 -or
    @($paths | Where-Object { $_ -match '^RelationshipTypes/[^/]+/definition.json$' }).Count -ne 17 -or
    @($paths | Where-Object { $_ -match '/Contextualizations/' }).Count -ne 17) {
    throw 'Created ontology did not persist all 10 entities/bindings and 17 relationships/contextualizations.'
}
Write-Output ($item | ConvertTo-Json -Depth 10)
Write-Output 'Verified persisted ontology definition.'
