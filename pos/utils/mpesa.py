import logging
import os
import re
import requests
import base64
from datetime import datetime
from django.utils import timezone


logger = logging.getLogger(__name__)
MPESA_STK_QUERY_THROTTLE_SECONDS = 20
SENSITIVE_LOG_KEYS = {
    "authorization",
    "password",
    "passkey",
    "consumersecret",
    "consumer_secret",
    "securitycredential",
    "security_credential",
    "access_token",
    "token",
}


def _mask_value(value):
    if value in (None, ""):
        return value
    value = str(value)
    if value.lower().startswith("bearer "):
        return "Bearer ***"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _safe_for_terminal(value):
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            normalized_key = str(key).replace("-", "_").lower()
            if normalized_key in SENSITIVE_LOG_KEYS or "secret" in normalized_key:
                safe[key] = _mask_value(item)
            else:
                safe[key] = _safe_for_terminal(item)
        return safe
    if isinstance(value, list):
        return [_safe_for_terminal(item) for item in value]
    return value


def _parse_response_body(response):
    try:
        return response.json()
    except ValueError:
        return {"text": response.text}


def _log_safaricom_request(label, method, url, headers=None, payload=None, auth_used=False):
    logger.info("Safaricom API request [%s]: %s %s", label, method, url)
    if auth_used:
        logger.info("Safaricom API request auth [%s]: HTTP Basic credentials configured", label)
    if headers:
        logger.info("Safaricom API request headers [%s]: %s", label, _safe_for_terminal(headers))
    if payload is not None:
        logger.info("Safaricom API request payload [%s]: %s", label, _safe_for_terminal(payload))


def _log_safaricom_response(label, response, body):
    logger.info("Safaricom API response [%s]: status=%s", label, response.status_code)
    logger.info("Safaricom API response headers [%s]: %s", label, _safe_for_terminal(dict(response.headers)))
    logger.info("Safaricom API response body [%s]: %s", label, _safe_for_terminal(body))

def validate_phone(phone):
    """Validate Kenyan phone number format (254XXXXXXXXX)"""
    phone = re.sub(r'\D', '', str(phone))
    return phone.startswith('254') and len(phone) == 12 and phone[3] in ['7', '1']

def _resolve_branch(branch):
    if branch is None:
        return None

    from ..models import Branch
    if isinstance(branch, int):
        return Branch.objects.select_related("company").filter(pk=branch, is_active=True).first()
    if isinstance(branch, Branch):
        return branch
    return None


def branch_has_mpesa_credentials(branch=None):
    """Return True when this exact branch has complete DB M-Pesa credentials."""
    branch = _resolve_branch(branch)
    if branch is None:
        return False
    return bool(
        branch.mpesa_stk_enabled and
        branch.mpesa_consumer_key and
        branch.mpesa_consumer_secret and
        branch.mpesa_business_shortcode and
        branch.mpesa_passkey and
        branch.mpesa_callback_url
    )


def branch_has_mpesa_direct_credentials(branch=None):
    """Return True when this branch can verify direct till payments."""
    branch = _resolve_branch(branch)
    if branch is None:
        return False
    return bool(
        branch.mpesa_till_enabled and
        branch.mpesa_consumer_key and
        branch.mpesa_consumer_secret and
        branch.mpesa_till_number and
        branch.mpesa_initiator_name and
        branch.mpesa_security_credential and
        branch.mpesa_direct_result_url and
        branch.mpesa_direct_timeout_url
    )


