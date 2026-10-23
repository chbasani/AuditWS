-- Spark SQL: run in a Fabric notebook attached to the auditdata Lakehouse.

SELECT CustomerId, CustomerName
FROM dbo.customers WHERE RiskRating = 'High' ORDER BY CustomerId;

SELECT Severity, count(*) FindingCount, sum(ExposureAmount) ExposureUSD
FROM dbo.findings WHERE Status = 'Open' GROUP BY Severity ORDER BY Severity;

WITH paid AS (
    SELECT InvoiceId, sum(PaidAmount) PaidAmount FROM dbo.payments GROUP BY InvoiceId
), balances AS (
    SELECT i.InvoiceId, i.DueDate,
        i.InvoiceAmount - coalesce(p.PaidAmount, 0) OutstandingAmount
    FROM dbo.invoices i LEFT JOIN paid p ON i.InvoiceId = p.InvoiceId
)
SELECT count(*) InvoiceCount, sum(OutstandingAmount) OutstandingUSD
FROM balances WHERE DueDate < DATE '2026-10-22' AND OutstandingAmount > 0;

SELECT ControlId, count(*) FailedTests, sum(ExceptionCount) Exceptions
FROM dbo.control_tests WHERE Result = 'Fail' GROUP BY ControlId;

SELECT FindingId, CustomerId, Severity, ExposureAmount
FROM dbo.findings WHERE Status = 'Open'
    AND RemediationDueDate < DATE '2026-10-22'
ORDER BY FindingId;
