"""
Core Models Facade
------------------
For 100% backward compatibility, all models and symbols have been modularized
into domain apps under `apps/` while being re-exported here:
  - apps.tenants.models: Tenant, Branch, DeliveryArea, PlatformConfiguration
  - apps.billing.models: AVAILABLE_FEATURES, SAAS_FEATURES_CATALOG, SubscriptionPlan, UpgradeRequest, TenantSubscription
  - apps.accounts.models: RESTAURANT_PERMISSIONS, PERMISSIONS_CATALOG, PRESET_ROLES_CONFIG, JobRole, Employee, UserProfile, RestaurantOwnerManager, RestaurantOwner, ensure_tenant_preset_roles
  - apps.menu.models: MenuCategory, MenuItem, MenuItemVariant, BranchMenuAvailability, BranchVariantPrice
  - apps.orders.models: Customer, Order, OrderItem
  - apps.inventory.models: InventoryItem
  - apps.callcenter.models: TenantApiKey, generate_api_key
  - apps.audit.models: AuditLog, KnowledgeDocument, log_audit_event
"""

from apps.tenants.models import (
    Tenant,
    Branch,
    DeliveryArea,
    PlatformConfiguration,
)
from apps.billing.models import (
    AVAILABLE_FEATURES,
    SAAS_FEATURES_CATALOG,
    SubscriptionPlan,
    UpgradeRequest,
    TenantSubscription,
)
from apps.accounts.models import (
    RESTAURANT_PERMISSIONS,
    PERMISSIONS_CATALOG,
    PRESET_ROLES_CONFIG,
    JobRole,
    Employee,
    UserProfile,
    RestaurantOwnerManager,
    RestaurantOwner,
    ensure_tenant_preset_roles,
)
from apps.menu.models import (
    MenuCategory,
    MenuItem,
    MenuItemVariant,
    BranchMenuAvailability,
    BranchVariantPrice,
)
from apps.orders.models import (
    Customer,
    Order,
    OrderItem,
)
from apps.inventory.models import (
    InventoryItem,
)
from apps.callcenter.models import (
    generate_api_key,
    TenantApiKey,
)
from apps.audit.models import (
    AuditLog,
    log_audit_event,
    KnowledgeDocument,
)

__all__ = [
    # Tenants
    "Tenant",
    "Branch",
    "DeliveryArea",
    "PlatformConfiguration",
    # Billing
    "AVAILABLE_FEATURES",
    "SAAS_FEATURES_CATALOG",
    "SubscriptionPlan",
    "UpgradeRequest",
    "TenantSubscription",
    # Accounts
    "RESTAURANT_PERMISSIONS",
    "PERMISSIONS_CATALOG",
    "PRESET_ROLES_CONFIG",
    "JobRole",
    "Employee",
    "UserProfile",
    "RestaurantOwnerManager",
    "RestaurantOwner",
    "ensure_tenant_preset_roles",
    # Menu
    "MenuCategory",
    "MenuItem",
    "MenuItemVariant",
    "BranchMenuAvailability",
    "BranchVariantPrice",
    # Orders
    "Customer",
    "Order",
    "OrderItem",
    # Inventory
    "InventoryItem",
    # Call Center
    "generate_api_key",
    "TenantApiKey",
    # Audit
    "AuditLog",
    "log_audit_event",
    "KnowledgeDocument",
]
