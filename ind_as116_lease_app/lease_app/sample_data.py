"""Demonstration portfolio covering the Phase 1 scenarios.

L0001  Mumbai store      - percentage escalation (5 % every year), monthly advance
L0002  Pune office       - absolute escalation (+Rs 12,500 every year), quarterly advance
L0003  Bhiwandi warehouse- both methods (absolute then percentage), 3-month rent-free,
                           mid-month commencement, monthly arrears
L0004  Bengaluru store   - additional security deposit during the lease (April 2027)
L0005  Delhi store       - lease modification (extension + revised rent + revised IBR) April 2027
L0006  Chennai store     - full termination effective 1 April 2027 + deposit refund April 2027
L0007  Hyderabad kiosk   - new lease commencing April 2027 with IDC, incentive, restoration,
                           quarterly arrears
L0008  Noida office      - partial termination (40 % area surrendered) April 2027
"""
from __future__ import annotations

from .db.repository import Repository

COMMON = {"entity": "ABC Retail Pvt Ltd", "lease_status": "Active", "gst_rate": "0", "non_lease_monthly": "0",
          "rent_free_months": "0", "prepaid_lease_rentals": "0", "initial_direct_costs": "0",
          "lease_incentives": "0", "restoration_provision": "0", "other_initial_adjustments": "0"}

LEASES = [
    dict(lease_id="L0001", agreement_no="AGR/MUM/2025/001", landlord_name="Shree Estates LLP", location="Mumbai - Andheri",
         address="Shop 12, Link Road, Andheri West, Mumbai", lease_category="Retail store",
         agreement_start_date="2025-03-01", commencement_date="2025-04-01", lease_end_date="2034-03-31",
         renewal_option="Renewable for 5 years at mutual consent (not reasonably certain)",
         termination_option="Lessee lock-in 3 years", payment_frequency="Monthly", payment_timing="Advance",
         monthly_rent="100000", security_deposit="600000", discount_rate="9", remarks="5% escalation every year"),
    dict(lease_id="L0002", agreement_no="AGR/PUN/2025/002", landlord_name="Kalyani Properties", location="Pune - Baner",
         address="3rd Floor, Baner Business Park, Pune", lease_category="Office",
         agreement_start_date="2025-06-15", commencement_date="2025-07-01", lease_end_date="2030-06-30",
         payment_frequency="Quarterly", payment_timing="Advance", monthly_rent="250000", security_deposit="750000",
         discount_rate="9.5", gst_rate="18", remarks="Absolute escalation Rs 12,500 p.m. every year; GST tracked"),
    dict(lease_id="L0003", agreement_no="AGR/BHW/2025/003", landlord_name="Bhiwandi Logistics Parks", location="Bhiwandi - Warehouse",
         address="Survey No 45, Bhiwandi, Thane", lease_category="Warehouse",
         agreement_start_date="2025-10-01", commencement_date="2025-10-15", lease_end_date="2035-10-14",
         payment_frequency="Monthly", payment_timing="Arrears", monthly_rent="180000", security_deposit="1080000",
         discount_rate="10", rent_free_months="3", non_lease_monthly="15000",
         remarks="3 months rent free; +Rs 10,000 yearly to Oct-2028, then 15% every 3 years"),
    dict(lease_id="L0004", agreement_no="AGR/BLR/2026/004", landlord_name="Prestige Mall Mgmt", location="Bengaluru - Whitefield",
         address="Unit G-14, Whitefield Mall, Bengaluru", lease_category="Retail store",
         agreement_start_date="2025-12-01", commencement_date="2026-01-01", lease_end_date="2032-12-31",
         payment_frequency="Monthly", payment_timing="Advance", monthly_rent="120000", security_deposit="360000",
         discount_rate="9", remarks="Additional deposit Rs 1,20,000 paid Apr-2027"),
    dict(lease_id="L0005", agreement_no="AGR/DEL/2025/005", landlord_name="DLF Commercial", location="Delhi - Saket",
         address="Shop 5, Select City Walk, Saket, New Delhi", lease_category="Retail store",
         agreement_start_date="2025-03-15", commencement_date="2025-04-01", lease_end_date="2030-03-31",
         payment_frequency="Monthly", payment_timing="Advance", monthly_rent="150000", security_deposit="900000",
         discount_rate="9", remarks="Extended to Mar-2033 w.e.f. 1-Apr-2027"),
    dict(lease_id="L0006", agreement_no="AGR/CHE/2024/006", landlord_name="Express Avenue Realty", location="Chennai - Royapettah",
         address="Shop 21, Express Avenue, Chennai", lease_category="Retail store",
         agreement_start_date="2024-05-15", commencement_date="2024-06-01", lease_end_date="2031-05-31",
         payment_frequency="Monthly", payment_timing="Advance", monthly_rent="90000", security_deposit="270000",
         discount_rate="8.5", remarks="Terminated w.e.f. 1-Apr-2027"),
    dict(lease_id="L0007", agreement_no="AGR/HYD/2027/007", landlord_name="Inorbit Malls", location="Hyderabad - Hitech City",
         address="Kiosk K-3, Inorbit Mall, Hyderabad", lease_category="Retail store",
         agreement_start_date="2027-03-10", commencement_date="2027-04-01", lease_end_date="2030-03-31",
         payment_frequency="Quarterly", payment_timing="Arrears", monthly_rent="60000", security_deposit="180000",
         discount_rate="9.25", initial_direct_costs="50000", lease_incentives="25000",
         restoration_provision="100000", remarks="New lease Apr-2027"),
    dict(lease_id="L0008", agreement_no="AGR/NOI/2025/008", landlord_name="Logix Infotech Park", location="Noida - Sector 62",
         address="Tower B, 5th floor, Sector 62, Noida", lease_category="Office",
         agreement_start_date="2025-03-20", commencement_date="2025-04-01", lease_end_date="2032-03-31",
         payment_frequency="Monthly", payment_timing="Advance", monthly_rent="300000", security_deposit="1800000",
         discount_rate="9", remarks="40% area surrendered w.e.f. 1-Apr-2027"),
]

