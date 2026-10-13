# Django discovers models here; they are defined in the infrastructure layer.
from .infrastructure.models import Delivery, Digest, Subscriber  # noqa: F401
