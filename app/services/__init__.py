"""Background services layer — independently startable/stoppable autonomous services."""
from app.services.registry import ServiceRegistry, get_service_registry, BaseService

__all__ = ["ServiceRegistry", "get_service_registry", "BaseService"]
