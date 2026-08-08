from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    EventViewSet,
    OrganizationViewSet,
    VenueViewSet,
)

app_name = "events"

router = DefaultRouter()
router.register("categories", CategoryViewSet)
router.register("venues", VenueViewSet)
router.register("organizations", OrganizationViewSet)
router.register("events", EventViewSet)

urlpatterns = router.urls