import json
from pyspark.sql import functions as F

queries = {
    "customers": """
        SELECT concat('C',lpad(cast(id AS STRING),3,'0')) CustomerId,
        concat('Synthetic Customer ',id) CustomerName,
        element_at(array('US','UK','CA'),cast(pmod(id-1,3)+1 AS INT)) Country,
        CASE WHEN pmod(id,4)=0 THEN 'High' WHEN pmod(id,3)=0 THEN 'Medium' ELSE 'Low' END RiskRating,
        'USD' ReportingCurrency FROM range(1,13)
    """,
    "accounts": """
        SELECT concat('A',lpad(cast(id AS STRING),3,'0')) AccountId,
        concat('C',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) CustomerId,
        CASE WHEN id<=12 THEN 'Operating' ELSE 'Receivables' END AccountType,
        'USD' Currency, cast(10000+id*750 AS DECIMAL(18,2)) Balance,
        'Active' Status FROM range(1,25)
    """,
    "transactions": """
        SELECT concat('T',lpad(cast(id AS STRING),4,'0')) TransactionId,
        concat('A',lpad(cast(pmod(id-1,24)+1 AS STRING),3,'0')) AccountId,
        concat('C',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) CustomerId,
        date_add(DATE '2026-01-01',cast(pmod(id-1,270) AS INT)) TransactionDate,
        cast(CASE WHEN pmod(id,20)=0 THEN 25000+id*100 ELSE 100+id*13 END AS DECIMAL(18,2)) Amount,
        'USD' Currency, CASE WHEN pmod(id,2)=0 THEN 'Credit' ELSE 'Debit' END Direction,
        CASE WHEN pmod(id,15)=0 THEN 'Manual' ELSE 'Automated' END EntryMethod,
        CASE WHEN pmod(id,20)=0 THEN 'Pending' ELSE 'Approved' END ApprovalStatus,
        CASE WHEN pmod(id,20)=0 THEN 'Synthetic flagged transaction' ELSE 'Synthetic routine transaction' END Description
        FROM range(1,241)
    """,
    "invoices": """
        SELECT concat('I',lpad(cast(id AS STRING),3,'0')) InvoiceId,
        concat('C',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) CustomerId,
        date_add(DATE '2026-06-01',cast(id AS INT)) InvoiceDate,
        date_add(DATE '2026-07-01',cast(id AS INT)) DueDate,
        cast(1000+id*125 AS DECIMAL(18,2)) InvoiceAmount,
        'USD' Currency, CASE WHEN pmod(id,5)=0 THEN 'Unpaid' ELSE 'Paid' END Status
        FROM range(1,61)
    """,
    "payments": """
        SELECT concat('P',lpad(cast(id AS STRING),3,'0')) PaymentId,
        concat('I',lpad(cast(id AS STRING),3,'0')) InvoiceId,
        concat('C',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) CustomerId,
        date_add(DATE '2026-07-01',cast(id AS INT)) PaymentDate,
        cast(1000+id*125 AS DECIMAL(18,2)) PaidAmount,
        'USD' Currency, 'BankTransfer' PaymentMethod
        FROM range(1,61) WHERE pmod(id,5)<>0
    """,
    "audit_engagements": """
        SELECT concat('E',lpad(cast(id AS STRING),3,'0')) EngagementId,
        concat('C',lpad(cast(id AS STRING),3,'0')) CustomerId,
        'FY2026 Financial Customer Audit' EngagementName,
        DATE '2026-01-01' PeriodStart, DATE '2026-09-30' PeriodEnd,
        DATE '2026-10-22' AsOfDate, 'InProgress' Status,
        concat('Synthetic Auditor ',pmod(id-1,3)+1) LeadAuditor
        FROM range(1,13)
    """,
    "controls": """
        SELECT concat('CTL',lpad(cast(id AS STRING),2,'0')) ControlId,
        element_at(array('Payment authorization','Invoice completeness','Account reconciliation',
            'Manual journal review','Customer risk review','Evidence retention'),cast(id AS INT)) ControlName,
        element_at(array('Authorization','Completeness','Accuracy','Authorization','RiskAssessment','Documentation'),cast(id AS INT)) ControlObjective,
        'Monthly' Frequency, concat('Synthetic Control Owner ',id) ControlOwner
        FROM range(1,7)
    """,
    "control_tests": """
        SELECT concat('CT',lpad(cast(id AS STRING),3,'0')) TestId,
        concat('E',lpad(cast(floor((id-1)/6)+1 AS STRING),3,'0')) EngagementId,
        concat('C',lpad(cast(floor((id-1)/6)+1 AS STRING),3,'0')) CustomerId,
        concat('CTL',lpad(cast(pmod(id-1,6)+1 AS STRING),2,'0')) ControlId,
        DATE '2026-10-01' TestDate, 25 SampleSize,
        CASE WHEN pmod(id,6)=0 THEN 3 ELSE 0 END ExceptionCount,
        CASE WHEN pmod(id,6)=0 THEN 'Fail' ELSE 'Pass' END Result
        FROM range(1,73)
    """,
    "findings": """
        SELECT concat('F',lpad(cast(id AS STRING),3,'0')) FindingId,
        concat('CT',lpad(cast(id*6 AS STRING),3,'0')) TestId,
        concat('E',lpad(cast(id AS STRING),3,'0')) EngagementId,
        concat('C',lpad(cast(id AS STRING),3,'0')) CustomerId,
        'CTL06' ControlId,
        concat('Synthetic evidence retention exception for customer ',id) FindingTitle,
        CASE WHEN pmod(id,4)=0 THEN 'High' WHEN pmod(id,3)=0 THEN 'Medium' ELSE 'Low' END Severity,
        CASE WHEN pmod(id,3)=0 THEN 'Closed' ELSE 'Open' END Status,
        cast(id*1500 AS DECIMAL(18,2)) ExposureAmount, 'USD' Currency,
        DATE '2026-10-05' IdentifiedDate,
        CASE WHEN pmod(id,2)=0 THEN DATE '2026-10-15' ELSE DATE '2026-11-15' END RemediationDueDate,
        CASE WHEN pmod(id,3)=0 THEN DATE '2026-10-12' ELSE cast(NULL AS DATE) END ClosedDate,
        concat('Synthetic Remediation Owner ',id) RemediationOwner
        FROM range(1,13)
    """,
    "evidence_documents": """
        SELECT concat('D',lpad(cast(id AS STRING),3,'0')) EvidenceId,
        concat('E',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) EngagementId,
        concat('F',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) FindingId,
        concat('C',lpad(cast(pmod(id-1,12)+1 AS STRING),3,'0')) CustomerId,
        concat('Synthetic evidence document ',id) DocumentTitle,
        CASE WHEN id<=12 THEN 'BankStatement' ELSE 'AuditWorkpaper' END DocumentType,
        CASE WHEN pmod(id,4)=0 THEN 'PendingReview' ELSE 'Verified' END VerificationStatus,
        DATE '2026-10-10' CollectedDate, 'Synthetic - no real customer information' Classification
        FROM range(1,25)
    """
}
expected = dict(zip(queries, [12, 24, 240, 60, 48, 12, 6, 72, 12, 24]))
tables = {}
for name, query in queries.items():
    target = "dbo." + name
    generated = spark.sql(query).withColumn("IsSynthetic", F.lit(True))
    if not spark.catalog.tableExists(target):
        generated.write.format("delta").mode("errorifexists").saveAsTable(target)
    stored = spark.table(target)
    assert stored.schema.simpleString() == generated.schema.simpleString(), (name, "schema mismatch")
    assert stored.count() == expected[name], (name, "row count mismatch")
    assert stored.exceptAll(generated).count() == 0, (name, "unexpected persisted rows")
    tables[name] = stored

