"""Build the audit old-experience IQ and two repository-only notebook artifacts."""

import argparse
import base64
import csv
import io
import json
from pathlib import Path
import shutil
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def csv_text(rows, columns):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def notebook(path, title, intro, source, install=False):
    cells = [{
        "cell_type": "markdown", "metadata": {},
        "source": [f"# {title}\n", "\n", intro + "\n"],
    }]
    if install:
        cells.append({
            "cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
            "source": [
                "%pip install /lakehouse/default/Files/fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl\n"
            ],
        })
    cells.append({
        "cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
        "source": source.splitlines(keepends=True),
    })
    value = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Synapse PySpark", "language": "python", "name": "synapse_pyspark"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4, "nbformat_minor": 4,
    }
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build(wheel):
    wheel = Path(wheel).resolve()
    name = "fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl"
    if wheel.name != name:
        raise ValueError(f"Expected the original Retail accelerator wheel: {name}")
    with ZipFile(wheel) as archive:
        if "fabriciq_ontology_accelerator-0.1.0.dist-info/licenses/LICENSE" not in archive.namelist():
            raise ValueError("The original wheel must retain its license.")
    if wheel != (SCRIPTS / name).resolve():
        shutil.copyfile(wheel, SCRIPTS / name)
    baseline = json.loads((ROOT / "data" / "expected-validation.json").read_text())
    template = json.loads((ROOT / "ontology" / "AuditOntology.template.json").read_text(encoding="utf-8-sig"))
    docs = {
        p["path"]: json.loads(base64.b64decode(p["payload"]))
        for p in template["definition"]["parts"]
    }
    entities = {
        path.split("/")[1]: value for path, value in docs.items()
        if path.startswith("EntityTypes/") and path.endswith("/definition.json")
    }
    entity_rows, binding_rows, table_entities = [], [], {}
    for path, binding in docs.items():
        if "/DataBindings/" not in path:
            continue
        entity = entities[path.split("/")[1]]
        config = binding["dataBindingConfiguration"]
        source = config["sourceTableProperties"]
        table_entities[source["sourceTableName"]] = entity["name"]
        columns = {p["targetPropertyId"]: p["sourceColumnName"] for p in config["propertyBindings"]}
        for prop in entity["properties"]:
            row = {
                "EntityTypeName": entity["name"],
                "PropertyName": prop["name"],
                "PropertyDataType": prop["valueType"],
                "IsIdentifier": str(prop["id"] in entity["entityIdParts"]).upper(),
                "IsDisplayName": str(prop["id"] == entity["displayNamePropertyId"]).upper(),
                "IsTimeseries": "FALSE",
            }
            entity_rows.append(row)
            binding_rows.append({
                **row,
                "SourceTableName": source["sourceTableName"],
                "BindingSourceColumnName": columns[prop["id"]],
                "DataBindingType": "NonTimeSeries",
                "SourceType": "LakehouseTable",
                "TimestampColumnName": "", "ClusterUri": "", "DatabaseName": "",
                "WorkspaceId": "", "SourceItemId": "", "SourceSchema": "dbo",
            })
    relationships, contexts = [], []
    for child, pk, fk, parent, parent_pk, rel_name in baseline["relationships"]:
        row = {
            "RelationshipName": rel_name,
            "SourceEntityTypeName": table_entities[child],
            "TargetEntityTypeName": table_entities[parent],
        }
        relationships.append(row)
        contexts.append({
            **row, "SourceKeyColumnNames": pk, "TargetKeyColumnNames": fk,
            "SourceTableName": child, "WorkspaceId": "", "ItemId": "", "SourceSchema": "dbo",
        })
    definition_columns = list(entity_rows[0])
    relationship_columns = list(relationships[0])
    generator = (ROOT / "data" / "create_audit_data.py").read_text(encoding="utf-8")
    with ZipFile(SCRIPTS / "audit_ontology_package.iq", "w", ZIP_DEFLATED) as archive:
        archive.writestr("definition/entity_types.csv", csv_text(entity_rows, definition_columns))
        archive.writestr("definition/relationship_types.csv", csv_text(relationships, relationship_columns))
        archive.writestr("binding/binding_entity_types.csv", csv_text(binding_rows, list(binding_rows[0])))
        archive.writestr("binding/binding_relationship_types.csv", csv_text(contexts, list(contexts[0])))
        archive.writestr(
            "data/create_audit_data.py", (ROOT / "data" / "create_audit_data.py").read_bytes()
        )
        archive.writestr("data/expected-validation.json", json.dumps(baseline, indent=2) + "\n")
        archive.writestr(
            "README.txt",
            "AuditWS OLD JSON ontology package, compatible with the original Retail accelerator.\n"
            "10 entities, 17 relationships, 10 dbo Lakehouse tables, 510 synthetic rows.\n"
            "Binding workspace/item IDs are intentionally empty; supply them at generation time.\n"
            "Run Generate_ontology_Data then Create_Ontology_from_package in Fabric.\n"
            "Use the notebook's discriminator-order fix and completed-operation verification.\n"
            "This package is not for the new TMDL ontology experience.\n",
        )
    guard = '''"""Fabric PySpark notebook source: create and validate the synthetic auditdata tables."""
import notebookutils
import sempy.fabric as fabric

context = notebookutils.runtime.context
if (
    not context["defaultLakehouseId"]
    or context["defaultLakehouseName"] != "auditdata"
    or str(context["defaultLakehouseWorkspaceId"]) != str(fabric.get_workspace_id())
):
    raise RuntimeError("Attach auditdata from this workspace as the default Lakehouse.")

'''
    data_source = guard + generator
    (SCRIPTS / "Generate_ontology_Data.py").write_text(data_source, encoding="utf-8")
    notebook(
        SCRIPTS / "Generate_ontology_Data.ipynb", "Generate_ontology_Data",
        "Import into AuditWS and attach the schema-enabled auditdata Lakehouse. Creates "
        "10 tables / 510 synthetic rows, validates all rows and 17 foreign keys. Existing "
        "tables are never overwritten; unexpected data causes a visible failure.",
        data_source,
    )
    notebook(
        SCRIPTS / "Create_Ontology_from_package.ipynb", "Create_Ontology_from_package",
        "OLD JSON experience only. Upload the adjacent wheel and audit_ontology_package.iq "
        "to auditdata/Files and attach auditdata as default. Run the data notebook first. "
        "Default new item name: AuditOntology_OldFromPackage. This never updates AuditOntology "
        "or AuditOntology_NewExperience. Preview permissions and active capacity are required.",
        (SCRIPTS / "Create_Ontology_from_package.py").read_text(encoding="utf-8"),
        install=True,
    )
    print("Built old IQ, original licensed wheel, and both .ipynb/.py notebook pairs in scripts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="Path to the original licensed accelerator wheel")
    build(parser.parse_args().wheel)
