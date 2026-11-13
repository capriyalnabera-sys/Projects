# Accounting method and judgements (Phase 1)

This note explains exactly how the application calculates each number so Finance can validate
the results and approve the accounting judgements. The engine is in `lease_app/engine/` and is
independent of the desktop screens.

## 1. Time and discount-rate conventions (configurable: Settings)

| Setting | Default | Alternative | Effect |
|---|---|---|---|
| Time basis | `monthly`: whole lease months from commencement plus the fraction of the current lease month (days ÷ days in that lease month) | `actual_365`: days ÷ 365 (same as Excel XNPV) | Full months always count as exactly 1.0, so monthly interest and depreciation are even |
| IBR conversion | `effective`: monthly rate = (1 + IBR)^(1/12) − 1 | `nominal`: IBR ÷ 12 | The IBR is treated as an effective annual rate |

**Judgement for Finance approval:** the defaults are monthly / effective. Changing them changes
every calculation (posted journals already stored are not altered).

## 2. Lease payments and rent escalation

* Lease months are anchored on the commencement date (for example, 15 Oct to 14 Nov).
* Monthly rent is taken from the lease master; escalation rules in the Rent Escalation Register are
  applied in date order:
  * Percentage: revised rent = existing rent × (1 + %), rounded to paise (half-up).
  * Absolute amount: revised rent = existing rent + amount.
  * Frequency 12 means the rule repeats every 12 months until the next rule's effective date.
    Frequency 0 means one-time.
  * An escalation applies from the first lease month starting on or after its effective date.
* Rent-free months carry zero lease payment; escalation continues to compound underneath.
* Periodic payment = sum of the monthly rents in the period (quarterly = 3 months), so an escalation
  falling inside a quarter is handled correctly. A broken final month is pro-rated on days.
* Due date: Advance = first day of the period; Arrears = last day of the period (settled at the end of that day).
* GST and non-lease components (CAM) are tracked separately and are **excluded** from the lease
  liability; they are expensed or taken as input credit in the rent journal.

## 3. Initial measurement (Ind AS 116.24–26)

* **Lease liability** = Σ payment ÷ (1 + monthly rate)^t, where t = months from commencement to the
  payment date. A payment due on the commencement date (advance) has t = 0 and discount factor 1; it
  is included in the present value and settled the same day by the rent journal. The net result is
  the same as excluding it from the liability and adding it to the ROU.
* **ROU asset** = lease liability + prepaid lease rentals + initial direct costs + restoration
  provision (input as present value) − lease incentives received + other adjustments.
* Each lease workbook (`Lease_Workings_Lxxxx.xlsx`, sheet *Initial PV workings*) shows each payment,
  t, the discount factor and a **live Excel formula** `=payment/(1+rate)^t`, so the PV can be
  verified in Excel independently.

## 4. Subsequent measurement

* **Interest (effective-interest method):** interest accrues on the outstanding liability for the
  exact time elapsed and is split at calendar-month ends and payment dates. Calendar-month journals
  therefore work for leases starting mid-month.
* **Depreciation:** straight line over the lease term (Ind AS 116.31–32). Whenever the carrying amount
  changes (modification or additional deposit discount), the new carrying amount is depreciated
  prospectively over the remaining term.
* **Rounding:** calculations use 40-digit decimal arithmetic (never floating point). Month-end
  balances are rounded to paise; monthly interest, depreciation and deposit unwinding are the
  balancing figures, so every roll-forward ties exactly and balances close at exactly zero.
* **Current / non-current liability:** current = liability today − liability 12 months later under
  the terms in force today (that is, the principal falling due within 12 months).

## 5. Modifications (Ind AS 116.44–46)

* **Separate lease** (`Separate lease = Yes`): there is no change to the existing lease. Enter the
  additional scope as a new lease.
* **Not a separate lease:** at the effective date the liability is remeasured as the PV of the
  revised payments at the **revised discount rate** (blank = unchanged rate).
  * **Decrease in scope** (area reduction %, or a shorter term where f = reduction in the
    remaining term): the ROU and liability are first reduced by the proportion f, with the
    difference taken to P&L as gain or loss (46(a)). The gross block and accumulated depreciation
    are reduced proportionately.
  * **Remaining remeasurement** (and all other modifications, such as an extension or rent change)
    adjusts the ROU (46(b)). If the ROU would go negative, the excess goes to P&L.