relations = [
    ("accounts", "AccountId", "CustomerId", "customers", "CustomerId", "AccountBelongsToCustomer"),
    ("transactions", "TransactionId", "AccountId", "accounts", "AccountId", "TransactionPostedToAccount"),
    ("transactions", "TransactionId", "CustomerId", "customers", "CustomerId", "TransactionForCustomer"),
    ("invoices", "InvoiceId", "CustomerId", "customers", "CustomerId", "InvoiceForCustomer"),
    ("payments", "PaymentId", "InvoiceId", "invoices", "InvoiceId", "PaymentSettlesInvoice"),
    ("payments", "PaymentId", "CustomerId", "customers", "CustomerId", "PaymentFromCustomer"),
    ("audit_engagements", "EngagementId", "CustomerId", "customers", "CustomerId", "EngagementAuditsCustomer"),
    ("control_tests", "TestId", "EngagementId", "audit_engagements", "EngagementId", "TestInEngagement"),
    ("control_tests", "TestId", "ControlId", "controls", "ControlId", "TestEvaluatesControl"),
    ("control_tests", "TestId", "CustomerId", "customers", "CustomerId", "TestForCustomer"),
    ("findings", "FindingId", "TestId", "control_tests", "TestId", "FindingFromTest"),
    ("findings", "FindingId", "EngagementId", "audit_engagements", "EngagementId", "FindingInEngagement"),
    ("findings", "FindingId", "CustomerId", "customers", "CustomerId", "FindingForCustomer"),
    ("findings", "FindingId", "ControlId", "controls", "ControlId", "FindingForControl"),
    ("evidence_documents", "EvidenceId", "EngagementId", "audit_engagements", "EngagementId", "EvidenceForEngagement"),
    ("evidence_documents", "EvidenceId", "FindingId", "findings", "FindingId", "EvidenceSupportsFinding"),
    ("evidence_documents", "EvidenceId", "CustomerId", "customers", "CustomerId", "EvidenceForCustomer")
]
for child, pk, fk, parent, parent_pk, name in relations:
    assert tables[child].join(tables[parent], tables[child][fk] == tables[parent][parent_pk], "left_anti").count() == 0, name
