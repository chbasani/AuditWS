"""Fabric notebook source: create an OLD JSON ontology from the audit IQ package.

Install the adjacent accelerator wheel into the Fabric session first.
Attach auditdata as the default Lakehouse. This script never updates an item.
"""

import base64
import json
from pathlib import Path
from uuid import UUID

PACKAGE_PATH = "/lakehouse/default/Files/audit_ontology_package.iq"
ONTOLOGY_NAME = "AuditOntology_OldFromPackage"
LAKEHOUSE_NAME = "auditdata"


def normalize_definition(definition):
    """Place polymorphic discriminators first, as required by Fabric import."""
    def ordered(value):
        if isinstance(value, list):
            return [ordered(item) for item in value]
        if isinstance(value, dict):
            discriminators = ("dataBindingType", "sourceType")
            keys = [key for key in discriminators if key in value]
            keys.extend(key for key in value if key not in discriminators)
            return {key: ordered(value[key]) for key in keys}
        return value

    parts = []
    for part in definition["parts"]:
        # The accelerator emits incomplete platform metadata. The working
        # old-experience API payload uses definition.json, not .platform.
        if part["path"] == ".platform":
            continue
        if part["payloadType"] != "InlineBase64":
            raise ValueError("Only InlineBase64 JSON ontology parts are supported.")
        payload = json.loads(base64.b64decode(part["payload"], validate=True))
        parts.append({
            "path": part["path"],
            "payload": base64.b64encode(
                json.dumps(ordered(payload), separators=(",", ":")).encode("utf-8")
            ).decode("ascii"),
            "payloadType": "InlineBase64",
        })
    return {"parts": parts}


def validate_definition(definition, workspace_id, lakehouse_id):
    documents = {
        part["path"]: json.loads(base64.b64decode(part["payload"], validate=True))
        for part in definition["parts"]
    }
    if len(documents) != len(definition["parts"]):
        raise ValueError("Duplicate definition parts.")
    entities = {
        path.split("/")[1]: value for path, value in documents.items()
        if path.startswith("EntityTypes/") and path.endswith("/definition.json")
    }
    relationships = {
        path.split("/")[1]: value for path, value in documents.items()
        if path.startswith("RelationshipTypes/") and path.endswith("/definition.json")
    }
    bindings = [v for p, v in documents.items() if "/DataBindings/" in p]
    contexts = [v for p, v in documents.items() if "/Contextualizations/" in p]
    if (len(documents), len(entities), len(relationships), len(bindings), len(contexts)) != (
        55, 10, 17, 10, 17
    ):
        raise ValueError("Expected 55 parts: 10 entities/bindings and 17 relationships/contexts.")
    if documents.get("definition.json") != {}:
        raise ValueError("Expected the old-experience definition.json marker.")
    for value in bindings + contexts:
        if "dataBindingConfiguration" in value:
            config = value["dataBindingConfiguration"]
            if next(iter(config)) != "dataBindingType":
                raise ValueError("dataBindingType must be the first property.")
            source = config["sourceTableProperties"]
        else:
            source = value["dataBindingTable"]
        if next(iter(source)) != "sourceType" or source["sourceType"] != "LakehouseTable":
            raise ValueError("sourceType must be the first property and LakehouseTable.")
        if (source["workspaceId"], source["itemId"], source["sourceSchema"]) != (
            workspace_id, lakehouse_id, "dbo"
        ):
            raise ValueError("A source is not bound to the selected dbo Lakehouse.")
    return documents


def list_ontologies(client, workspace_id):
    path = f"/v1/workspaces/{workspace_id}/ontologies"
    while path:
        response = client.get(path)
        response.raise_for_status()
        page = response.json()
        yield from page["value"]
        token = page.get("continuationToken")
        if token:
            from urllib.parse import urlencode
            path = f"/v1/workspaces/{workspace_id}/ontologies?" + urlencode({
                "continuationToken": token,
            })
        else:
            path = None


