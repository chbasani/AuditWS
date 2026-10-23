"""Offline checks using the actual old accelerator; no Spark or cloud writes."""

import ast
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from zipfile import ZipFile

from fabricontology import generate_definition_from_package
from Create_Ontology_from_package import (
    create_and_verify,
    normalize_definition,
    validate_definition,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
WORKSPACE = "11111111-1111-1111-1111-111111111111"
LAKEHOUSE = "22222222-2222-2222-2222-222222222222"
ITEM = "33333333-3333-3333-3333-333333333333"


def response(body, status=200):
    value = Mock(status_code=status)
    value.json.return_value = body
    return value


class OldPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = json.loads((ROOT / "data" / "expected-validation.json").read_text())
        cls.raw, cls.entities, cls.relationships, cls.bindings, cls.contexts = (
            generate_definition_from_package(
                str(SCRIPTS / "audit_ontology_package.iq"), "OfflineAudit",
                WORKSPACE, LAKEHOUSE, "dbo",
            )
        )
        cls.definition = normalize_definition(cls.raw)

    def test_complete_old_definition_and_order(self):
        validate_definition(self.definition, WORKSPACE, LAKEHOUSE)
        self.assertEqual(len(self.definition["parts"]), 55)
        self.assertFalse(any(p["path"].endswith(".tmdl") for p in self.definition["parts"]))
        self.assertEqual((len(self.entities), len(self.relationships)), (10, 17))
        self.assertEqual((len(self.bindings), len(self.contexts)), (10, 17))

    def test_all_columns_and_primary_keys(self):
        types = {
            "string": "String", "boolean": "Boolean", "date": "DateTime",
            "int": "BigInt", "bigint": "BigInt", "decimal(18,2)": "Double",
        }
        by_id = {entity["id"]: entity for entity in self.entities.values()}
        by_table = {}
        for binding in self.bindings:
            config = binding["dataBinding"]["dataBindingConfiguration"]
            entity = by_id[binding["entityTypeId"]]
            props = {prop["id"]: prop for prop in entity["properties"]}
            mapped = {
                pair["sourceColumnName"]: props[pair["targetPropertyId"]]["valueType"]
                for pair in config["propertyBindings"]
            }
            by_table[config["sourceTableProperties"]["sourceTableName"]] = (entity, mapped)
        self.assertEqual(set(by_table), {t["name"] for t in self.baseline["tables"]})
        for table in self.baseline["tables"]:
            entity, mapped = by_table[table["name"]]
            self.assertEqual(mapped, {c["name"]: types[c["type"]] for c in table["columns"]})
            self.assertEqual(len(entity["entityIdParts"]), 1)

    def test_all_relationship_directions_and_key_bindings(self):
        entities = {e["id"]: e for e in self.entities.values()}
        rels = {r["id"]: r for r in self.relationships}
        entity_table = {
            binding["entityTypeId"]:
                binding["dataBinding"]["dataBindingConfiguration"]["sourceTableProperties"]["sourceTableName"]
            for binding in self.bindings
        }
        actual = []
        for context in self.contexts:
            rel = rels[context["relationshipTypeId"]]
            child_id, parent_id = rel["source"]["entityTypeId"], rel["target"]["entityTypeId"]
            value = context["contextualization"]
            self.assertEqual(value["dataBindingTable"]["sourceTableName"], entity_table[child_id])
            source, target = value["sourceKeyRefBindings"][0], value["targetKeyRefBindings"][0]
            self.assertEqual(source["targetPropertyId"], entities[child_id]["entityIdParts"][0])
            self.assertEqual(target["targetPropertyId"], entities[parent_id]["entityIdParts"][0])
            parent_key = next(
                p["name"] for p in entities[parent_id]["properties"]
                if p["id"] == target["targetPropertyId"]
            )
            actual.append([
                entity_table[child_id], source["sourceColumnName"], target["sourceColumnName"],
                entity_table[parent_id], parent_key, rel["name"],
            ])
        self.assertEqual(sorted(actual), sorted(self.baseline["relationships"]))

    def test_package_is_portable_and_has_exact_generator(self):
        with ZipFile(SCRIPTS / "audit_ontology_package.iq") as archive:
            self.assertEqual(
                archive.read("data/create_audit_data.py"),
                (ROOT / "data" / "create_audit_data.py").read_bytes(),
            )
            for name in ("binding/binding_entity_types.csv", "binding/binding_relationship_types.csv"):
                rows = csv.DictReader(io.StringIO(archive.read(name).decode("utf-8")))
                for row in rows:
                    self.assertEqual(row["WorkspaceId"], "")
                    self.assertEqual(row.get("SourceItemId", row.get("ItemId")), "")
        self.assertEqual(sum(t["rows"] for t in self.baseline["tables"]), 510)

    def test_original_wheel_record_and_license(self):
        with ZipFile(SCRIPTS / "fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl") as archive:
            record = "fabriciq_ontology_accelerator-0.1.0.dist-info/RECORD"
            rows = csv.reader(io.StringIO(archive.read(record).decode("utf-8")))
            for name, digest, size in rows:
                if not digest:
                    continue
                content = archive.read(name)
                actual = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                self.assertEqual(digest, "sha256=" + actual)
                self.assertEqual(len(content), int(size))
            license_text = archive.read(
                "fabriciq_ontology_accelerator-0.1.0.dist-info/licenses/LICENSE"
            ).decode()
            self.assertIn("Copyright (c) 2025 Jomit", license_text)
            self.assertIn("permission notice", license_text)

    def test_notebook_code_matches_source_and_compiles(self):
        for name in ("Generate_ontology_Data", "Create_Ontology_from_package"):
            source = (SCRIPTS / (name + ".py")).read_text(encoding="utf-8")
            ast.parse(source)
            notebook = json.loads((SCRIPTS / (name + ".ipynb")).read_text())
            self.assertEqual(notebook["nbformat"], 4)
            self.assertEqual(notebook["metadata"]["kernelspec"]["name"], "synapse_pyspark")
            code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
            self.assertEqual("".join(code[-1]["source"]), source)
            for cell in code:
                text = "".join(cell["source"])
                if not text.startswith("%pip "):
                    compile(text, name + ".ipynb", "exec")
                self.assertEqual(cell["outputs"], [])
                self.assertIsNone(cell["execution_count"])

    def test_create_waits_and_verifies_saved_definition(self):
        client = Mock()
        client.get.return_value = response({"value": []})
        client.post.side_effect = [
            response({"id": ITEM}, 201), response({"definition": self.definition}),
        ]
        result = create_and_verify(client, WORKSPACE, LAKEHOUSE, "OfflineAudit", self.definition)
        self.assertEqual(result["id"], ITEM)
        self.assertEqual(client.post.call_count, 2)
        for call in client.post.call_args_list:
            self.assertTrue(call.kwargs["lro_wait"])

    def test_duplicate_on_second_page_never_writes(self):
        client = Mock()
        client.get.side_effect = [
            response({"value": [], "continuationToken": "page two"}),
            response({"value": [{"displayName": "OfflineAudit"}]}),
        ]
        with self.assertRaisesRegex(ValueError, "already exists"):
            create_and_verify(client, WORKSPACE, LAKEHOUSE, "OfflineAudit", self.definition)
        client.post.assert_not_called()

    def test_http_202_is_not_success(self):
        client = Mock()
        client.get.return_value = response({"value": []})
        client.post.return_value = response({}, 202)
        with self.assertRaisesRegex(RuntimeError, "not complete"):
            create_and_verify(client, WORKSPACE, LAKEHOUSE, "OfflineAudit", self.definition)

    def test_wrong_saved_binding_is_not_success(self):
        broken = json.loads(json.dumps(self.definition))
        part = next(p for p in broken["parts"] if "/DataBindings/" in p["path"])
        value = json.loads(base64.b64decode(part["payload"]))
        value["dataBindingConfiguration"]["sourceTableProperties"]["itemId"] = ITEM
        part["payload"] = base64.b64encode(json.dumps(value).encode()).decode()
        client = Mock()
        client.get.return_value = response({"value": []})
        client.post.side_effect = [response({"id": ITEM}, 201), response({"definition": broken})]
        with self.assertRaisesRegex(ValueError, "not bound"):
            create_and_verify(client, WORKSPACE, LAKEHOUSE, "OfflineAudit", self.definition)


if __name__ == "__main__":
    unittest.main(verbosity=2)
