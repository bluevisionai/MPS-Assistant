from __future__ import annotations

from datetime import date, timedelta
import re
import time
from typing import Any, Dict, List, Optional

import requests

from ..config import Settings

JOIN_REDIRECT_URL = "https://www.medicalprotection.org/southafrica/join"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")
POSTAL_CODE_PATTERN = re.compile(r"^\d{4}$")

ROLE_OPTIONS: List[dict[str, Any]] = [
    {
        "id": "doc-private",
        "title": "GP - Private Practice",
        "subtitle": "General Practitioner working in private practice",
        "badge": "Paid membership",
        "available_in_chat": True,
        "redirect_url": None,
        "sale_category": "TGZ",
    },
    {
        "id": "doc-state",
        "title": "GP - State Employed",
        "subtitle": "General Practitioner employed in the public sector",
        "badge": "Paid membership",
        "available_in_chat": True,
        "redirect_url": None,
        "sale_category": "SMZ",
    },
    {
        "id": "doc-mixed",
        "title": "GP - State + Private Work",
        "subtitle": "State-employed GP with private sessions included",
        "badge": "Paid membership",
        "available_in_chat": True,
        "redirect_url": None,
        "sale_category": "COM",
    },
    {
        "id": "spec-private",
        "title": "Specialist - Private Practice",
        "subtitle": "Consultant or specialist in private practice",
        "badge": "Different process",
        "available_in_chat": False,
        "redirect_url": JOIN_REDIRECT_URL,
    },
    {
        "id": "spec-state",
        "title": "Specialist - State Employed",
        "subtitle": "Consultant or specialist employed in the public sector",
        "badge": "Different process",
        "available_in_chat": False,
        "redirect_url": JOIN_REDIRECT_URL,
    },
    {
        "id": "medical-officer",
        "title": "Medical Officer",
        "subtitle": "Hospital or clinic medical officer role",
        "badge": "Different process",
        "available_in_chat": False,
        "redirect_url": JOIN_REDIRECT_URL,
    },
    {
        "id": "registrar",
        "title": "Registrar / Trainee Specialist",
        "subtitle": "Doctor in specialist training",
        "badge": "Different process",
        "available_in_chat": False,
        "redirect_url": JOIN_REDIRECT_URL,
    },
    {
        "id": "locum",
        "title": "Locum Doctor",
        "subtitle": "Short-term or sessional locum work",
        "badge": "Different process",
        "available_in_chat": False,
        "redirect_url": JOIN_REDIRECT_URL,
    },
]

PRICING_CATEGORIES = [
    {"value": "non-procedural", "label": "NON PROCEDURAL GP"},
    {"value": "procedural", "label": "PROCEDURAL GP"},
    {"value": "gp-ga", "label": "GP - including general anaesthesia"},
    {"value": "cosmetic", "label": "COSMETIC AND AESTHETIC MEDICINE"},
    {"value": "detailed-scans", "label": "GP INCLUDING DETAILED PREGNANCY SCANS"},
    {"value": "intrapartum", "label": "GP INCLUDING INTRAPARTUM OBSTETRICS"},
]

HOURS_BANDS = [
    {"value": "gt33", "label": "More than 33 hours per week"},
    {"value": "gt22", "label": ">22-33 hours per week"},
    {"value": "gt11", "label": ">11-22 hours per week"},
    {"value": "up11", "label": "Up to 11 hours per week"},
]

INTRAPARTUM_BASES = [
    {"value": "PGQ1", "label": "Claims-made protection (year 1)"},
    {"value": "PGQ2", "label": "Claims-made protection (year 2)"},
    {"value": "PGQ3", "label": "Claims-made protection (year 3)"},
    {"value": "PGQ4", "label": "Claims-made protection (year 4)"},
    {"value": "PGQ5-10", "label": "Claims-made protection (year 5-10)"},
    {"value": "PGO", "label": "Occurrence based protection (not available to new applicants)"},
]

