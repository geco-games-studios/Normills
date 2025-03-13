import requests

url = "https://api.lenco.co/access/v2/collections/mobile-money"

payload = {
    "operator": "airtel",
    "bearer": "merchant",
    "amount": "100.00",  # Amount in the local currency
    "phone": "2348012345678",  # Phone number with country code (Nigeria)
    "reference": "ORDER-12345"  # Unique reference for this transaction
}

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": "Bearer xo+CAiijrIy9XvZCYyhjrv0fpSAL6CfU8CgA+up1NXqK"
}

response = requests.post(url, json=payload, headers=headers)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")

# Store the transaction reference from the response for OTP submission
try:
    response_data = response.json()
    transaction_reference = response_data.get('data', {}).get('reference')
    print(f"Transaction Reference: {transaction_reference}")
except Exception as e:
    print(f"Error parsing response: {e}")

