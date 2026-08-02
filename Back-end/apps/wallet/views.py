import razorpay
from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rooms.models import Gift, Room
from apps.rooms.serializers import GiftSerializer

from .models import CoinPackage, PaymentOrder, Transaction
from .serializers import (
    CoinPackageSerializer,
    CreateOrderSerializer,
    TransactionSerializer,
)
from .services import get_balance, send_gift

razorpay_client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


class WalletBalanceView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response({"balance": get_balance(request.user)})


class TransactionHistoryView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return self.request.user.transactions.all()[:100]


class CoinPackageListView(generics.ListAPIView):
    queryset = CoinPackage.objects.all().order_by("price_inr")
    serializer_class = CoinPackageSerializer
    permission_classes = [permissions.IsAuthenticated]


class CreateOrderView(APIView):
    """Step 1 of purchase: client picks a package, we create a Razorpay
    order server-side (so the amount can never be tampered with client-side)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        package = get_object_or_404(CoinPackage, id=serializer.validated_data["package_id"])

        order = razorpay_client.order.create({
            "amount": int(package.price_inr * 100),  # paise
            "currency": "INR",
            "notes": {"user_id": str(request.user.id), "package_id": str(package.id)},
        })
        PaymentOrder.objects.create(
            user=request.user, package=package, razorpay_order_id=order["id"]
        )
        return Response({
            "razorpay_order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key": settings.RAZORPAY_KEY_ID,
        }, status=status.HTTP_201_CREATED)


class RazorpayWebhookView(APIView):
    """Step 2: Razorpay calls this server-to-server once payment succeeds.
    Coins are only ever credited here — never from a client call — so a
    user can't fake a successful payment from devtools."""
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        signature = request.headers.get("X-Razorpay-Signature", "")
        try:
            razorpay_client.utility.verify_webhook_signature(
                request.body.decode(), signature, settings.RAZORPAY_WEBHOOK_SECRET
            )
        except razorpay.errors.SignatureVerificationError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        payload = request.data
        if payload.get("event") != "order.paid":
            return Response(status=status.HTTP_200_OK)

        order_id = payload["payload"]["order"]["entity"]["id"]
        try:
            order = PaymentOrder.objects.select_related("package", "user").get(
                razorpay_order_id=order_id
            )
        except PaymentOrder.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if order.status != PaymentOrder.STATUS_PAID:
            order.status = PaymentOrder.STATUS_PAID
            order.save(update_fields=["status"])
            Transaction.objects.create(
                user=order.user,
                type=Transaction.TYPE_PURCHASE,
                amount=order.package.coins,
                label=f"Purchased {order.package.coins} coins",
            )
        return Response(status=status.HTTP_200_OK)


class GiftListView(generics.ListAPIView):
    queryset = Gift.objects.all()
    serializer_class = GiftSerializer
    permission_classes = [permissions.IsAuthenticated]


class SendGiftView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        from apps.rooms.serializers import SendGiftSerializer

        serializer = SendGiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        room = get_object_or_404(Room, id=data["room_id"])
        gift = get_object_or_404(Gift, id=data["gift_id"])
        recipient = get_object_or_404(
            Room.objects.get(id=data["room_id"]).seats.model._meta.get_field("user").related_model,
            id=data["recipient_id"],
        )

        event = send_gift(
            sender=request.user, recipient=recipient, gift=gift, room=room, combo=data["combo"]
        )

        # Broadcast to the room's WebSocket group so every client sees the
        # gift animation live — see apps/rooms/consumers.py
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"room_{room.id}",
            {
                "type": "gift.sent",
                "sender_id": request.user.id,
                "recipient_id": recipient.id,
                "gift_id": gift.id,
                "combo": data["combo"],
            },
        )
        return Response({"gift_event_id": event.id, "balance": get_balance(request.user)})
