# Old-experience audit ontology package and notebooks

These files recreate the **old JSON ontology experience** used by AuditOntology
in AuditWS. They are separate from the newer TMDL helper.

The PowerShell builders, shared module, and offline checks are in
[powershell/](powershell/). Python notebooks and packages remain in this folder.

| File | Purpose |
|---|---|
| [fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl](fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl) | Original, unmodified Retail accelerator wheel, including its MIT license. |
| [audit_ontology_package.iq](audit_ontology_package.iq) | Retail-compatible ZIP package: CSV entity/relationship definitions and bindings for all 10 audit tables, plus the synthetic generator and expected results. |
| [Generate_ontology_Data.ipynb](Generate_ontology_Data.ipynb) | Fabric PySpark notebook creating and exactly validating 10 tables / 510 synthetic rows and all 17 foreign keys. |
| [Create_Ontology_from_package.ipynb](Create_Ontology_from_package.ipynb) | Installs the wheel, builds the old definition, creates a new item and verifies its saved definition. |
| [Generate_ontology_Data.py](Generate_ontology_Data.py) | Python source equivalent of the data notebook. |
| [Create_Ontology_from_package.py](Create_Ontology_from_package.py) | Python source equivalent of the creation notebook; install the wheel first. |
| [Build-OldOntologyPackage.py](Build-OldOntologyPackage.py) | Rebuilds the IQ archive and notebook files from the existing model and generator. |
| [Test-OldOntologyPackage.py](Test-OldOntologyPackage.py) | Offline package, notebook, binding, and mocked REST checks. |

## Step by step in Fabric

A lakehouse 'auditdata' is created first and place the .whl and .iq files in that 'file' location of this lake house.  Execute the Generate_ontology_Data.ipynb and Create_ontology_from_package.ipynb in sequence with 'auditdata' tagged to this notebooks and run all. This should create a demo Ontology for Audit purpose. 

1. Open **AuditWS** and its schema-enabled **auditdata** Lakehouse.
2. Download the `.whl` and `.iq` above and upload both into **auditdata → Files**
   at the root, preserving their filenames. Do not use the new-experience wheel.
3. Import both `.ipynb` files into AuditWS using **Import notebook**. These are
   repository artifacts; publishing them here does not create remote notebooks.
4. Attach **auditdata** as the default Lakehouse for **both** notebooks. Use a
   Fabric PySpark runtime with Semantic Link (`sempy.fabric`), pandas and requests.
5. Run **Generate_ontology_Data** first. It uses the same deterministic generator
   as [the original demo](../data/create_audit_data.py). It creates missing tables
   only, and refuses to overwrite or accept unexpected existing contents.
6. Run **Create_Ontology_from_package**. Its first cell installs the wheel:

   ```python
   %pip install /lakehouse/default/Files/fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl
   ```

   The code resolves the workspace and attached Lakehouse from the notebook
   context, binds all sources to `dbo`, and uses the package at
   `/lakehouse/default/Files/audit_ontology_package.iq`.
7. The default **new** ontology name is `AuditOntology_OldFromPackage`. Change
   `ONTOLOGY_NAME` in the code cell if needed. If that name already exists,
   the notebook stops without modifying it. It does not update the existing
   AuditOntology, AuditOntology_NewExperience, or Data Agent.
8. The final success message requires a completed creation operation and a
   saved-definition check: **55 parts, 10 entities, 10 bindings, 17 relationships,
   17 contextualizations**, preserving submitted values.

Creating a new ontology consumes capacity and requires the relevant preview
settings, workspace permissions, and feature availability. The old experience
displayed a retirement date of **January 31, 2027** when the original demo was
built. These files do not bypass tenant restrictions or retirement.

### Why not call the wheel's REST creation helper?

The original wheel's contextualization dictionaries place `sourceType` after
other keys. This caused the actual Fabric import error documented in the
[troubleshooting guide](../docs/troubleshooting.md). The notebook recursively
puts `sourceType` and `dataBindingType` first, omits the wheel's incomplete
`.platform` part, and uses the built-in authenticated `FabricRestClient` with
`lro_wait=True`. It explicitly rejects an incomplete HTTP 202 result and checks
the persisted definition instead of reporting acceptance as success.

The wheel itself is unmodified. Its embedded MIT notice is preserved:
Copyright (c) 2025 Jomit. Its metadata declares `rdflib`; pandas and requests,
also imported by the package, are available in the Fabric notebook runtime.
For local tests, install those imports if your environment does not have them.

## Rebuild and validate locally

From the repository root:

```powershell
python .\scripts\Build-OldOntologyPackage.py .\scripts\fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl
python -m pip install .\scripts\fabriciq_ontology_accelerator-0.1.0-py3-none-any.whl pandas requests
python .\scripts\Test-OldOntologyPackage.py
pwsh -NoProfile -File .\scripts\powershell\Test-DemoPackage.ps1
```

Local tests exercise the actual accelerator parser and mock cloud writes. They
do not execute Spark or create a new Fabric ontology. The original synthetic
generator and its answers were previously validated live in AuditWS.