def create_and_verify(client, workspace_id, lakehouse_id, ontology_name, definition):
    workspace_id, lakehouse_id = str(UUID(workspace_id)), str(UUID(lakehouse_id))
    if not ontology_name or not ontology_name.strip():
        raise ValueError("A nonempty new ontology name is required.")
    expected = validate_definition(definition, workspace_id, lakehouse_id)
    if any(item["displayName"] == ontology_name for item in list_ontologies(client, workspace_id)):
        raise ValueError(f"{ontology_name} already exists. Choose a fresh name; nothing was changed.")
    response = client.post(
        f"/v1/workspaces/{workspace_id}/ontologies",
        json={"displayName": ontology_name, "definition": definition},
        lro_wait=True,
    )
    response.raise_for_status()
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Creation is not complete: HTTP {response.status_code}")
    item = response.json()
    item_id = str(UUID(item["id"]))
    response = client.post(
        f"/v1/workspaces/{workspace_id}/ontologies/{item_id}/getDefinition", lro_wait=True
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise RuntimeError(f"Definition retrieval is not complete: HTTP {response.status_code}")
    saved = normalize_definition(response.json()["definition"])
    actual = validate_definition(saved, workspace_id, lakehouse_id)
    # The service may add $schema and optional fields; every submitted field
    # still has to persist with its original value.
    def require_subset(wanted, stored, location):
        if isinstance(wanted, dict):
            for key, value in wanted.items():
                if key not in stored:
                    raise RuntimeError(f"Missing saved field: {location}/{key}")
                require_subset(value, stored[key], f"{location}/{key}")
        elif isinstance(wanted, list):
            if len(wanted) != len(stored):
                raise RuntimeError(f"Saved list length differs: {location}")
            for index, (left, right) in enumerate(zip(wanted, stored)):
                require_subset(left, right, f"{location}/{index}")
        elif wanted != stored:
            raise RuntimeError(f"Saved value differs: {location}")
    if set(actual) != set(expected):
        raise RuntimeError("Saved definition paths differ from the submitted definition.")
    for path, document in expected.items():
        require_subset(document, actual[path], path)
    print(f"Created and verified OLD ontology {ontology_name}: {item_id}; 55 parts")
    return item


def main():
    import notebookutils
    import sempy.fabric as fabric
    from fabricontology import generate_definition_from_package

    context = notebookutils.runtime.context
    workspace_id = str(fabric.get_workspace_id())
    lakehouse_id = str(context["defaultLakehouseId"] or "")
    if (
        not lakehouse_id
        or context["defaultLakehouseName"] != LAKEHOUSE_NAME
        or str(context["defaultLakehouseWorkspaceId"]) != workspace_id
    ):
        raise RuntimeError(f"Attach {LAKEHOUSE_NAME} from this workspace as the default Lakehouse.")
    if not Path(PACKAGE_PATH).is_file():
        raise FileNotFoundError(f"Upload audit_ontology_package.iq to {LAKEHOUSE_NAME}/Files.")
    result = generate_definition_from_package(
        ontology_package_path=PACKAGE_PATH,
        ontology_name=ONTOLOGY_NAME,
        binding_workspace_id=workspace_id,
        binding_lakehouse_item_id=lakehouse_id,
        binding_lakehouse_schema_name="dbo",
        namespace="usertypes",
    )
    definition, entities, relationships, bindings, contexts = result
    if (len(entities), len(relationships), len(bindings), len(contexts)) != (10, 17, 10, 17):
        raise ValueError("The package does not contain the complete audit ontology.")
    for binding in bindings:
        source = binding["dataBinding"]["dataBindingConfiguration"]["sourceTableProperties"]
        if not spark.catalog.tableExists("dbo." + source["sourceTableName"]):
            raise RuntimeError("Run Generate_ontology_Data first; a required table is missing.")
    return create_and_verify(
        fabric.FabricRestClient(), workspace_id, lakehouse_id,
        ONTOLOGY_NAME, normalize_definition(definition),
    )


if __name__ == "__main__":
    created_ontology = main()
