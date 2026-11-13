# Phase 1 demonstration – April 2027

Demo database: `sample_data/demo_lease_accounting.sqlite`. Journals are in
`sample_data/outputs/Journals_April_2027.xlsx`, and lease-wise workings are in
`sample_data/outputs/Lease_Workings_Lxxxx.xlsx`.

Settings: monthly time basis, effective-annual IBR. Each deposit is discounted at the IBR of its
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
| L0001 | 89,84,134.36 | 89,84,134.36 | 79,82,508.08 | 56,737.91 | 1,10,250.00 | 79,28,995.99 | 72,39,410.64 | 86,183.46 | 71,53,227.18 | 3,30,662.73 |
| L0002 | 1,33,04,563.65 | 1,33,04,563.65 | 97,22,226.56 | 67,828.28 | 7,87,500.00 | 90,02,554.84 | 88,25,714.81 | 2,26,300.38 | 85,99,414.43 | 5,62,806.84 |
| L0003 | 1,68,90,139.67 | 1,75,55,137.48 | 1,66,98,721.09 | 1,30,339.02 | 1,90,000.00 | 1,66,39,060.11 | 1,49,87,934.58 | 1,44,090.55 | 1,48,43,844.03 | 4,82,601.65 |
| L0004 | 86,88,443.96 | 86,88,443.96 | 77,51,031.98 | 54,956.07 | 1,26,000.00 | 76,79,988.05 | 72,70,847.08 | 1,06,053.91 | 72,11,665.88 | 2,94,617.38 |
| L0005 | 81,90,663.67 | 81,90,663.67 | 56,75,148.63 | 78,295.70 | 1,65,000.00 | 1,01,38,082.14 | 51,03,353.94 | 1,34,069.33 | 95,18,922.42 | 7,00,136.15 |
| L0006 | 66,16,295.61 | 66,16,295.61 | 47,26,323.69 | – | – | – | 40,08,173.84 | – | – | – |
| L0007 | 19,47,762.70 | 20,72,762.70 | – | 14,412.72 | – | 19,62,175.42 | – | 58,741.36 | 20,55,947.48 | 1,39,095.55 |
| L0008 | 2,17,21,109.84 | 2,17,21,109.84 | 1,77,32,224.75 | 75,250.83 | 1,98,450.00 | 1,05,16,135.82 | 1,60,97,300.05 | 1,60,973.00 | 94,97,407.17 | 7,07,148.70 |

The "Initial ROU" column excludes the security-deposit discount, which is added to the ROU as a
separate addition on the deposit date.

## Events in April 2027

* **L0004 additional deposit:** cash ₹1,20,000; fair value ₹73,127.29 (PV of a refund on 31-Dec-2032
  at 9%); discount ₹46,872.71 added to the ROU. Depreciation is recomputed from April.
* **L0005 modification:** liability ₹56,75,148.63 → ₹1,02,24,786.45 (PV of 72 revised payments at
  9.75%); ROU increased by the same ₹45,49,637.81; no gain or loss.
* **L0006 full termination:** liability ₹47,26,323.69 − ROU ₹40,08,173.84 − payment ₹1,80,000 =
  **gain ₹5,38,149.85**. Deposit refund: cash ₹2,70,000 against a carrying amount of ₹1,93,503.65, so
  ₹76,496.35 goes to P&L (refund before the original expected date).
* **L0007 new lease:** liability ₹19,47,762.70; ROU ₹20,72,762.70 (+ IDC ₹50,000 + restoration
  ₹1,00,000 − incentive ₹25,000). Deposit discount ₹41,926.14 added to the ROU.
* **L0008 partial termination (40%):** 40% of liability and ROU derecognised; gain = 40% × (L − ROU) −
  ₹50,000 = **₹6,03,969.88**. Rent falls to 60% (₹1,98,450). The remeasurement difference is ₹0.14,
  which comes only from paise rounding of the future escalated rents. Deposit refund ₹7,20,000
  against a carrying amount of ₹4,71,319.63.

## Totals

88 journal lines, 36 vouchers; total debit = total credit = **₹2,82,14,075.40**.