UNDERWRITING_GROUPS: List[dict[str, Any]] = [
    {
        "id": "3d",
        "title": "International Practice",
        "description": "Practice or patient treatment outside South Africa",
        "questions": [
            {
                "key": "practiceOutsideCountry",
                "prompt": "Will you carry out professional practice outside of the country in which you are applying for membership?",
                "note": "",
                "columns": [
                    {"label": "Country", "type": "text", "placeholder": "e.g. Lesotho"},
                    {"label": "Type of work and registration details", "type": "text", "placeholder": ""},
                ],
                "requires_upload": False,
            },
            {
                "key": "treatPatientsOutside",
                "prompt": "Will you be involved in treating or providing advice to patients outside of the country in which you are applying for membership?",
                "note": "This includes remote consultations and prescriptions.",
                "columns": [
                    {"label": "Country", "type": "text", "placeholder": "e.g. Botswana"},
                    {"label": "Type of work and registration details", "type": "text", "placeholder": ""},
                ],
                "requires_upload": False,
            },
        ],
    },
    {
        "id": "3a",
        "title": "Indemnity History",
        "description": "Previous professional indemnity cover and any gaps",
        "questions": [
            {
                "key": "hadIndemnityBefore",
                "prompt": "Have you had any professional indemnity or insurance before?",
                "note": "Include all organisations for the last 10 years. If previously with MPS, include your membership number.",
                "columns": [
                    {"label": "Organisation", "type": "text", "placeholder": "e.g. Medpro"},
                    {"label": "From", "type": "date", "placeholder": ""},
                    {"label": "To", "type": "date", "placeholder": ""},
                    {"label": "Membership or policy number", "type": "text", "placeholder": "e.g. 04/12345"},
                    {"label": "Name at the time", "type": "text", "placeholder": "If different"},
                ],
                "requires_upload": False,
            },
            {
                "key": "practicedWithoutIndemnity",
                "prompt": "Have you at any stage practised without professional indemnity during the last 10 years?",
                "note": "Exclude periods covered by state, employer, insurer or MDO indemnity.",
                "columns": [
                    {"label": "From", "type": "date", "placeholder": ""},
                    {"label": "To", "type": "date", "placeholder": ""},
                    {"label": "Reason", "type": "text", "placeholder": "Brief explanation"},
                ],
                "requires_upload": False,
            },
            {
                "key": "returningAfterBreak",
                "prompt": "Are you returning to work after a break in clinical practice of two or more years?",
                "note": "Attach copies of CPD, clinical refresher training, and any other correspondence.",
                "columns": [
                    {"label": "From", "type": "date", "placeholder": ""},
                    {"label": "To", "type": "date", "placeholder": ""},
                    {"label": "Reason for break", "type": "text", "placeholder": "Include CPD or refresher details"},
                ],
                "requires_upload": True,
            },
            {
                "key": "refusedOrWithdrawn",
                "prompt": "Have you ever been refused professional indemnity or had it withdrawn or voided?",
                "note": "Includes decline to renew.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Summary of events and reasons", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
            {
                "key": "nonStandardTerms",
                "prompt": "Have you ever had non-standard terms, conditions, or a non-standard premium imposed on your professional indemnity?",
                "note": "",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Summary of events and reasons", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
        ],
    },
    {
        "id": "3b",
        "title": "Claims and Complaints History",
        "description": "Any claims, complaints, or potential incidents in the last 10 years",
        "questions": [
            {
                "key": "complaintsUnresolved",
                "prompt": "In the last 10 years, have you had any complaints arising out of your professional practice that were not resolved at a local level?",
                "note": "Do not include patient names or confidential patient information. Attach a case history letter from each previous indemnifier.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary of event", "type": "text", "placeholder": ""},
                    {"label": "Extent of your involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Relevant indemnifiers", "type": "text", "placeholder": ""},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                    {"label": "Referred to regulatory body?", "type": "text", "placeholder": "Yes/No"},
                ],
                "requires_upload": True,
            },
            {
                "key": "claimsCompensation",
                "prompt": "In the last 10 years, have you been involved in any claims for compensation or damages arising out of your professional practice?",
                "note": "This includes matters previously handled by MPS. Do not include patient names.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary", "type": "text", "placeholder": ""},
                    {"label": "Extent of involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Relevant indemnifiers", "type": "text", "placeholder": ""},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                    {"label": "Referred to regulatory body?", "type": "text", "placeholder": "Yes/No"},
                ],
                "requires_upload": True,
            },
            {
                "key": "awarePotentialClaim",
                "prompt": "Are you aware of any incidents or complaints that might become a claim?",
                "note": "Includes matters previously handled by MPS. Do not include patient names.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary", "type": "text", "placeholder": ""},
                    {"label": "Extent of involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Relevant indemnifiers", "type": "text", "placeholder": ""},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
        ],
    },
    {
        "id": "3c",
        "title": "Regulatory and Criminal History",
        "description": "Any regulatory, disciplinary, or criminal proceedings",
        "questions": [
            {
                "key": "disciplinaryInquiry",
                "prompt": "Have you ever been the subject of a disciplinary inquiry or had practice privileges refused, withdrawn, or made conditional by a healthcare provider?",
                "note": "Includes matters previously handled by MPS. Do not include patient names.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary", "type": "text", "placeholder": ""},
                    {"label": "Extent of involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
            {
                "key": "regulatoryReferral",
                "prompt": "Have you ever been subject to any referral, complaint, inquiry, investigation, or hearing by any regulatory, licensing, or registration body?",
                "note": "Includes matters previously handled by MPS. Do not include patient names.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary", "type": "text", "placeholder": ""},
                    {"label": "Extent of involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Body", "type": "text", "placeholder": "e.g. HPCSA"},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
            {
                "key": "cautioned",
                "prompt": "Have you ever been cautioned by the police or convicted of any criminal offence?",
                "note": "Do not include patient names. If reported to a regulatory body, attach the final determination letter.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Details", "type": "text", "placeholder": ""},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
            {
                "key": "otherIssues",
                "prompt": "Are there any other issues of which MPS might need to be aware when considering your application?",
                "note": "Do not include patient names.",
                "columns": [
                    {"label": "Date", "type": "date", "placeholder": ""},
                    {"label": "Factual summary", "type": "text", "placeholder": ""},
                    {"label": "Extent of involvement", "type": "text", "placeholder": ""},
                    {"label": "Country", "type": "text", "placeholder": "SA"},
                    {"label": "Outcome", "type": "text", "placeholder": ""},
                ],
                "requires_upload": True,
            },
        ],
    },
]

