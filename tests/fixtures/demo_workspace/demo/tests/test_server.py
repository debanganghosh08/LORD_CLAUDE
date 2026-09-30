import json
import threading
import urllib.request

from app.api.server import serve


def test_server_round_trip(tmp_path):
    server = serve(port=0, data_file=str(tmp_path / "ledger.json"))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({"date": "2026-03-15", "amount": "12.50", "kind": "expense", "category": "groceries", "description": "Bakery"}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/transactions", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request) as response:
            assert response.status == 201 and json.load(response)["amount_cents"] == 1250
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/report?year=2026&month=3") as response:
            assert json.load(response)["expense_total"] == "12.50 EUR"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            assert b"<title>Ledger</title>" in response.read()
        assert (tmp_path / "ledger.json").is_file()
    finally:
        server.shutdown()
        server.server_close()
