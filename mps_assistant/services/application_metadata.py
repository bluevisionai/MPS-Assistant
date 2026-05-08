from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import requests

from ..config import Settings
from ..schemas import ExtractedDocument, ExtractedSection
from .browser_renderer import ApplicationWalkthrough, CapturedNetworkResponse, RenderedPage
from .extractors import build_extracted_document, extract_json_document


def build_application_metadata_documents(
    rendered_page: RenderedPage,
    downloaded_at: str,
    settings: Settings,
    session: requests.Session,
) -> List[ExtractedDocument]:
    parsed = urlparse(rendered_page.final_url or "")
    if parsed.netloc not in settings.rendered_application_hosts:
        return []

    documents: List[ExtractedDocument] = []

    appsettings_document = _fetch_appsettings_document(session, parsed, downloaded_at, settings.crawl_timeout_seconds)
    if appsettings_document is not None:
        documents.append(appsettings_document)

    for response in rendered_page.api_responses:
        document = _api_response_document(response, downloaded_at)
        if document is not None:
            documents.append(document)

    documents.extend(_bundle_inventory_documents(rendered_page.resource_urls, downloaded_at, session, settings))
    return documents


def build_walkthrough_documents(
    walkthrough: ApplicationWalkthrough,
    downloaded_at: str,
) -> List[ExtractedDocument]:
    if not walkthrough.request_payload:
        return []

    payload = dict(walkthrough.request_payload)
    payload.pop("CaptchaToken", None)

    field_sections = _walkthrough_payload_sections(payload)
    schema_document = build_extracted_document(
        source_key=f"{walkthrough.url}#request-model",
        origin="application_walkthrough",
        source_format="application-walkthrough",
        downloaded_at=downloaded_at,
        sections=field_sections,
        checksum_content=payload,
        url=walkthrough.url,
        page_title="Membership application request model",
        document_title="Membership application request model",
        file_name=None,
        content_type="application/json",
    )

    notes = []
    if walkthrough.response_status is not None:
        notes.append(f"Observed submission response status: {walkthrough.response_status}")
    if walkthrough.error_text:
        notes.append(f"Observed page message: {walkthrough.error_text}")
    if walkthrough.final_url:
        notes.append(f"Final URL after dummy walkthrough: {walkthrough.final_url}")
    notes_document = build_extracted_document(
        source_key=f"{walkthrough.url}#walkthrough-notes",
        origin="application_walkthrough",
        source_format="application-walkthrough",
        downloaded_at=downloaded_at,
        sections=[ExtractedSection(heading="Dummy walkthrough notes", text="\n".join(notes))] if notes else [],
        checksum_content={"notes": notes},
        url=walkthrough.url,
        page_title="Membership application walkthrough notes",
        document_title="Membership application walkthrough notes",
        file_name=None,
        content_type="text/plain",
    )

    return [document for document in [schema_document, notes_document] if document.sections]