def get_mpesa_config(branch=None):
    """Get M-Pesa configuration.

    Branch-aware calls intentionally use only that branch's DB credentials.
    This prevents one company or branch from falling back to another global
    M-Pesa account when its own setup is incomplete.
    """
    env_config = {
        'consumer_key': os.getenv('MPESA_CONSUMER_KEY', ''),
        'consumer_secret': os.getenv('MPESA_CONSUMER_SECRET', ''),
        'business_shortcode': os.getenv('MPESA_BUSINESS_SHORTCODE', ''),
        'passkey': os.getenv('MPESA_PASSKEY', ''),
        'environment': os.getenv('MPESA_ENVIRONMENT', 'sandbox'),
        'callback_url': os.getenv('MPESA_CALLBACK_URL', ''),
    }
    if branch is None:
        return env_config

    branch = _resolve_branch(branch)
    if branch is None:
        return {
            'consumer_key': '',
            'consumer_secret': '',
            'business_shortcode': '',
            'passkey': '',
            'environment': env_config['environment'],
            'callback_url': '',
        }

    branch_config = {
        'consumer_key': branch.mpesa_consumer_key or '',
        'consumer_secret': branch.mpesa_consumer_secret or '',
        'business_shortcode': branch.mpesa_business_shortcode or '',
        'passkey': branch.mpesa_passkey or '',
        'environment': branch.mpesa_environment or env_config['environment'],
        'callback_url': branch.mpesa_callback_url or '',
        'till_number': branch.mpesa_till_number or '',
        'initiator_name': branch.mpesa_initiator_name or '',
        'security_credential': branch.mpesa_security_credential or '',
        'direct_result_url': branch.mpesa_direct_result_url or '',
        'direct_timeout_url': branch.mpesa_direct_timeout_url or '',
    }
    if any(branch_config[field] for field in ('consumer_key', 'consumer_secret', 'business_shortcode', 'passkey', 'callback_url')) and not branch_has_mpesa_credentials(branch):
        logger.warning('Branch %s has incomplete M-Pesa credentials; STK is disabled for this branch.', branch)
    return branch_config


def _first_result_parameter(result, *keys):
    parameters = (
        result.get('Result', {})
        .get('ResultParameters', {})
        .get('ResultParameter', [])
    )
    if isinstance(parameters, dict):
        parameters = [parameters]
    key_set = {key.lower() for key in keys}
    for item in parameters:
        key = str(item.get('Key', '')).lower()
        if key in key_set:
            return item.get('Value')
    return None


def _amount_value(value):
    if value in (None, ''):
        return None
    try:
        from decimal import Decimal
        return Decimal(str(value))
    except Exception:
        return None


def initiate_direct_payment_lookup(transaction_id, amount=None, branch=None):
    """Verify a customer-paid direct till transaction by M-Pesa receipt code."""
    transaction_id = (transaction_id or '').strip().upper()
    if not transaction_id:
        return {'success': False, 'message': 'M-Pesa transaction code is required.'}

    branch_obj = _resolve_branch(branch)
    if branch_obj and not branch_has_mpesa_direct_credentials(branch_obj):
        return {'success': False, 'message': 'Direct till verification is disabled or incomplete for this branch.'}
    config = get_mpesa_config(branch_obj)
    required = [
        config.get('consumer_key'),
        config.get('consumer_secret'),
        config.get('till_number'),
        config.get('initiator_name'),
        config.get('security_credential'),
        config.get('direct_result_url'),
        config.get('direct_timeout_url'),
    ]
    if not all(required):
        return {'success': False, 'message': 'Direct till verification is not configured for this branch.'}

    token, error = get_access_token(config['consumer_key'], config['consumer_secret'], config['environment'])
    if error:
        return {'success': False, 'message': f'Authentication failed: {error}'}

    environment = config['environment']
    url = f"https://{'sandbox' if environment == 'sandbox' else 'api'}.safaricom.co.ke/mpesa/transactionstatus/v1/query"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    payload = {
        'Initiator': config['initiator_name'],
        'SecurityCredential': config['security_credential'],
        'CommandID': 'TransactionStatusQuery',
        'TransactionID': transaction_id,
        'PartyA': config['till_number'],
        'IdentifierType': '2',
        'ResultURL': config['direct_result_url'],
        'QueueTimeOutURL': config['direct_timeout_url'],
        'Remarks': 'POS direct till payment lookup',
        'Occasion': branch_obj.name[:20] if branch_obj and branch_obj.name else 'POS Sale',
    }

    log = None
    try:
        from ..models import MpesaDirectPaymentLog
        log = MpesaDirectPaymentLog.objects.filter(
            branch=branch_obj,
            transaction_id=transaction_id,
            sale__isnull=True,
        ).order_by('-created_at').first()
        defaults = {
            'amount': _amount_value(amount),
            'request': {
                'method': 'POST',
                'url': url,
                'headers': _safe_for_terminal(headers),
                'payload': _safe_for_terminal(payload),
            },
            'message': 'Checking M-Pesa transaction status.',
        }
        if log:
            for key, value in defaults.items():
                setattr(log, key, value)
            log.save(update_fields=['amount', 'request', 'message', 'updated_at'])
        else:
            log = MpesaDirectPaymentLog.objects.create(
                branch=branch_obj,
                transaction_id=transaction_id,
                **defaults,
            )
    except Exception:
        logger.exception('Failed to create M-Pesa direct lookup log.')

    try:
        _log_safaricom_request('direct-till-query', 'POST', url, headers=headers, payload=payload)
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        result = _parse_response_body(response)
        _log_safaricom_response('direct-till-query', response, result)

        if log:
            log.response = result
            log.originator_conversation_id = result.get('OriginatorConversationID') or log.originator_conversation_id
            log.conversation_id = result.get('ConversationID') or log.conversation_id
            log.message = (
                result.get('ResponseDescription')
                or result.get('errorMessage')
                or result.get('ResultDesc')
                or 'M-Pesa lookup submitted.'
            )[:255]
            log.save(update_fields=['response', 'originator_conversation_id', 'conversation_id', 'message', 'updated_at'])

        return {
            'success': response.ok,
            'transaction_id': transaction_id,
            'log_id': log.id if log else None,
            'originator_conversation_id': result.get('OriginatorConversationID'),
            'conversation_id': result.get('ConversationID'),
            'response': result,
            'message': result.get('ResponseDescription') or result.get('errorMessage') or 'M-Pesa lookup submitted.',
        }
    except Exception as e:
        logger.error('M-Pesa direct till lookup exception: %s', str(e), exc_info=True)
        if log:
            log.message = str(e)[:255]
            log.response = {'exception': str(e)}
            log.save(update_fields=['message', 'response', 'updated_at'])
        return {'success': False, 'message': str(e)}

