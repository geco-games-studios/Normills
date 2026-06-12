import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

FINAL_LENCO_STATUSES = ("successful", "failed")


def lenco_data_items(response_data):
    data = (response_data or {}).get("data")
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def best_lenco_data(response_data):
    items = lenco_data_items(response_data)
    for item in items:
        if item.get("status") in FINAL_LENCO_STATUSES:
            return item
    return items[0] if items else {}


def normalize_lenco_response(response_data):
    if not isinstance(response_data, dict):
        return {"status": False, "message": "Invalid response", "data": None}

    normalized = {**response_data}
    data = response_data.get("data")
    if isinstance(data, list):
        normalized["data"] = best_lenco_data(response_data) or None
    return normalized


def _mask_lenco_key():
    api_key = settings.LENCO_API_KEY or ''
    api_key = api_key.strip()
    if api_key.lower().startswith('bearer '):
        api_key = api_key[7:].strip()
    if not api_key:
        return 'missing'
    if len(api_key) <= 8:
        return 'configured-short'
    return f"{api_key[:4]}...{api_key[-4:]} ({len(api_key)} chars)"


def _lenco_authorization_header():
    api_key = (settings.LENCO_API_KEY or '').strip()
    if api_key.lower().startswith('bearer '):
        return api_key
    return f"Bearer {api_key}"


def _format_zambian_phone(phone_number):
    phone = ''.join(filter(str.isdigit, phone_number))
    if phone.startswith('00'):
        phone = phone[2:]
    if phone.startswith('0'):
        phone = f"260{phone[1:]}"
    elif len(phone) == 9:
        phone = f"260{phone}"
    elif not phone.startswith('260'):
        phone = f"260{phone}"
    return phone


def _lenco_headers():
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": _lenco_authorization_header(),
        "User-Agent": "Mozilla/5.0 (compatible; GecoMarketplaceBot/1.0; +https://marketplace.gecogames.com)"
    }


def _missing_api_key_response():
    logger.error("Lenco API key is not configured. Set LENCO_API_KEY in the server environment or .env file.")
    return {
        "status": False,
        "message": "Mobile money payments are not configured yet. Please contact support.",
        "data": None
    }


def _api_error_response(response, response_data, fallback_message="API error"):
    if response.status_code == 401:
        logger.error("Lenco authorization failed using API key %s", _mask_lenco_key())
        return {
            "status": False,
            "message": "Mobile money authorization failed. Please contact support.",
            "data": None
        }

    return {
        "status": False,
        "message": response_data.get("message", fallback_message),
        "data": None
    }

def submit_lenco_otp(otp, transaction_reference):
    """
    Submit OTP for a Lenco mobile money transaction.
    
    Args:
        otp (str): The OTP received by the customer.
        transaction_reference (str): The reference from the initial payment request.
        
    Returns:
        dict: The API response or an error dictionary.
    """
    url = f"{settings.LENCO_API_BASE_URL}/collections/mobile-money/submit-otp"
    if not settings.LENCO_API_KEY:
        return _missing_api_key_response()

    
    payload = {
        "otp": otp,
        "transaction_reference": transaction_reference
    }
    
    headers = _lenco_headers()
    
    logger.info(f"Submitting OTP for transaction: {transaction_reference}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        
        try:
            response_data = response.json()
            logger.info(f"OTP submission response: Status={response.status_code}, Data={response_data}")
        except ValueError:
            logger.error(f"Non-JSON response from OTP submission: {response.text}")
            response_data = {"status": False, "message": "Invalid JSON response", "data": None}
        
        if response.status_code >= 400:
            logger.error(f"OTP submission error: Status={response.status_code}, Response={response_data}")
            return _api_error_response(response, response_data)
        
        return response_data
    
    except requests.exceptions.RequestException as e:
        logger.error(f"OTP submission error: {str(e)}")
        return {
            "status": False,
            "message": str(e),
            "data": None
        }

def process_lenco_payment(amount, phone_number, reference, operator="airtel"):
    """
    Process a payment using the Lenco API.

    Args:
        amount (float): The amount to be paid.
        phone_number (str): The customer's phone number.
        reference (str): A unique reference for the transaction.
        operator (str): The mobile money operator (default: "airtel").

    Returns:
        dict: The API response or an error dictionary.
    """
    # Ensure the URL points to the correct endpoint
    url = f"{settings.LENCO_API_BASE_URL}/collections/mobile-money"
    if not settings.LENCO_API_KEY:
        return _missing_api_key_response()
    
    phone = _format_zambian_phone(phone_number)
    
    # Prepare payload and headers
    payload = {
        "operator": operator,
        "bearer": "merchant",
        "amount": f"{float(amount):.2f}",
        "phone": phone,
        "reference": reference,
        "currency": "ZMW"
    }
    
    headers = _lenco_headers()
    
    # Log the request for debugging
    logger.info(f"Lenco payment request: URL={url}, Payload={payload}")
    
    try:
        # Make the API request
        response = requests.post(url, json=payload, headers=headers)
        
        # Try to parse the JSON response
        try:
            response_data = response.json()
            logger.info(f"Lenco API response: Status={response.status_code}, Data={response_data}")
        except ValueError:
            logger.error(f"Non-JSON response: {response.text}")
            response_data = {"status": False, "message": "Invalid JSON response", "data": None}
        
        # Check for error status codes
        if response.status_code >= 400:
            logger.error(f"Lenco API error: Status={response.status_code}, Response={response_data}")
            return _api_error_response(response, response_data)
        
        # Return the response in the expected format
        return response_data
    
    except requests.exceptions.RequestException as e:
        # Log the error and return a meaningful response
        logger.error(f"Payment processing error: {str(e)}. Payload={payload}")
        return {
            "status": False,
            "message": str(e),
            "data": None
        }


def get_collection_status(transaction_reference):
    if not settings.LENCO_API_KEY:
        return _missing_api_key_response()

    urls = [
        f"{settings.LENCO_API_BASE_URL}/collections/status/{transaction_reference}",
        f"{settings.LENCO_API_BASE_URL}/collections/{transaction_reference}",
        f"{settings.LENCO_API_BASE_URL}/collections/mobile-money/{transaction_reference}",
    ]
    last_response = None

    try:
        for url in urls:
            response = requests.get(url, headers=_lenco_headers())
            try:
                response_data = response.json()
                logger.info(f"Lenco status response: URL={url}, Status={response.status_code}, Data={response_data}")
            except ValueError:
                logger.error(f"Non-JSON response from status check: URL={url}, Response={response.text}")
                response_data = {"status": False, "message": "Invalid JSON response", "data": None}

            if response.status_code >= 400:
                last_response = _api_error_response(response, response_data)
                continue

            normalized_response = normalize_lenco_response(response_data)
            if normalized_response.get("status"):
                status = best_lenco_data(response_data).get("status")
                if status in FINAL_LENCO_STATUSES:
                    return normalized_response
                last_response = normalized_response
                continue

            last_response = normalized_response

        return last_response or {
            "status": False,
            "message": "Failed to verify payment",
            "data": None
        }
    except requests.exceptions.RequestException as e:
        logger.error(f"Collection status error: {str(e)}")
        return {
            "status": False,
            "message": str(e),
            "data": None
        }
