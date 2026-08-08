from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    EventViewSet,
    OrganizerViewSet,
    VenueViewSet,
)

app_name = "events"

router = DefaultRouter()
router.register("categories", CategoryViewSet)
router.register("venues", VenueViewSet)
router.register("organizers", OrganizerViewSet)
router.register("events", EventViewSet)

urlpatterns = router.urls