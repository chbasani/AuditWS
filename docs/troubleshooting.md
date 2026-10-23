# Troubleshooting

## CapacityNotActive / paused capacity

Resume the capacity assigned to AuditWS and retry after it becomes active. Authentication and tenant settings do not resume capacity.

## FeatureNotAvailable / ontology creation unsupported

Have a Fabric administrator verify ontology preview settings and security-group scope for your user. Confirm workspace/capacity and region support. These were genuine blockers during the original build; repeating the same request did not bypass them.

The old ontology experience may no longer be offered in **New item**. The included API builder intentionally creates that experience to match RetailOnto. If the API no longer supports it, stop and migrate the model to the new experience rather than mixing JSON and TMDL formats.

## Azure CLI login vs browser login

Signing into an external browser does not automatically authenticate Azure CLI, VS Code's Fabric connector, or another browser profile. Use `az login --tenant <tenant-id> --allow-no-subscriptions` for these scripts. A portal hostname such as `msit.powerbi.com` is not itself an Entra tenant ID.

The scripts use the public commercial-cloud API. Check your own tenant and workspace IDs; this repository does not contain the original deployment's IDs.

## Tables not found / dbo schema missing

Attach `auditdata` as the notebook's **default Lakehouse** and use a schema-enabled Lakehouse. Run the full generator successfully before importing the ontology. Confirm all ten `dbo` tables appear after refreshing the explorer.

Schema validation compares Spark `simpleString()` representations because Delta can change nullability metadata during persistence. The generator still validates exact row content, counts, key uniqueness and foreign-key matches.

## HTTP 202 but ontology is empty or disappears

An accepted create is not a completed import. Wait for the Fabric operation to reach **Succeeded** and inspect its result. The original failed imports temporarily exposed an empty ontology, then rolled back the ontology item.

The helper normalizes Microsoft's regional operation Location paths through `https://api.fabric.microsoft.com/v1/operations/<operation-id>`. It reports failure details and does not treat timeout or rollback as success.

Do not rerun a create while an operation is still running. On timeout, query the operation ID shown in the exception and inspect the workspace first.

## ALMOperationImportFailed: metadata property is not first

The original error was:

```text
The metadata property is either not supported by the type or is not
the first property in the deserialized JSON object.
Path: $.dataBindingConfiguration.sourceTableProperties.sourceType
```

Fabric's polymorphic JSON reader expects `sourceType` first in a table-source object and `dataBindingType` first in its configuration object. Plain PowerShell hashtables do not preserve this ordering reliably. The ontology builder uses `[ordered]` objects for all such discriminators, including relationship contextualizations. Do not reserialize the decoded definition parts with an unordered map.

## getDefinition returns 404

Use **POST**, not GET, on the appropriate `/items/<id>/getDefinition` or `/dataAgents/<id>/getDefinition` endpoint. Also check that the item ID still exists after any failed asynchronous import.

## Data Agent shows no data or no source

1. Confirm AuditOntology exists and its saved definition has 10 entities, 10 bindings, 17 relationships and 17 contextualizations.
2. Verify the bindings use your workspace and `auditdata` IDs.
3. Verify the agent's selected source is AuditOntology with all ten entity types.
4. Allow initialization time and retry a simple customer query.
5. Inspect the real query error instead of treating example answers as a fallback.

The exported agent source uses `ontologies/AuditOntology/ontology.json`. A separate hand-authored `datasource.json` is not required for this observed source shape. Routing through the ontology's bound Lakehouse is expected.

## Aggregation / answer mismatch

- Ensure the complete instructions are saved, including `Support group by in GQL`, the aggregation workaround documented for the old experience.
- Use the fixed date **2026-10-22** when comparing the demo baseline.
- Calculate unpaid balances from payments, not just invoice status.
- Filter out Closed findings from open exposure/remediation.
- Compare unique IDs, counts and amounts to [recorded results](../examples/verified-agent-results.json); natural-language phrasing and row ordering may differ.
- Service-managed model/runtime upgrades can change responses. Re-run all five tests after changes.

## Agent works in draft but not published

Publish after configuring the source/instructions and testing. Check the published version, not only the draft. The original published definition included:

```text
Files/Config/publish_info.json
Files/Config/published/stage_config.json
Files/Config/published/ontologies/AuditOntology/ontology.json
```

The demo does not publish to Microsoft 365 Copilot or change sharing permissions.

## Duplicate names and generated backing items

The creation scripts refuse duplicate target names rather than silently updating existing content. Use the IDs returned by successful calls, not a stale item from a failed operation.

Failed imports can leave backing Lakehouses, SQL analytics endpoints and GraphModels. Do not delete by name pattern or bulk-delete workspace items. Identify each failed operation and check references before manually removing only its abandoned resources. Never remove the backing resources for the working ontology.
