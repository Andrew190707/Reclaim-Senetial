import main

client = main.app.test_client()

with client.session_transaction() as sess:
    sess["authenticated"] = True
    sess["csrf_token"] = "test-csrf-token"

payload = {
    "order_id": "ORD-DEBUG",
    "merchant_id": "M-001",
    "customer_id": "C-0001",
    "original_sku": "P-100-A",
    "returned_sku": "P-100-A",
    "refund_amount": 2500,
    "original_package_weight": 1.5,
    "returned_package_weight": 1.48,
    "serial_number_match": "match",
    "product_condition": "sealed",
    "warehouse_scan_result": "verified",
    "return_reason": "changed mind",
    "courier_status": "received",
}

response = client.post(
    "/api/verify",
    json=payload,
    headers={"X-CSRF-Token": "test-csrf-token"},
)

print("STATUS:", response.status_code)
print("RESPONSE:", response.get_json())