ESCALATIONS = [
    dict(lease_id="L0001", effective_date="2026-04-01", escalation_type="Percentage", escalation_pct="5",
         frequency_months="12", remarks="5% p.a. compounding", agreement_ref="Clause 4.2"),
    dict(lease_id="L0002", effective_date="2026-07-01", escalation_type="Absolute Amount", escalation_amount="12500",
         frequency_months="12", remarks="Rs 12,500 p.m. increase every year", agreement_ref="Clause 5.1"),
    dict(lease_id="L0003", effective_date="2026-10-15", escalation_type="Absolute Amount", escalation_amount="10000",
         frequency_months="12", remarks="Rs 10,000 p.m. yearly until Oct-2028", agreement_ref="Clause 6.1(a)"),
    dict(lease_id="L0003", effective_date="2028-10-15", escalation_type="Percentage", escalation_pct="15",
         frequency_months="36", remarks="15% every 3 years from Oct-2028", agreement_ref="Clause 6.1(b)"),
    dict(lease_id="L0004", effective_date="2027-01-01", escalation_type="Percentage", escalation_pct="5",
         frequency_months="12", agreement_ref="Clause 3"),
    dict(lease_id="L0005", effective_date="2026-04-01", escalation_type="Percentage", escalation_pct="6",
         frequency_months="12", agreement_ref="Clause 4"),
    dict(lease_id="L0006", effective_date="2025-06-01", escalation_type="Percentage", escalation_pct="5",
         frequency_months="12", agreement_ref="Clause 4"),
    dict(lease_id="L0007", effective_date="2028-04-01", escalation_type="Percentage", escalation_pct="4",
         frequency_months="12", agreement_ref="Clause 7"),
    dict(lease_id="L0008", effective_date="2026-04-01", escalation_type="Percentage", escalation_pct="5",
         frequency_months="12", agreement_ref="Clause 4"),
]

