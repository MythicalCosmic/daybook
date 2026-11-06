"""Models of HR records (docs/PLAN-OWNER.md §3.11, with the pharmacy document kinds of §14.9).

A person's HR file hangs off their membership: one `EmployeeProfile` (made when they are
approved), up to three `EmergencyContact`s, any number of `EmployeeDocument`s (private files),
and their contracts. Passport, PINFL, card numbers and HR notes are stored encrypted
(`apps.core.crypto`); a digest next to the PINFL and the passport keeps them unique and
findable without decrypting anything.
"""

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.companies.models import Company, TenantModel
from apps.core.crypto import DigestField, EncryptedTextField
from apps.core.models import Language, TimeStampedModel
from apps.core.storage import private_storage, private_upload_to
from apps.members.models import Membership, Position


def _warn_days(default: int) -> models.PositiveSmallIntegerField:
    return models.PositiveSmallIntegerField(default=default, validators=[MaxValueValidator(365)])


class HRSettings(TimeStampedModel):
    """One row per company, made on first read by `apps.hr.conf.get_settings`."""

    company = models.OneToOneField(Company, on_delete=models.CASCADE, related_name="hr_settings")
    document_warn_days = _warn_days(30)
    contract_warn_days = _warn_days(30)
    probation_warn_days = _warn_days(7)
    celebrations_enabled = models.BooleanField(default=True)
    celebrate_anniversaries = models.BooleanField(default=True)
    # The employer as contracts print it ({{company_name}}, {{company_tin}}).
    employer_name = models.CharField(max_length=200, blank=True)
    employer_tin = models.CharField(max_length=9, blank=True)
    # "A qualified pharmacist whenever a pharmacy is open" (docs/PLAN-OWNER.md §14.9): checked at
    # pharmacy branches only, and only once `pharmacist_positions` says who counts.
    coverage_enabled = models.BooleanField(default=True)
    pharmacist_positions = models.ManyToManyField(Position, blank=True, related_name="+")
    coverage_min = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    # Only people who have their position's required documents (verified, in force) count.
    coverage_needs_documents = models.BooleanField(default=True)
    coverage_alert_minutes = models.PositiveSmallIntegerField(
        default=15, validators=[MinValueValidator(5), MaxValueValidator(240)]
    )
    coverage_days = models.PositiveSmallIntegerField(
        default=14, validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    # Off for a company whose cashiers only take payment while a pharmacist dispenses.
    unqualified_seller_alert = models.BooleanField(default=True)

    class Meta:
        verbose_name = "HR settings"
        verbose_name_plural = "HR settings"

    def __str__(self):
        return f"HR settings of {self.company}"


class EmployeeProfile(TenantModel):
    """Someone's personal details, IDs and how they are paid."""

    class Gender(models.TextChoices):
        MALE = "male", _("Male")
        FEMALE = "female", _("Female")

    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", _("Full time")
        PART_TIME = "part_time", _("Part time")
        CONTRACTOR = "contractor", _("Contractor")
        INTERN = "intern", _("Intern")

    class PayoutMethod(models.TextChoices):
        CASH = "cash", _("Cash")
        CARD = "card", _("Card")
        BANK = "bank", _("Bank transfer")

    class TerminationReason(models.TextChoices):
        RESIGNED = "resigned", _("Resigned")
        DISMISSED = "dismissed", _("Dismissed")
        CONTRACT_ENDED = "contract_ended", _("Contract ended")
        PROBATION_FAILED = "probation_failed", _("Probation not passed")
        OTHER = "other", _("Other")

    membership = models.OneToOneField(Membership, on_delete=models.CASCADE, related_name="profile")
    employee_number = models.CharField(max_length=20, blank=True)
    middle_name = models.CharField(max_length=100, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    show_birthday = models.BooleanField(default=True)
    gender = models.CharField(max_length=8, choices=Gender.choices, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    employment_type = models.CharField(
        max_length=16, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    personal_phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    pinfl = EncryptedTextField(plain_max_length=14, blank=True)
    pinfl_digest = DigestField(of="pinfl")
    passport = EncryptedTextField(plain_max_length=9, blank=True)
    passport_digest = DigestField(of="passport")
    tin = models.CharField(max_length=9, blank=True)
    payout_method = models.CharField(
        max_length=8, choices=PayoutMethod.choices, default=PayoutMethod.CASH
    )
    payout_card = EncryptedTextField(plain_max_length=19, blank=True)
    terminated_on = models.DateField(null=True, blank=True)
    termination_reason = models.CharField(
        max_length=16, choices=TerminationReason.choices, blank=True
    )
    termination_note = models.CharField(max_length=1000, blank=True)
    notes = EncryptedTextField(plain_max_length=4000, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "employee_number"],
                condition=~Q(employee_number=""),
                name="hr_unique_employee_number",
            ),
            # The same person can't be hired twice.
            models.UniqueConstraint(
                fields=["company", "pinfl_digest"],
                condition=~Q(pinfl_digest=""),
                name="hr_unique_pinfl",
            ),
        ]
        # A shared passport is a warning, not a constraint.
        indexes = [models.Index(fields=["company", "passport_digest"])]

    def __str__(self):
        return str(self.membership)


class EmergencyContact(TenantModel):
    """Whom to call when something happens to someone at work (three at most)."""

    MAX_PER_PERSON = 3

    profile = models.ForeignKey(
        EmployeeProfile, on_delete=models.CASCADE, related_name="emergency_contacts"
    )
    name = models.CharField(max_length=150)
    relation = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=20)

    class Meta:
        ordering = ["pk"]

    def __str__(self):
        return self.name


class DocumentKind(models.TextChoices):
    PASSPORT = "passport", _("Passport")
    ID_CARD = "id_card", _("ID card")
    MILITARY_ID = "military_id", _("Military ID")
    DIPLOMA = "diploma", _("Diploma")
    PHARMACY_DIPLOMA = "pharmacy_diploma", _("Pharmacy diploma")
    MEDICAL_DIPLOMA = "medical_diploma", _("Medical diploma")
    PHARMACIST_CERTIFICATE = "pharmacist_certificate", _("Specialist certificate")
    QUALIFICATION_CATEGORY = "qualification_category", _("Qualification category")
    STATE_REGISTRATION = "state_registration", _("State registration")
    MEDICAL_BOOK = "medical_book", _("Medical book")
    MEDICAL_EXAM = "medical_exam", _("Medical examination")
    WORK_BOOK = "work_book", _("Work record book")
    CONTRACT = "contract", _("Contract")
    NDA = "nda", _("Confidentiality agreement")
    PHOTO = "photo", _("Photo")
    OTHER = "other", _("Other")


# Identity documents: their numbers and scans need `hr.sensitive`.
ID_KINDS = frozenset({DocumentKind.PASSPORT, DocumentKind.ID_CARD, DocumentKind.MILITARY_ID})


class DocumentLevel(models.TextChoices):
    """A diploma's level, or a qualification category's."""

    HIGHER = "higher", _("Higher")
    COLLEGE = "college", _("College")
    HIGHEST = "highest", _("Highest category")
    FIRST = "first", _("First category")
    SECOND = "second", _("Second category")


class RequiredDocument(TenantModel):
    """A document everyone (no position) or everyone in a position must have. Any document of
    `kind` or of one of the `alternatives` satisfies it, at `level` when one is asked."""

    kind = models.CharField(max_length=24, choices=DocumentKind.choices)
    position = models.ForeignKey(
        Position,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="required_documents",
    )
    level = models.CharField(max_length=16, choices=DocumentLevel.choices, blank=True)
    alternatives = ArrayField(
        models.CharField(max_length=24, choices=DocumentKind.choices), default=list, blank=True
    )

    class Meta:
        ordering = ["position__order", "position__name", "kind", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "kind", "position"],
                nulls_distinct=False,
                name="hr_unique_required_document",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.position or '*'})"


