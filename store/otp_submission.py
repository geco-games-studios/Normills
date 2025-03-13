import requests

url = "https://api.lenco.co/access/v2/collections/mobile-money/submit-otp"

# Replace these values with the actual OTP and transaction reference
otp_code = "123456"  # The OTP received by the customer
transaction_reference = "YOUR_TRANSACTION_REFERENCE"  # From the initial payment response

payload = {
    "otp": otp_code,
    "transaction_reference": transaction_reference
}

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": "Bearer xo+CAiijrIy9XvZCYyhjrv0fpSAL6CfU8CgA+up1NXqK"
}

response = requests.post(url, json=payload, headers=headers)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")

