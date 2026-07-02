"""M-Pesa callback handlers and log viewsets."""
import logging
from decimal import Decimal

from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import MpesaDirectPaymentLog, MpesaStkLog
from .serializers import MpesaDirectPaymentLogSerializer, MpesaStkLogSerializer
from .views_helpers import _resolve_read_branch

logger = logging.getLogger(__name__)


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def mpesa_callback(request):
    payload = request.data
    logger.info("M-Pesa callback received: %s", payload)

    callback = payload.get("Body", {}).get("stkCallback", {}) if isinstance(payload, dict) else {}
    checkout_request_id = callback.get("CheckoutRequestID") or ""
    merchant_request_id = callback.get("MerchantRequestID") or ""
    result_code = callback.get("ResultCode")
    result_desc = callback.get("ResultDesc") or ""

    try:
        result_code_value = int(result_code)
    except (TypeError, ValueError):
        result_code_value = None

    lookup = Q()
    queryset = MpesaStkLog.objects.none()
    if checkout_request_id or merchant_request_id:
        if checkout_request_id:
            lookup |= Q(checkout_request_id=checkout_request_id)
        if merchant_request_id:
            lookup |= Q(merchant_request_id=merchant_request_id)
        queryset = MpesaStkLog.objects.filter(lookup)

    updated = queryset.update(
        response=payload,
        result_code=result_code_value,
        result_desc=result_desc[:255],
        success=result_code_value == 0,
        message=result_desc[:255],
    )

    if updated == 0:
        logger.warning(
            "M-Pesa callback did not match any STK log. checkout_request_id=%s merchant_request_id=%s result_code=%s result_desc=%s",
            checkout_request_id, merchant_request_id, result_code, result_desc,
        )
        logger.warning("M-Pesa callback payload did not update a log: %s", payload)

    logger.info(
        "M-Pesa callback processed: checkout_request_id=%s merchant_request_id=%s result_code=%s updated_logs=%s",
        checkout_request_id, merchant_request_id, result_code, updated,
    )

    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


def _direct_result_parameter(result, *keys):
    parameters = result.get("ResultParameters", {}).get("ResultParameter", [])
    if isinstance(parameters, dict):
        parameters = [parameters]
    key_set = {key.lower() for key in keys}
    for item in parameters:
        key = str(item.get("Key", "")).lower()
        if key in key_set:
            return item.get("Value")
    return None


@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def mpesa_direct_callback(request):
    payload = request.data
    logger.info("M-Pesa direct till callback received: %s", payload)

    result = payload.get("Result", {}) if isinstance(payload, dict) else {}
    originator_conversation_id = result.get("OriginatorConversationID") or ""
    conversation_id = result.get("ConversationID") or ""
    result_code = result.get("ResultCode")
    result_desc = result.get("ResultDesc") or ""

    try:
        result_code_value = int(result_code)
    except (TypeError, ValueError):
        result_code_value = None

    transaction_id = (
        _direct_result_parameter(result, "ReceiptNo", "TransactionID", "MpesaReceiptNumber") or ""
    )
    amount = _direct_result_parameter(result, "Amount", "TransactionAmount")
    phone = _direct_result_parameter(result, "PhoneNumber", "MSISDN")
    payer_name = _direct_result_parameter(result, "DebitPartyName", "CustomerName", "ReceiverPartyPublicName")

    lookup = Q()
    if originator_conversation_id:
        lookup |= Q(originator_conversation_id=originator_conversation_id)
    if conversation_id:
        lookup |= Q(conversation_id=conversation_id)
    if transaction_id:
        lookup |= Q(transaction_id=transaction_id)

    queryset = MpesaDirectPaymentLog.objects.filter(lookup) if lookup else MpesaDirectPaymentLog.objects.none()
    updates = {
        "response": payload, "result_code": result_code_value,
        "result_desc": result_desc[:255], "success": result_code_value == 0,
        "message": result_desc[:255], "originator_conversation_id": originator_conversation_id,
        "conversation_id": conversation_id,
    }
    if transaction_id:
        updates["transaction_id"] = transaction_id
    if amount not in (None, ""):
        try:
            updates["amount"] = Decimal(str(amount))
        except Exception:
            logger.warning("M-Pesa direct callback had invalid amount: %s", amount)
    if phone:
        updates["phone"] = str(phone)
    if payer_name:
        updates["payer_name"] = str(payer_name)[:160]

    updated = queryset.update(**updates)
    if updated == 0:
        logger.warning(
            "M-Pesa direct callback did not match any log. originator=%s conversation=%s transaction=%s result_code=%s",
            originator_conversation_id, conversation_id, transaction_id, result_code,
        )

    return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class MpesaStkLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MpesaStkLog.objects.select_related("branch__company", "sale", "payment")
    serializer_class = MpesaStkLogSerializer

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-created_at")
        branch_obj = _resolve_read_branch(self.request)
        if not branch_obj:
            return queryset.none()
        queryset = queryset.filter(
            Q(branch=branch_obj) | Q(sale__branch=branch_obj) | Q(payment__sale__branch=branch_obj)
        )
        phone = (self.request.query_params.get("phone") or "").strip()
        success = self.request.query_params.get("success")
        checkout_request_id = (self.request.query_params.get("checkout_request_id") or "").strip()
        merchant_request_id = (self.request.query_params.get("merchant_request_id") or "").strip()

        if phone:
            queryset = queryset.filter(phone__icontains=phone)
        if checkout_request_id:
            queryset = queryset.filter(checkout_request_id=checkout_request_id)
        if merchant_request_id:
            queryset = queryset.filter(merchant_request_id=merchant_request_id)
        if success in {"1", "true", "yes"}:
            queryset = queryset.filter(success=True)
        if success in {"0", "false", "no"}:
            queryset = queryset.filter(success=False)
        return queryset


class MpesaDirectPaymentLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MpesaDirectPaymentLog.objects.select_related("branch__company", "sale", "payment")
    serializer_class = MpesaDirectPaymentLogSerializer

    def get_queryset(self):
        queryset = super().get_queryset().order_by("-created_at")
        branch_obj = _resolve_read_branch(self.request)
        if not branch_obj:
            return queryset.none()
        queryset = queryset.filter(
            Q(branch=branch_obj) | Q(sale__branch=branch_obj) | Q(payment__sale__branch=branch_obj)
        )
        transaction_id = (self.request.query_params.get("transaction_id") or "").strip().upper()
        conversation_id = (self.request.query_params.get("conversation_id") or "").strip()
        success = self.request.query_params.get("success")
        if transaction_id:
            queryset = queryset.filter(transaction_id=transaction_id)
        if conversation_id:
            queryset = queryset.filter(Q(conversation_id=conversation_id) | Q(originator_conversation_id=conversation_id))
        if success in {"1", "true", "yes"}:
            queryset = queryset.filter(success=True)
        if success in {"0", "false", "no"}:
            queryset = queryset.filter(success=False)
        return queryset