def _fetch_appsettings_document(
    session: requests.Session,
    parsed_url,
    downloaded_at: str,
    timeout_seconds: int,
) -> Optional[ExtractedDocument]:
    appsettings_url = f"{parsed_url.scheme}://{parsed_url.netloc}/appsettings.json"
    try:
        response = session.get(appsettings_url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    sections = _appsettings_sections(payload)
    return build_extracted_document(
        source_key=appsettings_url,
        origin="website",
        source_format="application-json",
        downloaded_at=downloaded_at,
        sections=sections,
        checksum_content=payload,
        url=appsettings_url,
        page_title="Application settings",
        document_title="Application settings",
        file_name=Path(urlparse(appsettings_url).path).name or None,
        content_type="application/json",
    )


def _api_response_document(response: CapturedNetworkResponse, downloaded_at: str) -> Optional[ExtractedDocument]:
    try:
        payload = json.loads(response.body)
    except json.JSONDecodeError:
        return None

    path = urlparse(response.url).path
    file_name = Path(path).name or None
    if path.endswith("/appsettings.json"):
        return build_extracted_document(
            source_key=response.url,
            origin="website",
            source_format="application-json",
            downloaded_at=downloaded_at,
            sections=_appsettings_sections(payload),
            checksum_content=payload,
            url=response.url,
            page_title="Application settings",
            document_title="Application settings",
            file_name=file_name,
            content_type=response.mime_type,
        )

    if path.startswith("/api/Scheme/") and path.endswith("/AddressCountries"):
        return build_extracted_document(
            source_key=response.url,
            origin="website",
            source_format="application-json",
            downloaded_at=downloaded_at,
            sections=[
                ExtractedSection(
                    heading="Available address countries",
                    text="\n".join(f"- {item.get('name')}" for item in payload if item.get("name")),
                )
            ],
            checksum_content=payload,
            url=response.url,
            page_title="Application address countries",
            document_title="Application address countries",
            file_name=file_name,
            content_type=response.mime_type,
        )

    if path.startswith("/api/Lookup/ProspectTitles"):
        return build_extracted_document(
            source_key=response.url,
            origin="website",
            source_format="application-json",
            downloaded_at=downloaded_at,
            sections=[
                ExtractedSection(
                    heading="Available titles",
                    text="\n".join(f"- {item.get('name')}" for item in payload if item.get("name")),
                )
            ],
            checksum_content=payload,
            url=response.url,
            page_title="Application titles",
            document_title="Application titles",
            file_name=file_name,
            content_type=response.mime_type,
        )

    if path.startswith("/api/Scheme/"):
        sections = _scheme_sections(payload)
        title = f"Scheme {payload.get('id', '')} application settings".strip()
        return build_extracted_document(
            source_key=response.url,
            origin="website",
            source_format="application-json",
            downloaded_at=downloaded_at,
            sections=sections,
            checksum_content=payload,
            url=response.url,
            page_title=title,
            document_title=title,
            file_name=file_name,
            content_type=response.mime_type,
        )

    return extract_json_document(
        source_key=response.url,
        origin="website",
        downloaded_at=downloaded_at,
        payload=payload,
        url=response.url,
        page_title=file_name,
        document_title=file_name,
        file_name=file_name,
        content_type=response.mime_type,
        source_format="application-json",
    )


def _appsettings_sections(payload: dict) -> List[ExtractedSection]:
    sections: List[ExtractedSection] = []

    schemes = payload.get("SouthAfricaSchemes") or []
    if schemes:
        sections.append(
            ExtractedSection(
                heading="South Africa schemes",
                text="\n".join(f"- {value}" for value in schemes),
            )
        )

    private_practice = payload.get("PrivatePractice") or {}
    if isinstance(private_practice, dict):
        lines = []
        for key, values in private_practice.items():
            label = _humanize_name(key)
            if isinstance(values, list):
                lines.append(f"{label}: {', '.join(str(value) for value in values)}")
            else:
                lines.append(f"{label}: {values}")
        if lines:
            sections.append(ExtractedSection(heading="Private practice option sets", text="\n".join(lines)))

    for key, heading in [
        ("MpsComments", "How did you hear about MPS options"),
        ("MpsStudentComments", "Student referral options"),
    ]:
        values = payload.get(key) or {}
        if isinstance(values, dict) and values:
            lines = [f"{item_key}: {item_value}" for item_key, item_value in sorted(values.items(), key=lambda item: item[0])]
            sections.append(ExtractedSection(heading=heading, text="\n".join(lines)))

    upload_limits = payload.get("UploadLimits") or {}
    if isinstance(upload_limits, dict) and upload_limits:
        lines = []
        allowed_types = upload_limits.get("AllowedFileTypes") or []
        if allowed_types:
            lines.append("Allowed file types: " + ", ".join(str(value) for value in allowed_types))
        allowed_content = upload_limits.get("AllowedContentTypes") or []
        if allowed_content:
            lines.append("Allowed content types: " + ", ".join(str(value) for value in allowed_content))
        if upload_limits.get("MaxFileSizeBytes") is not None:
            lines.append(f"Max file size bytes: {upload_limits.get('MaxFileSizeBytes')}")
        if upload_limits.get("MaxUploads") is not None:
            lines.append(f"Max uploads: {upload_limits.get('MaxUploads')}")
        if lines:
            sections.append(ExtractedSection(heading="Upload limits", text="\n".join(lines)))

    return sections


def _scheme_sections(payload: dict) -> List[ExtractedSection]:
    sections: List[ExtractedSection] = []

    overview_lines = []
    for key in ["id", "name", "professionId", "regionId", "email", "phone", "bannerHeader", "introHeader", "completionUri", "privacyUri"]:
        value = payload.get(key)
        if value not in (None, ""):
            overview_lines.append(f"{_humanize_name(key)}: {value}")
    if overview_lines:
        sections.append(ExtractedSection(heading="Scheme overview", text="\n".join(overview_lines)))

    membership_lines = []
    for key in ["membershipStartLabel", "membershipStartMaxValue", "membershipStartMaxPeriod", "isEnabled", "applicationConfirmationText"]:
        value = payload.get(key)
        if value not in (None, ""):
            membership_lines.append(f"{_humanize_name(key)}: {value}")
    if membership_lines:
        sections.append(ExtractedSection(heading="Membership timing and completion", text="\n".join(membership_lines)))

    identity_lines = []
    for key in [
        "isRegistrationNumberRequired",
        "registationNumberLabel",
        "registationNumber2Label",
        "isIdNumberRequired",
        "idNumberLabel",
        "isAddressPostcodeRequired",
        "postcodeLabel",
        "hasPostcode",
        "countyLabel",
        "countriesOfPractice",
        "hasAddressLookup",
        "addressLookupPlaceholder",
        "addressLookupCountries",
    ]:
        value = payload.get(key)
        if value not in (None, ""):
            identity_lines.append(f"{_humanize_name(key)}: {value}")
    if identity_lines:
        sections.append(ExtractedSection(heading="Identity and address requirements", text="\n".join(identity_lines)))

    practice_lines = []
    for key in [
        "hasPrivateQuestion",
        "hasPrivateSalaryQuestion",
        "privateSalaryQuestionLabel",
        "privateSalaryQuestionOptions",
        "practiceHoursPerWeekLabel",
        "workingHospitalLabel",
        "hasSchoolQuestion",
        "hasSchoolIntakeQuestion",
        "hasSchoolCourseQuestion",
        "hasRetroactiveReportingBenefits",
        "isWorkingHospitalRequired",
    ]:
        value = payload.get(key)
        if value not in (None, ""):
            practice_lines.append(f"{_humanize_name(key)}: {value}")
    if practice_lines:
        sections.append(ExtractedSection(heading="Practice and application flags", text="\n".join(practice_lines)))

    return sections


def _bundle_inventory_documents(
    resource_urls: Sequence[str],
    downloaded_at: str,
    session: requests.Session,
    settings: Settings,
) -> List[ExtractedDocument]:
    documents: List[ExtractedDocument] = []
    client_url = _first_matching_url(resource_urls, "Mps.InternationalApplications.Apply.Client.")
    shared_url = _first_matching_url(resource_urls, "Mps.InternationalApplications.Apply.Shared.")

    client_strings = _fetch_binary_strings(session, client_url, settings.crawl_timeout_seconds) if client_url else []
    shared_strings = _fetch_binary_strings(session, shared_url, settings.crawl_timeout_seconds) if shared_url else []

    if client_url and client_strings:
        route_sections = _route_sections(client_strings)
        if route_sections:
            documents.append(
                build_extracted_document(
                    source_key=f"{client_url}#routes",
                    origin="website",
                    source_format="application-bundle",
                    downloaded_at=downloaded_at,
                    sections=route_sections,
                    checksum_content=route_sections_as_dict(route_sections),
                    url=client_url,
                    page_title="Application route map",
                    document_title="Application route map",
                    file_name=Path(urlparse(client_url).path).name,
                    content_type="application/wasm",
                )
            )

        component_sections = _component_sections(client_strings)
        if component_sections:
            documents.append(
                build_extracted_document(
                    source_key=f"{client_url}#components",
                    origin="website",
                    source_format="application-bundle",
                    downloaded_at=downloaded_at,
                    sections=component_sections,
                    checksum_content=route_sections_as_dict(component_sections),
                    url=client_url,
                    page_title="Application page inventory",
                    document_title="Application page inventory",
                    file_name=Path(urlparse(client_url).path).name,
                    content_type="application/wasm",
                )
            )

    combined_strings = list(client_strings) + list(shared_strings)
    if combined_strings:
        field_sections = _field_inventory_sections(combined_strings)
        if field_sections:
            inventory_url = client_url or shared_url or "https://apply.medicalprotection.org"
            documents.append(
                build_extracted_document(
                    source_key=f"{inventory_url}#field-inventory",
                    origin="website",
                    source_format="application-bundle",
                    downloaded_at=downloaded_at,
                    sections=field_sections,
                    checksum_content=route_sections_as_dict(field_sections),
                    url=inventory_url,
                    page_title="Application field inventory",
                    document_title="Application field inventory",
                    file_name=Path(urlparse(inventory_url).path).name or None,
                    content_type="application/wasm",
                )
            )

    return documents


def route_sections_as_dict(sections: Sequence[ExtractedSection]) -> List[dict]:
    return [{"heading": section.heading, "text": section.text} for section in sections]


def _first_matching_url(resource_urls: Sequence[str], needle: str) -> Optional[str]:
    for url in resource_urls:
        if needle in url:
            return url
    return None


def _fetch_binary_strings(session: requests.Session, url: str, timeout_seconds: int) -> List[str]:
    try:
        response = session.get(url, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception:
        return []

    matches = re.findall(rb"[\x20-\x7E]{4,}", response.content)
    seen = set()
    strings: List[str] = []
    for raw in matches:
        try:
            value = raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            continue
        if not value or value in seen:
            continue
        seen.add(value)
        strings.append(value)
    return strings


def _route_sections(strings: Sequence[str]) -> List[ExtractedSection]:
    routes = []
    seen = set()
    for value in strings:
        match = re.search(r"/\{(?:SchemeId:int|SessionId:guid)\}[A-Za-z/]*", value)
        if not match:
            continue
        route = match.group(0).strip()
        if route in seen:
            continue
        seen.add(route)
        routes.append(route)

    practitioner_routes = [route for route in routes if "/Student" not in route]
    student_routes = [route for route in routes if "/Student" in route]
    sections = []
    if practitioner_routes:
        sections.append(ExtractedSection(heading="Practitioner routes", text=_numbered_lines(practitioner_routes)))
    if student_routes:
        sections.append(ExtractedSection(heading="Student routes", text=_numbered_lines(student_routes)))
    return sections


def _component_sections(strings: Sequence[str]) -> List[ExtractedSection]:
    sections = []
    mappings = [
        ("Practitioner main pages", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Practitioner\._[0-9A-Za-z_]+"),
        ("Student main pages", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Student\._[0-9A-Za-z_]+"),
        ("Previous history components", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Practitioner\.PreviousHistoryComponents\.[A-Za-z0-9_]+"),
        ("Practice overview components", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Practitioner\.PracticeOverviewComponents\.[A-Za-z0-9_]+"),
        ("Private practice medical components", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Practitioner\.PrivatePracticeMedicalComponents(?:\.[A-Za-z0-9_]+)+"),
        ("Private practice dental components", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Practitioner\.PrivatePracticeDentalComponents(?:\.[A-Za-z0-9_]+)+"),
        ("Student history and marketing components", r"Mps\.InternationalApplications\.Apply\.Client\.Pages\.Student\.HistoryAndMarketingComponents\.[A-Za-z0-9_]+"),
    ]
    for heading, pattern in mappings:
        values = _deduped_matches(strings, pattern)
        cleaned = [_clean_component_name(value) for value in values if value]
        cleaned = [value for value in cleaned if value]
        if cleaned:
            sections.append(ExtractedSection(heading=heading, text="\n".join(f"- {value}" for value in cleaned)))
    return sections


def _field_inventory_sections(strings: Sequence[str]) -> List[ExtractedSection]:
    sections = []

    conditionals = _deduped_matches(
        strings,
        r"get_(?:Is[A-Za-z0-9]+Required|Has[A-Za-z0-9]+Question|Ask[A-Za-z0-9]+Question|HasRetroactiveReportingBenefits|HasPrivateQuestion|HasPrivateSalaryQuestion|HasSchoolQuestion|HasSchoolIntakeQuestion|HasSchoolCourseQuestion)",
    )
    conditional_lines = [_clean_field_name(value.removeprefix("get_")) for value in conditionals]
    if conditional_lines:
        sections.append(ExtractedSection(heading="Conditional question flags", text="\n".join(f"- {value}" for value in conditional_lines)))

    categories = [
        ("Practice overview fields", r"get_(?:CountryOfPractice[A-Za-z0-9]*|PublicPractice[A-Za-z0-9]*|Hospital|Organisation|GroupPractice[A-Za-z0-9]*|RequiresIndependentPracticeCover|RequiresProtectionOutsideEmployerIndemnity|AcknowledgeNoClaimsIndemnity|DoesPrivateWork)"),
        ("Private practice fields", r"get_(?:PrivatePractice[A-Za-z0-9]+)"),
        ("Qualifications and registration fields", r"get_(?:Registration[A-Za-z0-9]*|SpecialtyId|SubSpecialtyId|RegisteredOnOtherSpecialtyList|OtherSpecialtyList|RegistrationCategory|CampaignCodeEmployer|CaseHistoryLetter)"),
        ("Student and school fields", r"get_(?:School[A-Za-z0-9]*|Student[A-Za-z0-9]*|QualificationCount)"),
        ("Previous history and claims fields", r"get_(?:Mrp[0-9A-Za-z]+|Convictions|ClaimsMade[A-Za-z0-9]+|Rrb[A-Za-z0-9]+)"),
    ]
    for heading, pattern in categories:
        raw_values = _deduped_matches(strings, pattern)
        cleaned = [_clean_field_name(value.removeprefix("get_")) for value in raw_values]
        cleaned = [value for value in cleaned if value]
        if cleaned:
            sections.append(ExtractedSection(heading=heading, text="\n".join(f"- {value}" for value in cleaned[:160])))

    return sections


def _walkthrough_payload_sections(payload: dict) -> List[ExtractedSection]:
    sections = []
    grouped = {
        "Application and scheme fields": [],
        "Personal details fields": [],
        "Address and contact fields": [],
        "Consent and status fields": [],
    }
    for key in sorted(payload):
        value = payload[key]
        line = f"{_humanize_name(key)}: {_value_type_name(value)}"
        if key in {"SchemeId", "Id", "ApplicationVersionId", "ApplicationStatusId", "MembershipNumber", "MembershipStartDate", "MembershipStartDateDisplay", "MembershipStartDateGoogle", "MembershipStartDateMax", "MembershipStartLabel", "PrivacyUri", "SaveErrorVisible", "StartDateInPast", "TransferredToMapsOn", "MapsContactId", "MapsMembershipNumber", "MapsPolicyNumber", "IsWebApplication"}:
            grouped["Application and scheme fields"].append(line)
        elif key in {"FirstName", "MiddleName", "LastName", "PreviousName", "ProspectTitleId", "ProspectTitleName", "Gender", "DateOfBirth", "IdNumber", "IdNumberLabel", "RegistrationNumber", "RegistrationNumber2"}:
            grouped["Personal details fields"].append(line)
        elif key in {"Address1", "Address2", "Address3", "City", "County", "CountryId", "CountryName", "Postcode", "Email", "EmailConfirmation", "MobilePhone", "HomePhone", "WorkPhone", "AddressLookupCountries", "AddressLookupPlaceholder", "CountyLabel", "PostcodeLabel", "HasAddressLookup", "HasPostcode", "IsAddressPostcodeRequired"}:
            grouped["Address and contact fields"].append(line)
        else:
            grouped["Consent and status fields"].append(line)

    for heading, lines in grouped.items():
        if lines:
            sections.append(ExtractedSection(heading=heading, text="\n".join(lines)))
    return sections


def _deduped_matches(strings: Sequence[str], pattern: str) -> List[str]:
    regex = re.compile(pattern)
    values = []
    seen = set()
    for item in strings:
        match = regex.search(item)
        if not match:
            continue
        value = match.group(0)
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _clean_component_name(value: str) -> str:
    cleaned = value.split("Pages.", 1)[-1]
    cleaned = cleaned.replace("Practitioner.", "Practitioner / ")
    cleaned = cleaned.replace("Student.", "Student / ")
    cleaned = cleaned.replace("PreviousHistoryComponents.", "Previous history / ")
    cleaned = cleaned.replace("PracticeOverviewComponents.", "Practice overview / ")
    cleaned = cleaned.replace("PrivatePracticeMedicalComponents.", "Private practice medical / ")
    cleaned = cleaned.replace("PrivatePracticeDentalComponents.", "Private practice dental / ")
    cleaned = cleaned.replace("HistoryAndMarketingComponents.", "History and marketing / ")
    cleaned = cleaned.replace("SharedComponents.", "Shared / ")
    cleaned = cleaned.replace(".", " / ")
    cleaned = cleaned.replace("_", " ")
    return _humanize_path(cleaned)


def _clean_field_name(value: str) -> str:
    value = re.sub(r"^(Is|Has|Ask)", "", value)
    value = re.sub(r"(Required|Question)$", "", value)
    value = value.replace("Id", " ID")
    value = value.replace("Rrb", "Retroactive reporting benefits ")
    value = value.replace("Mrp", "Previous history ")
    return _humanize_path(value)


def _humanize_path(value: str) -> str:
    parts = re.split(r"\s*/\s*", value)
    cleaned_parts = [_humanize_name(part) for part in parts if part]
    return " / ".join(cleaned_parts)


def _humanize_name(value: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", value or "")
    spaced = spaced.replace("_", " ").replace("-", " ")
    return " ".join(spaced.split()).strip()


def _value_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _numbered_lines(values: Iterable[str]) -> str:
    return "\n".join(f"{index}. {value}" for index, value in enumerate(values, start=1))