def get_access_token(consumer_key=None, consumer_secret=None, environment=None):
    """Get M-Pesa API access token"""
    config = get_mpesa_config()
    consumer_key = consumer_key or config['consumer_key']
    consumer_secret = consumer_secret or config['consumer_secret']
    environment = environment or config['environment']
    
    if not consumer_key or not consumer_secret:
        logger.error("M-Pesa access token request failed: credentials missing")
        return None, "M-Pesa credentials not configured"
    
    url = f"https://{'sandbox' if environment == 'sandbox' else 'api'}.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials"
    
    try:
        _log_safaricom_request("oauth-token", "GET", url, auth_used=True)
        response = requests.get(url, auth=(consumer_key, consumer_secret), timeout=30)
        result = _parse_response_body(response)
        _log_safaricom_response("oauth-token", response, result)
        response.raise_for_status()
        logger.info("M-Pesa access token received: %s", 'present' if result.get('access_token') else 'missing')
        return result.get('access_token'), None
    except Exception as e:
        logger.error("M-Pesa access token request failed: %s", str(e), exc_info=True)
        return None, str(e)

def _persist_stk_log(log_kwargs):
    try:
        from ..models import MpesaStkLog
        field_names = set()
        for field in MpesaStkLog._meta.fields:
            field_names.add(field.name)
            field_names.add(field.attname)
        MpesaStkLog.objects.create(
            **{k: v for k, v in log_kwargs.items() if k in field_names}
        )
    except Exception:
        pass


