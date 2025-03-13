import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

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
    
    # Format the phone number (remove non-digits and ensure country code)
    phone = ''.join(filter(str.isdigit, phone_number))
    if not phone.startswith('234'):  # Adjust for your country code
        phone = f"234{phone}" if phone.startswith('0') else f"234{phone}"
    
    # Prepare payload and headers
    payload = {
        "operator": operator,
        "bearer": "merchant",
        "amount": f"{float(amount):.2f}",  # Format as string with 2 decimal places
        "phone": phone,
        "reference": reference
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {settings.LENCO_API_KEY}"
    }
    
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
            response_data = {"error": "Invalid JSON response", "raw_response": response.text}
        
        # Check for error status codes
        if response.status_code >= 400:
            logger.error(f"Lenco API error: Status={response.status_code}, Response={response_data}")
            return {
                "error": response_data.get("message", "API error"),
                "status": "failed",
                "status_code": response.status_code,
                "response": response_data
            }
        
        return response_data
    
    except requests.exceptions.RequestException as e:
        # Log the error and return a meaningful response
        logger.error(f"Payment processing error: {str(e)}. Payload={payload}")
        error_response = {
            "error": str(e),
            "status": "failed",
            "status_code": getattr(e.response, "status_code", None)
        }
        
        # Try to get more details from the response if available
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_response["response"] = e.response.json()
            except ValueError:
                error_response["response_text"] = e.response.text
        
        return error_response

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
    
    payload = {
        "otp": otp,
        "transaction_reference": transaction_reference
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {settings.LENCO_API_KEY}"
    }
    
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
            return {
                "status": False,
                "message": response_data.get("message", "API error"),
                "data": None
            }
        
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
    
    # Format the phone number (remove non-digits and ensure country code)
    phone = ''.join(filter(str.isdigit, phone_number))
    # Adjust country code as needed for your region
    if not phone.startswith('260'):  # Zambia country code
        phone = f"260{phone}" if phone.startswith('0') else f"260{phone}"
    
    # Ensure operator is exactly "airtel" or "mtn" (no validation here, it should be done before calling this function)
    # Do not modify the operator value - pass it as is
    
    # Prepare payload and headers
    payload = {
        "operator": operator,  # Use the operator value as provided
        "bearer": "merchant",
        "amount": f"{float(amount):.2f}",  # Format as string with 2 decimal places
        "phone": phone,
        "reference": reference,
        "currency": "ZMW"  # Add currency for Zambia
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {settings.LENCO_API_KEY}"
    }
    
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
            return {
                "status": False,
                "message": response_data.get("message", "API error"),
                "data": None
            }
        
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

