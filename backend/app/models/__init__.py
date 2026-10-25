"""Import all models so Alembic sees the complete application metadata."""

from app.models.audit_event import AuditEvent
from app.models.login_rate_limit import LoginRateLimit
from app.models.mfa import MfaChallenge, MfaRecoveryCode, UserMfa
from app.models.payment_occurrence import PaymentOccurrence
from app.models.payment_receipt import PaymentReceipt
from app.models.recurring_payment import RecurringPayment
from app.models.registration import RegistrationChallenge, RegistrationRequest
from app.models.telegram_payments import TelegramPaymentAccount, TelegramPaymentConfirmation
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "AuditEvent",
    "LoginRateLimit",
    "MfaChallenge",
    "MfaRecoveryCode",
    "PaymentOccurrence",
    "PaymentReceipt",
    "RecurringPayment",
    "RegistrationChallenge",
    "RegistrationRequest",
    "TelegramPaymentAccount",
    "TelegramPaymentConfirmation",
    "User",
    "UserMfa",
    "UserSession",
]