def initiate_stk_push(phone, amount, reference, description="", callback_url=None, sale=None, payment=None, branch=None):
    """Initiate M-Pesa STK Push payment"""
    payload = None
    log_kwargs = {
        'branch_id': None,
        'sale_id': sale if isinstance(sale, int) else (sale.id if sale is not None else None),
        'payment_id': payment if isinstance(payment, int) else (payment.id if payment is not None else None),
        'phone': phone,
        'amount': amount,
        'reference': reference,
        'request': {},
        'response': {},
        'success': False,
        'message': '',
    }

    logger.info("M-Pesa STK push start: phone=%s amount=%s reference=%s branch=%s", phone, amount, reference, branch)

    if not validate_phone(phone):
        logger.error("M-Pesa STK validation failed: invalid phone %s", phone)
        log_kwargs.update({'message': 'Invalid phone number', 'response': {'error': 'Invalid phone number'}})
        _persist_stk_log(log_kwargs)
        return {'success': False, 'message': 'Invalid phone number'}
    
    # Resolve branch object if needed (used to include branch name in payload)
    branch_obj = _resolve_branch(branch)
    if branch_obj:
        log_kwargs['branch_id'] = branch_obj.id
        if not branch_has_mpesa_credentials(branch_obj):
            log_kwargs.update({'message': 'M-Pesa STK is disabled or incomplete for this branch.', 'response': {'error': 'M-Pesa STK disabled'}})
            _persist_stk_log(log_kwargs)
            return {'success': False, 'message': 'M-Pesa STK is disabled or incomplete for this branch.'}

    config = get_mpesa_config(branch_obj)
    if not all([config['consumer_key'], config['consumer_secret'], config['business_shortcode'], config['passkey'], config['callback_url']]):
        logger.error(
            "M-Pesa not configured: consumer_key=%s consumer_secret=%s business_shortcode=%s passkey=%s callback_url=%s",
            bool(config['consumer_key']), bool(config['consumer_secret']), bool(config['business_shortcode']), bool(config['passkey']), bool(config['callback_url']),
        )
        log_kwargs.update({'message': 'M-Pesa not configured', 'response': {'error': 'M-Pesa not configured'}})
        _persist_stk_log(log_kwargs)
        return {'success': False, 'message': 'M-Pesa not configured'}
    
    token, error = get_access_token(config['consumer_key'], config['consumer_secret'], config['environment'])
    if error:
        log_kwargs.update({'message': f'Authentication failed: {error}', 'response': {'error': error}})
        _persist_stk_log(log_kwargs)
        return {'success': False, 'message': f'Authentication failed: {error}'}
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = f"{config['business_shortcode']}{config['passkey']}{timestamp}"
    password = base64.b64encode(password_str.encode()).decode()
    
    environment = config['environment']
    url = f"https://{'sandbox' if environment == 'sandbox' else 'api'}.safaricom.co.ke/mpesa/stkpush/v1/processrequest"
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    
    # Show only the branch name on the customer STK prompt.
    if branch_obj and getattr(branch_obj, 'name', None):
        acct_ref = branch_obj.name.strip()[:12]
    else:
        acct_ref = 'POS Sale'

    payload = {
        'BusinessShortCode': config['business_shortcode'],
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': int(float(amount)),
        'PartyA': phone,
        'PartyB': config['business_shortcode'],
        'PhoneNumber': phone,
        'CallBackURL': callback_url or config['callback_url'],
        'AccountReference': acct_ref,
        'TransactionDesc': (description or 'POS Payment')[:25],
    }
    log_kwargs['request'] = {
        'method': 'POST',
        'url': url,
        'headers': _safe_for_terminal(headers),
        'payload': _safe_for_terminal(payload),
    }
    
    try:
        _log_safaricom_request("stk-push", "POST", url, headers=headers, payload=payload)
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        result = _parse_response_body(response)
        _log_safaricom_response("stk-push", response, result)
        log_kwargs['response'] = result

        if result.get('ResponseCode') == '0':
            log_kwargs['success'] = False
            log_kwargs['message'] = result.get('CustomerMessage', 'STK sent; waiting for callback')
            log_kwargs['merchant_request_id'] = result.get('MerchantRequestID') or ''
            log_kwargs['checkout_request_id'] = result.get('CheckoutRequestID') or ''
            _persist_stk_log(log_kwargs)
            return {
                'success': True,
                'merchant_request_id': result.get('MerchantRequestID'),
                'checkout_request_id': result.get('CheckoutRequestID'),
                'customer_message': result.get('CustomerMessage'),
            }

        log_kwargs['message'] = result.get('errorMessage') or result.get('ResponseDescription') or 'STK push failed'
        _persist_stk_log(log_kwargs)
        return {'success': False, 'message': log_kwargs['message']}
    except Exception as e:
        logger.error("M-Pesa STK request exception: %s", str(e), exc_info=True)
        # Try to persist failure if possible
        try:
            from ..models import MpesaStkLog
            MpesaStkLog.objects.create(
                branch=branch_obj,
                phone=phone,
                amount=amount,
                reference=reference,
                request=_safe_for_terminal(payload),
                response={'exception': str(e)},
                message=str(e),
                success=False,
            )
        except Exception:
            pass
        return {'success': False, 'message': str(e)}