PROVINCES = [
    "Gauteng",
    "Western Cape",
    "KwaZulu-Natal",
    "Eastern Cape",
    "Free State",
    "Limpopo",
    "Mpumalanga",
    "North West",
    "Northern Cape",
]

CLIENT_TYPES = [
    "General Practitioner",
    "Specialist",
    "Intern",
    "Community Service Officer",
    "Medical Officer",
    "Student",
    "Locum",
    "Healthcare Practitioner",
]

BANKS = [
    {"name": "ABSA Bank", "code": "632005"},
    {"name": "African Bank", "code": "430000"},
    {"name": "Capitec Bank", "code": "470010"},
    {"name": "Discovery Bank", "code": "679000"},
    {"name": "First National Bank (FNB)", "code": "250655"},
    {"name": "Investec Bank", "code": "580105"},
    {"name": "Nedbank", "code": "198765"},
    {"name": "Standard Bank", "code": "051001"},
    {"name": "TymeBank", "code": "678910"},
    {"name": "Other (specify branch code)", "code": ""},
]

PAYMENT_METHODS = [
    {
        "id": "debit",
        "label": "Debit Order",
        "subtitle": "Secure setup confirmed with MPS after your draft is received",
    },
    {
        "id": "card",
        "label": "Card",
        "subtitle": "Secure card collection stays outside this chat",
    },
    {
        "id": "eft",
        "label": "EFT",
        "subtitle": "Internet banking transfer with an MPS reference",
    },
]

PAYMENT_FREQUENCIES = [
    {"id": "monthly", "label": "Monthly"},
    {"id": "annual", "label": "Annual"},
]

POSTCODE_BRANCHES = [
    ((1000, 1999), "SAMA Gauteng - Johannesburg"),
    ((2000, 2199), "SAMA Gauteng - East Rand"),
    ((2500, 2999), "SAMA Gauteng - Pretoria / Tshwane"),
    ((3000, 3699), "SAMA KwaZulu-Natal Coastal"),
    ((3700, 3999), "SAMA KwaZulu-Natal Inland"),
    ((4000, 4999), "SAMA KwaZulu-Natal"),
    ((5000, 5999), "SAMA Western Cape"),
    ((6000, 6499), "SAMA Eastern Cape"),
    ((6500, 6999), "SAMA Northern Cape"),
    ((7000, 7999), "SAMA Western Cape - Cape Peninsula"),
    ((8000, 8999), "SAMA Free State"),
    ((9000, 9999), "SAMA Limpopo / North West"),
]


class OnboardingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._portal_check_ok: Optional[bool] = None
        self._portal_check_message: str = "Not checked yet."
        self._portal_checked_at: float = 0.0

    def get_config(self) -> dict[str, Any]:
        auth_status = self.portal_auth_status()
        return {
            "portal_url": self.settings.onboarding_portal_url,
            "join_url": JOIN_REDIRECT_URL,
            "portal_auth": auth_status,
            "roles": ROLE_OPTIONS,
            "pricing": {
                "categories": PRICING_CATEGORIES,
                "hours_bands": HOURS_BANDS,
                "intrapartum_bases": INTRAPARTUM_BASES,
                "minimum_start_days": 56,
            },
            "underwriting": UNDERWRITING_GROUPS,
            "provinces": PROVINCES,
            "client_types": CLIENT_TYPES,
            "banks": BANKS,
            "payment_methods": PAYMENT_METHODS,
            "payment_frequencies": PAYMENT_FREQUENCIES,
            "payment_security_note": (
                "This chat can complete the live draft application journey, but it does not store card numbers, CVVs, "
                "or full bank credentials. Secure payment setup still needs to be confirmed directly with MPS."
            ),
        }

    def portal_auth_status(self) -> dict[str, Any]:
        now = time.time()
        if self._portal_check_ok is not None and now - self._portal_checked_at < 600:
            return {
                "enabled": bool(self.settings.onboarding_portal_username and self.settings.onboarding_portal_password),
                "ok": self._portal_check_ok,
                "message": self._portal_check_message,
            }

        if not self.settings.onboarding_portal_username or not self.settings.onboarding_portal_password:
            self._portal_check_ok = False
            self._portal_check_message = "Portal credentials are not configured."
            self._portal_checked_at = now
            return {
                "enabled": False,
                "ok": self._portal_check_ok,
                "message": self._portal_check_message,
            }

        try:
            response = requests.post(
                self.settings.onboarding_auth_url,
                json={
                    "username": self.settings.onboarding_portal_username,
                    "password": self.settings.onboarding_portal_password,
                },
                timeout=self.settings.onboarding_timeout_seconds,
            )
            data = self._json_or_empty(response)
            self._portal_check_ok = bool(response.ok and data.get("token"))
            self._portal_check_message = "Portal login verified." if self._portal_check_ok else self._error_message(data, "Portal login failed.")
        except requests.RequestException:
            self._portal_check_ok = False
            self._portal_check_message = "Portal login check failed."
        self._portal_checked_at = now
        return {
            "enabled": True,
            "ok": self._portal_check_ok,
            "message": self._portal_check_message,
        }

    def send_otp(self, email: str) -> dict[str, Any]:
        normalized_email = (email or "").strip()
        if not EMAIL_PATTERN.match(normalized_email):
            raise ValueError("Enter a valid email address first.")
        try:
            response = requests.post(
                f"{self.settings.onboarding_api_base_url}/verification/send-otp",
                json={"email": normalized_email},
                timeout=self.settings.onboarding_timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError("Unable to reach the verification service.") from error
        data = self._json_or_empty(response)
        if not response.ok:
            raise ValueError(self._error_message(data, "Unable to send the verification code."))
        return {"sent": True, "message": "Verification code sent."}

    def verify_otp(self, email: str, code: str) -> dict[str, Any]:
        normalized_email = (email or "").strip()
        normalized_code = re.sub(r"\D", "", code or "")
        if not EMAIL_PATTERN.match(normalized_email):
            raise ValueError("Enter a valid email address first.")
        if len(normalized_code) != 6:
            raise ValueError("Enter the 6-digit verification code.")
        try:
            response = requests.post(
                f"{self.settings.onboarding_api_base_url}/verification/verify-otp",
                json={"email": normalized_email, "code": normalized_code},
                timeout=self.settings.onboarding_timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError("Unable to reach the verification service.") from error
        data = self._json_or_empty(response)
        if not response.ok:
            return {"verified": False, "message": self._error_message(data, "The verification code was not accepted.")}
        return {"verified": True, "message": "Email verified."}

    def get_rate_card(self) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.settings.onboarding_api_base_url}/pricing/rate-card",
                timeout=self.settings.onboarding_timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError("Unable to reach the live rate-card service.") from error
        data = self._json_or_empty(response)
        if not response.ok:
            raise RuntimeError(self._error_message(data, "Unable to load the live rate card."))
        return data

    def quote(self, gp_category: str, gp_hours_band: Optional[str], gp_intrapartum_basis: Optional[str]) -> dict[str, Any]:
        try:
            response = requests.post(
                f"{self.settings.onboarding_api_base_url}/pricing/quote",
                json={
                    "gp_category": gp_category or "non-procedural",
                    "gp_hours_band": gp_hours_band or None,
                    "gp_intrapartum_basis": gp_intrapartum_basis or None,
                },
                timeout=self.settings.onboarding_timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError("Unable to reach the live pricing service.") from error
        data = self._json_or_empty(response)
        if not response.ok:
            raise ValueError(self._error_message(data, "Unable to calculate the live quote."))
        return data

    def submit_application(self, submission: dict[str, Any]) -> dict[str, Any]:
        fields = dict(submission.get("fields") or {})
        checkboxes = dict(submission.get("checkboxes") or {})
        qualifications = list(submission.get("qualifications") or [])
        underwriting_answers = dict(submission.get("underwriting_answers") or {})
        underwriting_rows = dict(submission.get("underwriting_rows") or {})
        role_id = str(submission.get("membership_category") or "").strip()
        verified = bool(submission.get("verified"))
        verified = bool(submission.get("verified", False))
        marketing = str(submission.get("marketing") or "").strip().lower()

        role = next((item for item in ROLE_OPTIONS if item["id"] == role_id), None)
        if not role:
            raise ValueError("Choose a membership role before submitting.")
        if not role.get("available_in_chat"):
            raise ValueError("That role still needs to continue on the official MPS join site.")
        if not checkboxes.get("ack"):
            raise ValueError("Accept the acknowledgement and authorisation wording before continuing.")
        if not checkboxes.get("scd"):
            raise ValueError("Confirm the special category data consent before continuing.")
        if not checkboxes.get("acc"):
            raise ValueError("Confirm that the application details are accurate before submitting.")

        first_name = str(fields.get("firstName") or "").strip()
        last_name = str(fields.get("lastName") or "").strip()
        email = str(fields.get("email") or "").strip()
        confirm_email = str(fields.get("confirmEmail") or "").strip()
        if len(first_name) < 2:
            raise ValueError("First name must be at least 2 characters.")
        if len(last_name) < 2:
            raise ValueError("Surname must be at least 2 characters.")
        if not EMAIL_PATTERN.match(email):
            raise ValueError("Enter a valid email address.")
        if email != confirm_email:
            raise ValueError("Email confirmation does not match.")

        membership_start_date = str(fields.get("membershipStartDate") or "").strip()
        if not membership_start_date:
            raise ValueError("Choose the desired membership start date.")
        try:
            parsed_start = date.fromisoformat(membership_start_date)
        except ValueError as error:
            raise ValueError("Membership start date is invalid.") from error
        if parsed_start < date.today() + timedelta(days=56):
            raise ValueError("Membership start date must be at least 8 weeks from today.")

        gp_category = str(fields.get("gpCategory") or "").strip()
        gp_hours_band = str(fields.get("gpHoursBand") or "").strip() or None
        gp_intrapartum_basis = str(fields.get("gpIntrapartumBasis") or "").strip() or None
        if not gp_category:
            raise ValueError("Select the GP pricing category.")
        if gp_category == "intrapartum":
            if not gp_intrapartum_basis:
                raise ValueError("Select the intrapartum protection basis.")
        elif not gp_hours_band:
            raise ValueError("Select the weekly hours band.")

        if not str(fields.get("gender") or "").strip():
            raise ValueError("Select the gender in full details.")
        if len(str(fields.get("address1") or "").strip()) < 3:
            raise ValueError("Address Line 1 is required.")
        if len(str(fields.get("city") or "").strip()) < 2:
            raise ValueError("City is required.")
        if not str(fields.get("region") or "").strip():
            raise ValueError("Province or region is required.")
        postal_code = str(fields.get("postalCode") or "").strip()
        if not POSTAL_CODE_PATTERN.match(postal_code):
            raise ValueError("Postal code must be 4 digits.")
        if not str(fields.get("clientType") or "").strip():
            raise ValueError("Choose the client type.")
        if not any(self._qualification_complete(entry) for entry in qualifications):
            raise ValueError("Add at least one complete qualification.")

        expected_questions = [question["key"] for group in UNDERWRITING_GROUPS for question in group["questions"]]
        unanswered = [key for key in expected_questions if underwriting_answers.get(key) not in {"yes", "no"}]
        if unanswered:
            raise ValueError("Answer all underwriting questions before submitting.")
        for question_key, answer in underwriting_answers.items():
            if answer != "yes":
                continue
            rows = underwriting_rows.get(question_key) or []
            if not any(self._disclosure_row_has_content(row) for row in rows):
                raise ValueError("Add disclosure details for each underwriting question answered yes.")

        collection_method = str(fields.get("collectionMethod") or "debit").strip().lower() or "debit"
        collection_frequency = str(fields.get("collectionFrequency") or "monthly").strip().lower() or "monthly"
        if collection_method not in {item["id"] for item in PAYMENT_METHODS}:
            raise ValueError("Choose a payment method.")
        if collection_frequency not in {item["id"] for item in PAYMENT_FREQUENCIES}:
            raise ValueError("Choose a billing frequency.")

        payload = {
            "current_step": int(submission.get("current_step") or 7),
            "membership_start_date": membership_start_date,
            "title": fields.get("title") or None,
            "first_name": first_name,
            "middle_names": str(fields.get("middleNames") or "").strip() or None,
            "last_name": last_name,
            "maiden_name": str(fields.get("maidenName") or "").strip() or None,
            "gender": str(fields.get("gender") or "").strip() or None,
            "date_of_birth": str(fields.get("dateOfBirth") or "").strip() or None,
            "id_number": str(fields.get("idNumber") or "").strip() or None,
            "address_1": str(fields.get("address1") or "").strip() or None,
            "address_2": str(fields.get("address2") or "").strip() or None,
            "address_3": str(fields.get("address3") or "").strip() or None,
            "city": str(fields.get("city") or "").strip() or None,
            "region": str(fields.get("region") or "").strip() or None,
            "country": str(fields.get("country") or "South Africa").strip() or "South Africa",
            "postal_code": postal_code,
            "email": email,
            "confirm_email": confirm_email,
            "mobile_phone": None,
            "home_phone": str(fields.get("homePhone") or "").strip() or None,
            "work_phone": str(fields.get("workPhone") or "").strip() or None,
            "marketing_consent": marketing == "yes",
            "special_category_consent": bool(checkboxes.get("scd")),
        }

        try:
            response = requests.post(
                f"{self.settings.onboarding_api_base_url}/{self.settings.onboarding_country_code}/leads/draft",
                json=payload,
                timeout=self.settings.onboarding_timeout_seconds,
            )
        except requests.RequestException as error:
            raise RuntimeError("Unable to reach the live application service.") from error
        data = self._json_or_empty(response)
        if response.status_code not in {200, 201, 202}:
            raise RuntimeError(self._error_message(data, "The live application draft could not be saved."))

        return {
            "lead_id": data.get("lead_id"),
            "status": data.get("status") or "submitted",
            "message": data.get("message") or "Draft lead saved.",
            "reference": self.application_reference(first_name, last_name),
            "payment_method": collection_method,
            "payment_frequency": collection_frequency,
        }

    @staticmethod
    def derive_sama_branch(postal_code: str) -> Optional[str]:
        try:
            postal_int = int(postal_code)
        except (TypeError, ValueError):
            return None
        for (start, end), label in POSTCODE_BRANCHES:
            if start <= postal_int <= end:
                return label
        return None

    @staticmethod
    def sale_dates(membership_start_date: str) -> dict[str, str]:
        if not membership_start_date:
            return {"sale_start": "", "sale_end": "", "renewal": ""}
        try:
            start_date = date.fromisoformat(membership_start_date)
        except ValueError:
            return {"sale_start": "", "sale_end": "", "renewal": ""}
        sale_end = start_date.replace(year=start_date.year + 1) - timedelta(days=1)
        renewal = sale_end + timedelta(days=1)
        return {
            "sale_start": start_date.isoformat(),
            "sale_end": sale_end.isoformat(),
            "renewal": renewal.isoformat(),
        }

    @staticmethod
    def application_reference(first_name: str, last_name: str) -> str:
        first = (first_name or "").upper().replace(" ", "")[:3] or "APP"
        last = (last_name or "").upper().replace(" ", "")[:3] or "MPS"
        return f"MPS-{first}{last}-{date.today().year}"

    @staticmethod
    def _qualification_complete(entry: Any) -> bool:
        if not isinstance(entry, dict):
            return False
        return all(
            str(entry.get(key) or "").strip()
            for key in ("country", "institution", "qualification", "monthYear")
        )

    @staticmethod
    def _disclosure_row_has_content(row: Any) -> bool:
        if isinstance(row, dict):
            return any(str(value or "").strip() for value in row.values())
        if isinstance(row, list):
            return any(str(value or "").strip() for value in row)
        return False

    @staticmethod
    def _json_or_empty(response: requests.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _error_message(data: dict[str, Any], fallback: str) -> str:
        detail = data.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg")
                if isinstance(msg, str) and msg.strip():
                    return msg.strip()
            if isinstance(first, str) and first.strip():
                return first.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
        error = data.get("error")
        if isinstance(error, str) and error.strip():
            return error.strip()
        return fallback
