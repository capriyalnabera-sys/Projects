# Phase 1 demonstration – April 2027

Demo database: `sample_data/demo_lease_accounting.sqlite`. Journals are in
`sample_data/outputs/Journals_April_2027.xlsx`, and lease-wise workings are in
`sample_data/outputs/Lease_Workings_Lxxxx.xlsx`.

Settings: monthly time basis; monthly rate = **IBR ÷ 12** (for example, 9% → 0.75% per month). Each deposit is discounted at the IBR of its
lease (no default deposit rate is set).

## Demonstration leases

| Lease | Scenario demonstrated | Key terms |
|---|---|---|
| L0001 Mumbai | **Percentage escalation** | ₹1,00,000 p.m., +5% every April, monthly advance, IBR 9%, 9 years |
| L0002 Pune | **Absolute escalation** + GST | ₹2,50,000 p.m., +₹12,500 p.m. every July, quarterly advance, IBR 9.5%, GST 18% |
| L0003 Bhiwandi | **Both methods** + rent-free + mid-month start + arrears | Starts 15-Oct-2025, 3 months rent-free, +₹10,000 yearly, then +15% every 3 years from Oct-2028, CAM ₹15,000 p.m. |
| L0004 Bengaluru | **Additional security deposit** | Additional ₹1,20,000 deposit on 1-Apr-2027 (not a modification) |
| L0005 Delhi | **Lease modification** | Extended from Mar-2030 to Mar-2033 w.e.f. 1-Apr-2027; rent ₹1,65,000 p.m., +5% yearly; IBR 9% → 9.75% |
| L0006 Chennai | **Full termination** | Terminated w.e.f. 1-Apr-2027; payment ₹1,80,000; deposit ₹2,70,000 refunded 30-Apr-2027 |
| L0007 Hyderabad | **New lease** in April 2027 | IDC ₹50,000, incentive ₹25,000, restoration ₹1,00,000, quarterly arrears |
| L0008 Noida | **Partial termination** | 40% of area surrendered w.e.f. 1-Apr-2027; payment ₹50,000; 40% of deposit refunded |

## April 2027 – lease-wise figures (₹)

| Lease | Initial liability | Initial ROU | Opening liability | Interest | Payment | Closing liability | Opening ROU | Depreciation | Closing ROU | Deposit (carrying) |
|---|---|---|---|---|---|---|---|---|---|---|
| L0001 | 88,53,822.28 | 88,53,822.28 | 78,91,337.38 | 58,358.15 | 1,10,250.00 | 78,39,445.53 | 71,44,693.85 | 85,055.87 | 70,59,637.98 | 3,22,787.26 |
| L0002 | 1,31,87,958.90 | 1,31,87,958.90 | 96,67,567.29 | 70,300.53 | 7,87,500.00 | 89,50,367.82 | 87,55,856.91 | 2,24,509.15 | 85,31,347.76 | 5,55,954.95 |
| L0003 | 1,65,45,608.35 | 1,72,28,034.84 | 1,64,15,076.93 | 1,33,881.83 | 1,90,000.00 | 1,63,58,958.76 | 1,47,08,666.30 | 1,41,405.73 | 1,45,67,260.57 | 4,65,474.40 |
| L0004 | 85,89,210.55 | 85,89,210.55 | 76,77,768.03 | 56,638.26 | 1,26,000.00 | 76,08,406.29 | 71,93,233.51 | 1,04,950.10 | 71,36,606.85 | 2,88,856.53 |
| L0005 | 81,22,646.64 | 81,22,646.64 | 56,46,899.18 | 80,788.89 | 1,65,000.00 | 1,00,24,037.39 | 50,68,607.00 | 1,32,360.50 | 93,97,595.82 | 6,93,059.10 |
| L0006 | 65,48,225.46 | 65,48,225.46 | 46,97,068.59 | – | – | – | 39,69,617.21 | – | – | – |
| L0007 | 19,36,452.91 | 20,61,452.91 | – | 14,926.82 | – | 19,51,379.73 | – | 58,469.23 | 20,46,423.06 | 1,37,613.27 |
| L0008 | 2,14,73,026.31 | 2,14,73,026.31 | 1,75,86,133.06 | 77,649.23 | 1,98,450.00 | 1,04,30,879.20 | 1,59,37,052.28 | 1,59,370.52 | 94,02,860.98 | 6,95,136.67 |

The "Initial ROU" column excludes the security-deposit discount, which is added to the ROU as a
separate addition on the deposit date.

## Events in April 2027

* **L0004 additional deposit:** cash ₹1,20,000; fair value ₹71,676.56 (PV of a refund on 31-Dec-2032
  at 9% ÷ 12); discount ₹48,323.44 added to the ROU. Depreciation is recomputed from April.
* **L0005 modification:** liability ₹56,46,899.18 → ₹1,01,08,248.50 (PV of 72 revised payments at
  9.75% ÷ 12); ROU increased by the same ₹44,61,349.32; no gain or loss.
* **L0006 full termination:** liability ₹46,97,068.59 − ROU ₹39,69,617.21 − payment ₹1,80,000 =
  **gain ₹5,47,451.38**. Deposit refund: cash ₹2,70,000 against a carrying amount of ₹1,91,053.70, so
  ₹78,946.30 goes to P&L (refund before the original expected date).
* **L0007 new lease:** liability ₹19,36,452.91; ROU ₹20,61,452.91 (+ IDC ₹50,000 + restoration
  ₹1,00,000 − incentive ₹25,000). Deposit discount ₹43,439.38 added to the ROU.
* **L0008 partial termination (40%):** 40% of liability and ROU derecognised; gain = 40% × (L − ROU) −
  ₹50,000 = **₹6,09,632.31**. Rent falls to 60% (₹1,98,450). The remeasurement difference is ₹0.14,
  which comes only from paise rounding of the future escalated rents. Deposit refund ₹7,20,000
  against a carrying amount of ₹4,63,309.04.

## Totals

88 journal lines, 36 vouchers; total debit = total credit = **₹2,79,79,993.90**.
