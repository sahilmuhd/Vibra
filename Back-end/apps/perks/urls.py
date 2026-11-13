from django.urls import path

from .views import BuyView, CheckinView, EquipView, EventsView, LeaderboardView, StoreView, TasksView

urlpatterns = [
    path("store/", StoreView.as_view(), name="store"),
    path("store/buy/", BuyView.as_view(), name="store-buy"),
    path("store/equip/", EquipView.as_view(), name="store-equip"),
    path("checkin/", CheckinView.as_view(), name="checkin"),
    path("tasks/", TasksView.as_view(), name="tasks"),
    path("leaderboard/", LeaderboardView.as_view(), name="leaderboard"),
    path("events/", EventsView.as_view(), name="events"),
]
