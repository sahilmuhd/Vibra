from django.contrib import admin

from .models import CoinPackage, PaymentOrder, Transaction

admin.site.register(Transaction)
admin.site.register(CoinPackage)
admin.site.register(PaymentOrder)