def query_stk_status(checkout_request_id, branch=None):
    """Run Safaricom STK push query for the given checkout request ID."""
    if not checkout_request_id:
        return {'success': False, 'message': 'Missing checkout_request_id'}

    branch_obj = _resolve_branch(branch)
    log = None
    try:
        from ..models import MpesaStkLog
        lookup = {'checkout_request_id': checkout_request_id}
        if branch_obj:
            lookup['branch'] = branch_obj
        log = MpesaStkLog.objects.filter(**lookup).order_by('-created_at').first()
    except Exception:
        log = None

    if log and log.result_code is not None:
        return {
            'success': True,
            'cached': True,
            'response': log.response,
            'ResultCode': log.result_code,
            'ResultDesc': log.result_desc,
            'message': log.message,
        }

    if log and log.response and (timezone.now() - log.updated_at).total_seconds() < MPESA_STK_QUERY_THROTTLE_SECONDS:
        return {
            'success': True,
            'pending': True,
            'cached': True,
            'retry_after': MPESA_STK_QUERY_THROTTLE_SECONDS,
            'response': log.response,
            'message': 'M-Pesa status query was checked recently. Waiting before querying Safaricom again.',
        }

    config = get_mpesa_config(branch_obj)
    if not all([config['consumer_key'], config['consumer_secret'], config['business_shortcode'], config['passkey']]):
        return {'success': False, 'message': 'M-Pesa not configured for status query.'}

    token, error = get_access_token(config['consumer_key'], config['consumer_secret'], config['environment'])
    if error:
        return {'success': False, 'message': f'Authentication failed: {error}'}

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    password_str = f"{config['business_shortcode']}{config['passkey']}{timestamp}"
    password = base64.b64encode(password_str.encode()).decode()
    environment = config['environment']
    url = f"https://{'sandbox' if environment == 'sandbox' else 'api'}.safaricom.co.ke/mpesa/stkpushquery/v1/query"

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }

    payload = {
        'BusinessShortCode': config['business_shortcode'],
        'Password': password,
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id,
    }

    try:
        _log_safaricom_request('stk-query', 'POST', url, headers=headers, payload=payload)
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        result = _parse_response_body(response)
        _log_safaricom_response('stk-query', response, result)
        fault = result.get('fault') if isinstance(result, dict) else None
        if fault:
            fault_message = fault.get('faultstring') or 'Safaricom status query is temporarily unavailable.'
            if log:
                try:
                    log.response = result
                    log.message = fault_message[:255]
                    log.save(update_fields=['response', 'message', 'updated_at'])
                except Exception:
                    logger.exception('Failed to persist M-Pesa STK query fault.')
            return {
                'success': True,
                'pending': True,
                'rate_limited': 'SpikeArrestViolation' in str(fault),
                'retry_after': 60,
                'response': result,
                'message': fault_message,
            }

        result_code = result.get('ResultCode')
        try:
            result_code_value = int(result_code)
        except (TypeError, ValueError):
            result_code_value = None

        if result_code_value is not None:
            result_desc = result.get('ResultDesc') or result.get('ResponseDescription') or ''
            try:
                from ..models import MpesaStkLog
                lookup = {'checkout_request_id': checkout_request_id}
                if branch_obj:
                    lookup['branch'] = branch_obj
                updated = MpesaStkLog.objects.filter(**lookup).update(
                    response=result,
                    result_code=result_code_value,
                    result_desc=result_desc[:255],
                    success=result_code_value == 0,
                    message=result_desc[:255],
                )
                logger.info(
                    'M-Pesa STK query persisted: checkout_request_id=%s branch=%s result_code=%s updated_logs=%s',
                    checkout_request_id,
                    branch_obj.id if branch_obj else None,
                    result_code_value,
                    updated,
                )
            except Exception:
                logger.exception('Failed to persist M-Pesa STK query result.')

        return {
            'success': response.ok,
            'response': result,
            'ResultCode': result.get('ResultCode'),
            'ResultDesc': result.get('ResultDesc'),
            'ResponseCode': result.get('ResponseCode'),
            'ResponseDescription': result.get('ResponseDescription'),
            'customer_message': result.get('CustomerMessage'),
        }
    except Exception as e:
        logger.error('M-Pesa STK query request exception: %s', str(e), exc_info=True)
        return {'success': False, 'message': str(e)}
