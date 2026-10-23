#requires -Version 7.0
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Decode-Part($Part) {
    [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Part.payload)) | ConvertFrom-Json
}
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -File | Where-Object Extension -in '.ps1', '.psm1') {
    $parseErrors = $null
    [Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$null, [ref]$parseErrors) | Out-Null
    Assert ($parseErrors.Count -eq 0) "PowerShell syntax error in $($file.Name): $parseErrors"
}
$expected = Get-Content -Raw -LiteralPath (Join-Path $root 'data\expected-validation.json') | ConvertFrom-Json
Assert ($expected.tables.Count -eq 10) 'Expected 10 tables.'
Assert (($expected.tables.rows | Measure-Object -Sum).Sum -eq 510) 'Expected 510 synthetic rows.'
Assert ($expected.relationships.Count -eq 17) 'Expected 17 declared relationships.'
$workspace = '11111111-1111-1111-1111-111111111111'
$lakehouse = '22222222-2222-2222-2222-222222222222'
$ontologyId = '33333333-3333-3333-3333-333333333333'
$ontologyPath = Join-Path $root 'artifacts\test-ontology.json'
$agentPath = Join-Path $root 'artifacts\test-agent.json'
& (Join-Path $PSScriptRoot 'New-AuditOntology.ps1') -WorkspaceId $workspace -LakehouseId $lakehouse -BuildOnly -OutputPath $ontologyPath
& (Join-Path $PSScriptRoot 'New-AuditDataAgent.ps1') -WorkspaceId $workspace -OntologyId $ontologyId -BuildOnly -OutputPath $agentPath
$request = Get-Content -Raw -LiteralPath $ontologyPath | ConvertFrom-Json
Assert ($request.displayName -ceq 'AuditOntology') 'Ontology name must not be overwritten by a relationship name.'
Assert ($request.definition.parts.Count -eq 55) 'Ontology must contain exactly 55 definition parts.'
$parts = $request.definition.parts
Assert (@($parts | Where-Object path -match '^EntityTypes/[^/]+/definition.json$').Count -eq 10) 'Missing entity definitions.'
Assert (@($parts | Where-Object path -match '/DataBindings/').Count -eq 10) 'Missing Lakehouse bindings.'
Assert (@($parts | Where-Object path -match '^RelationshipTypes/[^/]+/definition.json$').Count -eq 17) 'Missing relationship definitions.'
Assert (@($parts | Where-Object path -match '/Contextualizations/').Count -eq 17) 'Missing relationship contextualizations.'
foreach ($part in $parts) {
    $decoded = Decode-Part $part
    if ($part.path -match '/DataBindings/') {
        $binding = $decoded.dataBindingConfiguration
        Assert (@($binding.PSObject.Properties.Name)[0] -ceq 'dataBindingType') 'dataBindingType must be first.'
        $source = $binding.sourceTableProperties
        Assert (@($source.PSObject.Properties.Name)[0] -ceq 'sourceType') 'sourceType must be first.'
        Assert ($source.workspaceId -eq $workspace -and $source.itemId -eq $lakehouse) 'A binding was not rebound to the supplied IDs.'
        Assert ($source.sourceSchema -ceq 'dbo') 'All demo tables use dbo.'
    }
    if ($part.path -match '/Contextualizations/') {
        $source = $decoded.dataBindingTable
        Assert (@($source.PSObject.Properties.Name)[0] -ceq 'sourceType') 'Context sourceType must be first.'
        Assert ($source.workspaceId -eq $workspace -and $source.itemId -eq $lakehouse) 'A contextualization was not rebound.'
    }
}
$agent = Get-Content -Raw -LiteralPath $agentPath | ConvertFrom-Json
Assert ($agent.displayName -ceq 'AuditDataAgent') 'Unexpected Data Agent name.'
$instructions = Get-Content -Raw -LiteralPath (Join-Path $root 'agent\instructions.txt')
$stage = Decode-Part ($agent.definition.parts | Where-Object path -eq 'Files/Config/draft/stage_config.json')
$source = Decode-Part ($agent.definition.parts | Where-Object path -like '*/ontology.json')
Assert ($stage.aiInstructions -ceq $instructions) 'Instructions were not preserved exactly.'
Assert ($source.artifactId -eq $ontologyId -and $source.workspaceId -eq $workspace) 'Agent ontology IDs were not rebound.'
Assert (@($source.elements | Where-Object is_selected).Count -eq 10) 'Expected 10 selected entity types.'
$recorded = Get-Content -Raw -LiteralPath (Join-Path $root 'examples\verified-agent-results.json') | ConvertFrom-Json
Assert ($recorded.tests.Count -eq 5) 'Expected five recorded live agent tests.'
Assert (@($recorded.tests | Where-Object { -not $_.passed }).Count -eq 0) 'Recorded baseline includes a failed test.'
$actual = $recorded.tests
$answers = $expected.expected_answers
Assert ((($actual[0].actualRows.CustomerId | Sort-Object) -join ',') -ceq (($answers.high_risk_customers.CustomerId | Sort-Object) -join ',')) 'Customer baseline differs.'
foreach ($finding in $answers.open_findings_by_severity) {
    $row = @($actual[1].actualRows | Where-Object Severity -eq $finding.Severity)
    Assert ($row.Count -eq 1) 'Missing severity baseline.'
    Assert ($row[0].FindingCount -eq $finding.FindingCount -and [decimal]$row[0].ExposureAmount -eq [decimal]$finding.ExposureUSD) 'Exposure baseline differs.'
}
Assert ($actual[2].actualRows[0].OverdueInvoiceCount -eq $answers.overdue_unpaid_invoices[0].InvoiceCount -and
    [decimal]$actual[2].actualRows[0].OutstandingBalance -eq [decimal]$answers.overdue_unpaid_invoices[0].OutstandingUSD) 'Invoice baseline differs.'
Assert ($actual[3].actualRows[0].ControlId -eq $answers.failed_control_tests[0].ControlId -and
    $actual[3].actualRows[0].FailedTestCount -eq $answers.failed_control_tests[0].FailedTests -and
    $actual[3].actualRows[0].ExceptionCount -eq $answers.failed_control_tests[0].Exceptions) 'Control baseline differs.'
Assert ($actual[4].actualRows.Count -eq $answers.overdue_remediation.Count) 'Remediation row count differs.'
foreach ($finding in $answers.overdue_remediation) {
    $row = @($actual[4].actualRows | Where-Object FindingId -eq $finding.FindingId)
    Assert ($row.Count -eq 1) 'Missing overdue finding baseline.'
    Assert ($row[0].CustomerId -eq $finding.CustomerId -and $row[0].Severity -eq $finding.Severity -and
        [decimal]$row[0].ExposureAmount -eq [decimal]$finding.ExposureAmount) 'Remediation baseline differs.'
}
Write-Output 'PASS: syntax, 10 tables/510 rows, 55-part ontology, ordered discriminators, ID rebinding, instructions and all five recorded result baselines.'
Write-Output 'No Fabric requests were made. These are offline package checks, not a fresh deployment or live agent evaluation.'