class EmployeeDocument(TenantModel):
    """A document of someone's: a passport scan, a diploma, a medical book with its expiry."""

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="hr_documents"
    )
    kind = models.CharField(max_length=24, choices=DocumentKind.choices)
    title = models.CharField(max_length=150, blank=True)
    number = EncryptedTextField(plain_max_length=32, blank=True)
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True, db_index=True)
    level = models.CharField(max_length=16, choices=DocumentLevel.choices, blank=True)
    specialty = models.CharField(max_length=80, blank=True)
    issuer = models.CharField(max_length=150, blank=True)
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("hr/documents"), blank=True
    )
    visible_to_employee = models.BooleanField(default=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    # Warning steps already sent (days before expiry: 30, 7, 0), so each goes out once.
    expiry_notified = ArrayField(models.SmallIntegerField(), default=list, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["company", "kind"])]

    def __str__(self):
        return self.title or self.get_kind_display()

    @property
    def is_id(self) -> bool:
        return self.kind in ID_KINDS


class ContractKind(models.TextChoices):
    INDEFINITE = "indefinite", _("Indefinite")
    FIXED_TERM = "fixed_term", _("Fixed term")
    CIVIL = "civil", _("Civil contract")
    INTERNSHIP = "internship", _("Internship")


# Kinds that run to an end date.
TERM_KINDS = frozenset({ContractKind.FIXED_TERM, ContractKind.INTERNSHIP, ContractKind.CIVIL})


