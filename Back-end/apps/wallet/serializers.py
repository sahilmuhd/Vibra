from rest_framework import serializers

from .models import CoinPackage, Transaction


class CoinPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CoinPackage
        fields = ["id", "coins", "price_inr", "is_best_value"]


class CreateOrderSerializer(serializers.Serializer):
    package_id = serializers.IntegerField()


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ["id", "type", "amount", "label", "created_at"]