* Revised rent: blank = continue the current rent. Escalations: "Continue existing escalation
  clauses = Yes" keeps the original clauses. Otherwise, only the revised escalation rule applies.
* The original calculation is kept as version *Original*; each modification adds a version.
* Only **Approved** modifications are accounted for. Escalations already in the original contract
  are never treated as modifications.

## 6. Terminations

* **Full:** the effective date is the first day the lease no longer applies. Payments due on or after
  that date are cancelled. The liability, gross block and accumulated depreciation are
  derecognised. Gain/(loss) = liability − ROU (net) − termination payment.
* **Partial:** processed as a decrease in scope of the surrendered % (46(a)). The revised rent
  defaults to current rent × (1 − %). Gain/(loss) includes the termination payment.

## 7. Security deposits (Ind AS 109 / Ind AS 116)

* **Refundable, interest-free:** fair value = refund ÷ (1 + rate)^(t/12) at the deposit discount
  rate. The rate is taken from the movement record, then the Settings default, then the lease IBR.
  The expected refund date defaults to the lease end date. The difference between cash and fair
  value is a prepaid lease payment added to the **ROU** and depreciated over the remaining term (or
  held as *Prepaid lease rentals* until commencement). The deposit is unwound to the refund amount
  by the effective-interest method: Dr Security deposit, Cr Interest income.
* **Each additional deposit** is a separate tranche with its own fair value and unwinding. It is
  **not** a lease modification.
* **Refunds** are applied first-in-first-out. The carrying amount of the refunded portion is
  derecognised. Any difference from cash (an early refund) goes to P&L ("Gain / loss on early refund
  of security deposit").
* **Interest-bearing at a market rate:** carried at nominal (no discounting).
* **Non-refundable:** treated as a lease payment and added to the ROU.

## 8. Journals generated per month

| Journal type | Entry |
|---|---|
| INITIAL_RECOGNITION | Dr ROU gross, Dr Lease incentive receivable / Cr Lease liability, Prepaid rent, IDC clearing, Restoration provision |
| ROU_DEPRECIATION | Dr Depreciation / Cr Accumulated depreciation – ROU |
| LIABILITY_INTEREST | Dr Interest expense / Cr Lease liability |
| LEASE_RENTAL_PAYMENT | Dr Lease liability, Dr Non-lease expense, Dr GST input / Cr Lease rent payable |
| SD_ADDITION | Dr Security deposit (FV), Dr ROU (discount) / Cr Bank |
| SD_REFUND | Dr Bank / Cr Security deposit (carrying), Cr/Dr Early-refund gain/loss |
| SD_UNWINDING | Dr Security deposit / Cr Interest income |
| LEASE_MODIFICATION | Dr/Cr ROU gross and accumulated depreciation, Dr/Cr Lease liability, Gain/loss |
| LEASE_TERMINATION | Dr Lease liability, Dr Accumulated depreciation / Cr ROU gross, Cr Termination payable, Gain/loss |

The rental entry credits *Lease rent payable*. The actual bank payment is recorded in the AP module,
which keeps the lease accounting independent of payment timing. Every voucher is checked to
balance before it is saved.

## 9. Points for Finance to confirm (judgements)

1. Time basis (monthly) and effective-annual IBR conversion.
2. Treatment of the deposit discount as a prepaid lease payment in the ROU. The alternative is a
   separate prepaid asset.
3. The deposit discount rate. Use Settings for a single market rate, or enter one per deposit.
4. Early refund difference taken to P&L. This is economically equivalent to a revision of expected
   cash flows under Ind AS 109 B5.4.6.
5. Term-reduction proportion f measured on remaining days.
6. Escalation effective dates aligned with lease-month starts.

## 10. Known Phase 1 limitations (planned for Phase 2)

* Unwinding of the restoration provision (Ind AS 37) is not yet automated. The provision is
  recognised at PV in the ROU only.
* A modification that changes the lease end does not yet re-estimate the expected refund date of
  existing deposits.
* An absolute-amount escalation that continues after a partial termination is not scaled down.
  Enter revised escalation terms on the termination or modification if needed.
* Impairment of the ROU, the short-term / low-value exemptions and variable payments are not yet in
  scope.
