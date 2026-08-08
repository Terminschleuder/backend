from rest_framework.routers import DefaultRouter

from .views import CityViewSet

app_name = "locations"

router = DefaultRouter()
router.register("cities", CityViewSet)

urlpatterns = router.urls