"""Plain data structures passed into and out of the calculation engine.

The engine never touches the database or the user interface - it receives these objects
and returns results.  This keeps the accounting logic testable in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .decimal_utils import ZERO

FREQUENCY_MONTHS = {"Monthly": 1, "Quarterly": 3, "Half-yearly": 6, "Annual": 12}


@dataclass
class EscalationRule:
    effective_date: date
    esc_type: str                    # "Percentage" | "Absolute Amount"
    pct: Decimal = ZERO              # 5 means 5 %
    amount: Decimal = ZERO
    frequency_months: int = 0        # 0 = one-time; 12 = repeats every 12 months
    remarks: str = ""
    agreement_ref: str = ""
    source_id: Optional[int] = None


@dataclass
class ModificationInput:
    ref: str
    effective_date: date
    mod_type: str = "Other"
    revised_monthly_rent: Optional[Decimal] = None
    revised_end_date: Optional[date] = None
    revised_rate: Optional[Decimal] = None
    revised_frequency_months: Optional[int] = None
    revised_timing: Optional[str] = None
    area_reduction_pct: Decimal = ZERO
    keep_existing_escalations: bool = True
    revised_escalations: list = field(default_factory=list)
    separate_lease: bool = False
    # used when a partial termination is processed through the modification logic
    termination_payment: Decimal = ZERO
    is_partial_termination: bool = False


@dataclass
class TerminationInput:
    ref: str
    effective_date: date
    full: bool = True
    partial_pct: Decimal = ZERO
    termination_payment: Decimal = ZERO
    revised_monthly_rent: Optional[Decimal] = None
    revised_rate: Optional[Decimal] = None


@dataclass
class DepositMovementInput:
    ref: str
    movement_date: date
    kind: str                        # "Original" | "Addition" | "Refund"
    amount: Decimal
    refundable: bool = True
    interest_free: bool = True
    annual_rate: Optional[Decimal] = None
    expected_refund_date: Optional[date] = None


@dataclass
class LeaseInput:
    lease_id: str
    commencement: date
    end_date: date
    monthly_rent: Decimal
    frequency_months: int = 1
    timing: str = "Advance"          # Advance | Arrears
    annual_rate: Decimal = ZERO      # IBR % p.a.
    rent_free_months: int = 0
    escalations: list = field(default_factory=list)
    prepaid: Decimal = ZERO
    idc: Decimal = ZERO
    incentives: Decimal = ZERO
    restoration: Decimal = ZERO
    other_adj: Decimal = ZERO
    gst_rate: Decimal = ZERO
    non_lease_monthly: Decimal = ZERO
    modifications: list = field(default_factory=list)
    terminations: list = field(default_factory=list)
    deposits: list = field(default_factory=list)
    agreement_no: str = ""
    entity: str = ""
    location: str = ""
    landlord: str = ""