class ContractTemplate(TenantModel):
    """A company's contract text: sanitized HTML with {{placeholders}} from a fixed list
    (apps.hr.printing.PLACEHOLDERS), printed as a PDF for one person."""

    name = models.CharField(max_length=150)
    kind = models.CharField(
        max_length=16, choices=ContractKind.choices, blank=True, help_text=_("Empty: any kind.")
    )
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.UZ)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-is_active", "name", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["company", "name"], name="hr_unique_template_name"),
        ]

    def __str__(self):
        return self.name


class Contract(TenantModel):
    """Someone's employment contract. At most one is in force per person at a time; pay lives
    in payroll (`payroll.Compensation`), never here."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("In force")
        ENDED = "ended", _("Ended")
        TERMINATED = "terminated", _("Terminated")

    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="contracts")
    number = models.CharField(max_length=30, blank=True)
    kind = models.CharField(
        max_length=16, choices=ContractKind.choices, default=ContractKind.INDEFINITE
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    # The position when it was drawn up (people change positions; their contract doesn't).
    position = models.ForeignKey(
        Position, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    probation_until = models.DateField(null=True, blank=True)
    probation_passed_at = models.DateTimeField(null=True, blank=True)
    weekly_hours = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(60)],
    )
    template = models.ForeignKey(
        ContractTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contracts",
    )
    # The PDF made from the template, or the signed paper scanned.
    file = models.FileField(
        storage=private_storage, upload_to=private_upload_to("hr/contracts"), blank=True
    )
    pdf_generated_at = models.DateTimeField(null=True, blank=True)
    # A file with the salary in it opens only for payroll.view (and the person themselves).
    file_has_salary = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    # The last day it was in force, once it ended or was terminated.
    terminated_on = models.DateField(null=True, blank=True)
    termination_reason = models.CharField(max_length=300, blank=True)
    note = models.CharField(max_length=300, blank=True)
    # Warning steps already sent (days before the end / before probation finishes).
    end_notified = ArrayField(models.SmallIntegerField(), default=list, blank=True)
    probation_notified = ArrayField(models.SmallIntegerField(), default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        ordering = ["-starts_on", "-pk"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["company", "ends_on"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(status="active"),
                name="hr_one_active_contract",
            ),
            models.UniqueConstraint(
                fields=["company", "number"],
                condition=~Q(number=""),
                name="hr_unique_contract_number",
            ),
            models.CheckConstraint(
                condition=~Q(kind="fixed_term") | Q(ends_on__isnull=False),
                name="hr_fixed_term_has_an_end",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True) | Q(ends_on__gte=models.F("starts_on")),
                name="hr_contract_ends_after_it_starts",
            ),
            models.CheckConstraint(
                condition=Q(probation_until__isnull=True)
                | Q(probation_until__gte=models.F("starts_on")),
                name="hr_probation_after_the_start",
            ),
        ]

    def __str__(self):
        return self.number or f"#{self.pk}"

    @property
    def on_probation(self) -> bool:
        return self.probation_until is not None and self.probation_passed_at is None


class Celebration(TenantModel):
    """A birthday or a work anniversary that was celebrated (posted to the groups, the person
    greeted), so each one is celebrated once."""

    class Kind(models.TextChoices):
        BIRTHDAY = "birthday", _("Birthday")
        ANNIVERSARY = "anniversary", _("Work anniversary")

    membership = models.ForeignKey(
        Membership, on_delete=models.CASCADE, related_name="celebrations"
    )
    kind = models.CharField(max_length=12, choices=Kind.choices)
    day = models.DateField()
    years = models.PositiveSmallIntegerField(null=True, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-day", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "kind", "day"], name="hr_unique_celebration"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.day}"