DEPOSITS = [
    dict(deposit_ref="SD-L0001-01", lease_id="L0001", movement_type="Original", movement_date="2025-04-01", amount="600000"),
    dict(deposit_ref="SD-L0002-01", lease_id="L0002", movement_type="Original", movement_date="2025-07-01", amount="750000"),
    dict(deposit_ref="SD-L0003-01", lease_id="L0003", movement_type="Original", movement_date="2025-10-01",
         amount="1080000", remarks="Paid before commencement"),
    dict(deposit_ref="SD-L0004-01", lease_id="L0004", movement_type="Original", movement_date="2026-01-01", amount="360000"),
    dict(deposit_ref="SD-L0004-02", lease_id="L0004", movement_type="Addition", movement_date="2027-04-01",
         amount="120000", supporting_document="Addendum-1 dated 15-Mar-2027",
         remarks="Additional deposit on renewal of fit-out approval - not a lease modification"),
    dict(deposit_ref="SD-L0005-01", lease_id="L0005", movement_type="Original", movement_date="2025-04-01", amount="900000"),
    dict(deposit_ref="SD-L0006-01", lease_id="L0006", movement_type="Original", movement_date="2024-06-01", amount="270000"),
    dict(deposit_ref="SD-L0006-R1", lease_id="L0006", movement_type="Refund", movement_date="2027-04-30",
         amount="270000", remarks="Full refund on termination"),
    dict(deposit_ref="SD-L0007-01", lease_id="L0007", movement_type="Original", movement_date="2027-04-01", amount="180000"),
    dict(deposit_ref="SD-L0008-01", lease_id="L0008", movement_type="Original", movement_date="2025-04-01", amount="1800000"),
    dict(deposit_ref="SD-L0008-R1", lease_id="L0008", movement_type="Refund", movement_date="2027-04-30",
         amount="720000", remarks="Partial refund (40%) on surrender of area"),
]

MODIFICATIONS = [
    dict(mod_ref="MOD-L0005-01", lease_id="L0005", effective_date="2027-04-01", modification_type="Lease extension",
         reason="Store performing well - term extended by 3 years",
         original_terms="Expiry 31-Mar-2030; rent Rs 1,59,000 p.m. (FY27-28 after 6% escalation); IBR 9%",
         revised_terms="Expiry 31-Mar-2033; rent Rs 1,65,000 p.m. from Apr-2027; 5% yearly from Apr-2028",
         revised_monthly_rent="165000", revised_end_date="2033-03-31", revised_discount_rate="9.75",
         area_reduction_pct="0", keep_existing_escalations="No", revised_escalation_type="Percentage",
         revised_escalation_pct="5", revised_escalation_frequency="12", revised_first_escalation_date="2028-04-01",
         separate_lease="No",
         accounting_assessment="No additional right of use - not a separate lease (Ind AS 116.44). Remeasure "
                               "liability at revised IBR; adjust ROU (Ind AS 116.45(c), 46(b)).",
         approval_status="Approved"),
]

TERMINATIONS = [
    dict(term_ref="TRM-L0006-01", lease_id="L0006", effective_date="2027-04-01", termination_type="Full",
         termination_reason="Store closure - mutual termination", termination_payment="180000",
         settlement_amount="0", approval_reference="BOD/2027/03/14", approval_status="Approved"),
    dict(term_ref="TRM-L0008-01", lease_id="L0008", effective_date="2027-04-01", termination_type="Partial",
         partial_pct="40", termination_reason="Surrender of 40% of office floor area",
         termination_payment="50000", approval_reference="CFO/2027/03/22", approval_status="Approved"),
]


def load_sample_data(repo: Repository) -> int:
    n = 0
    for row in LEASES:
        if repo.get("lease_master", row["lease_id"]):
            continue
        repo.save("lease_master", {**COMMON, **row}, "Sample data")
        n += 1
    for reg, rows in (("escalations", ESCALATIONS), ("deposits", DEPOSITS), ("modifications", MODIFICATIONS),
                      ("terminations", TERMINATIONS)):
        existing = repo.list_rows(reg)
        for row in rows:
            if reg == "escalations":
                if any(r["lease_id"] == row["lease_id"] and r["effective_date"] == row["effective_date"] for r in existing):
                    continue
            elif repo.get(reg, row[repo_key(reg)]):
                continue
            base = {"refundable": "Refundable", "interest_type": "Interest-free", "approval_status": "Approved"} \
                if reg == "deposits" else {}
            repo.save(reg, {**base, **row}, "Sample data")
    return n


def repo_key(reg):
    return {"deposits": "deposit_ref", "modifications": "mod_ref", "terminations": "term_ref"}[reg]
