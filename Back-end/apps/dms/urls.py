from django.urls import path

from .views import ConversationListView, ThreadView, UnreadDMCountView

urlpatterns = [
    path("", ConversationListView.as_view(), name="dm-list"),
    path("unread-count/", UnreadDMCountView.as_view(), name="dm-unread"),
    path("<int:user_id>/", ThreadView.as_view(), name="dm-thread"),
]
