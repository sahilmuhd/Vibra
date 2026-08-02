from django.urls import path

from .views import (
    CoinPackageListView,
    CreateOrderView,
    GiftListView,
    RazorpayWebhookView,
    SendGiftView,
    TransactionHistoryView,
    WalletBalanceView,
)

urlpatterns = [
    path("balance/", WalletBalanceView.as_view(), name="wallet-balance"),
    path("transactions/", TransactionHistoryView.as_view(), name="wallet-transactions"),
    path("packages/", CoinPackageListView.as_view(), name="coin-packages"),
    path("orders/create/", CreateOrderView.as_view(), name="create-order"),
    path("webhook/razorpay/", RazorpayWebhookView.as_view(), name="razorpay-webhook"),
    path("gifts/", GiftListView.as_view(), name="gift-list"),
    path("gifts/send/", SendGiftView.as_view(), name="send-gift"),
]