for table, pk in [
    ("customers", "CustomerId"), ("accounts", "AccountId"), ("transactions", "TransactionId"),
    ("invoices", "InvoiceId"), ("payments", "PaymentId"), ("audit_engagements", "EngagementId"),
    ("controls", "ControlId"), ("control_tests", "TestId"), ("findings", "FindingId"),
    ("evidence_documents", "EvidenceId")
]:
    assert tables[table].select(pk).distinct().count() == expected[table], table

checks = {
    "high_risk_customers": "SELECT CustomerId,CustomerName FROM dbo.customers WHERE RiskRating='High' ORDER BY CustomerId",
    "open_findings_by_severity": "SELECT Severity,count(*) FindingCount,sum(ExposureAmount) ExposureUSD FROM dbo.findings WHERE Status='Open' GROUP BY Severity ORDER BY Severity",
    "overdue_unpaid_invoices": """
        WITH paid AS (
            SELECT InvoiceId, sum(PaidAmount) PaidAmount FROM dbo.payments GROUP BY InvoiceId
        ), balances AS (
            SELECT i.InvoiceId, i.DueDate,
                i.InvoiceAmount - coalesce(p.PaidAmount, 0) OutstandingAmount
            FROM dbo.invoices i LEFT JOIN paid p ON i.InvoiceId = p.InvoiceId
        )
        SELECT count(*) InvoiceCount, sum(OutstandingAmount) OutstandingUSD
        FROM balances WHERE DueDate < DATE '2026-10-22' AND OutstandingAmount > 0
    """,
    "failed_control_tests": "SELECT ControlId,count(*) FailedTests,sum(ExceptionCount) Exceptions FROM dbo.control_tests WHERE Result='Fail' GROUP BY ControlId",
    "overdue_remediation": "SELECT FindingId,CustomerId,Severity,ExposureAmount FROM dbo.findings WHERE Status='Open' AND RemediationDueDate<DATE '2026-10-22' ORDER BY FindingId"
}
report = {
    "tables": [{"name": name, "rows": expected[name], "columns": [{"name": f.name, "type": f.dataType.simpleString()} for f in tables[name].schema.fields]} for name in queries],
    "relationships": relations,
    "expected_answers": {name: [row.asDict() for row in spark.sql(query).collect()] for name, query in checks.items()},
    "validation": "10 tables persisted; exact data, unique primary keys and all 17 foreign keys validated"
}
print("AUDIT_VALIDATION_JSON=" + json.dumps(report, default=str))
