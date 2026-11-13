from django.urls import path

from . import views

urlpatterns = [
    path("families/", views.FamilyListView.as_view(), name="families"),
    path("families/<int:family_id>/", views.FamilyDetailView.as_view(), name="family"),
    path("families/<int:family_id>/chat/", views.FamilyChatView.as_view(), name="family-chat"),
    path("families/<int:family_id>/<str:action>/", views.FamilyActionView.as_view(), name="family-action"),
    path("bonds/", views.BondsView.as_view(), name="bonds"),
    path("bonds/requests/<int:req_id>/<str:action>/", views.BondRequestActionView.as_view(), name="bond-request"),
    path("bonds/with/<int:user_id>/break/", views.BreakBondView.as_view(), name="bond-break"),
    path("bonds/of/<int:user_id>/", views.UserBondsView.as_view(), name="user-bonds"),
    path("visitors/", views.VisitorsView.as_view(), name="visitors"),
    path("friends-live/", views.FriendsLiveView.as_view(), name="friends-live"),
    path("voice/", views.VoiceUploadView.as_view(), name="voice-upload"),
    path("scheduled/", views.ScheduledListView.as_view(), name="scheduled"),
    path("scheduled/<int:sched_id>/<str:action>/", views.ScheduledActionView.as_view(), name="scheduled-action"),
]
