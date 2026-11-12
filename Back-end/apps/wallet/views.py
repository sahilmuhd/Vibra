import razorpay
from django.conf import settings
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rooms.models import Gift, Room
from apps.rooms.realtime import broadcast_to_everyone, broadcast_to_room
from apps.rooms.serializers import GiftSerializer, SendGiftSerializer

from .models import CoinPackage, PaymentOrder
from .serializers import (
    CoinPackageSerializer,
    CreateOrderSerializer,
    TransactionSerializer,
)
from .services import credit_paid_order, get_balance, send_gift

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
    throttle_classes = []

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

        try:
            order_id = payload["payload"]["order"]["entity"]["id"]
        except (KeyError, TypeError):
            return Response({"detail": "Malformed payload."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            credit_paid_order(order_id)
        except PaymentOrder.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_200_OK)


class GiftListView(generics.ListAPIView):
    queryset = Gift.objects.all()
    serializer_class = GiftSerializer
    permission_classes = [permissions.IsAuthenticated]


class SendGiftView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SendGiftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        room = get_object_or_404(Room, id=data["room_id"])
        gift = get_object_or_404(Gift, id=data["gift_id"])
        recipient = get_object_or_404(get_user_model(), id=data["recipient_id"])

        event = send_gift(
            sender=request.user, recipient=recipient, gift=gift, room=room, combo=data["combo"]
        )

        # Fan out to the room's WebSocket group so every client sees the gift
        # animation live. Failures are logged, never raised: the gift is already paid.
        sender_profile = getattr(request.user, "profile", None)
        recipient_profile = getattr(recipient, "profile", None)
        payload = {
            "sender_id": request.user.id,
            "sender_name": sender_profile.username if sender_profile else request.user.username,
            "sender_avatar": sender_profile.avatar_url if sender_profile else "",
            "recipient_id": recipient.id,
            "recipient_name": recipient_profile.username if recipient_profile else recipient.username,
            "recipient_avatar": recipient_profile.avatar_url if recipient_profile else "",
            "gift_id": gift.id,
            "gift_name": gift.name,
            "gift_emoji": gift.emoji,
            "gift_cost": gift.cost,
            "animation_key": gift.animation_key,
            "combo": data["combo"],
        }
        broadcast_to_room(room.id, "gift.sent", payload)
        if gift.cost * data["combo"] >= settings.GLOBAL_GIFT_MIN:
            broadcast_to_everyone("gift.global", {**payload, "room_id": room.id, "room_name": room.name})
        return Response({"gift_event_id": event.id, "balance": get_balance(request.user)})
