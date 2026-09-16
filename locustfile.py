"""Locust load test for Sneha Creations ERP.

Goal: 15 concurrent users for 5 minutes, 0% failures, p95 < 500ms.
Run against the containerized stack: http://127.0.0.1:8000
"""
from locust import HttpUser, task, between


class ERPUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        r = self.client.post(
            "/api/auth/login",
            json={"email": "loadtest@awsol.com", "password": "LoadTest123!"},
            name="POST /api/auth/login",
        )
        if r.status_code != 200:
            raise RuntimeError(f"Login failed: {r.status_code} {r.text[:200]}")
        token = r.json().get("access_token", "")
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    # Read-heavy workloads that hit the scoped-ledger paths from T20/T21/T22.

    @task(6)
    def list_buyer_orders(self):
        self.client.get("/buyer-order/orders", name="GET /buyer-order/orders")

    @task(4)
    def list_rm_orders(self):
        self.client.get("/rm-order/orders", name="GET /rm-order/orders")

    @task(3)
    def list_grn_buyer_orders(self):
        self.client.get("/grn/buyer-orders", name="GET /grn/buyer-orders")

    @task(3)
    def list_bom_orders(self):
        self.client.get("/bom/orders", name="GET /bom/orders")

    @task(2)
    def list_issue_rm_orders(self):
        self.client.get("/issue-rm/orders", name="GET /issue-rm/orders")

    @task(2)
    def list_fg_inspections(self):
        self.client.get("/fg-inspection/orders", name="GET /fg-inspection/orders")

    @task(2)
    def list_fg_inventory(self):
        self.client.get("/fg-inventory/orders", name="GET /fg-inventory/orders")

    @task(1)
    def list_master_parties(self):
        self.client.get("/master/all", name="GET /master/all")

    @task(1)
    def list_rm_inventory(self):
        self.client.get("/master/inventory/", name="GET /master/inventory/")

    @task(1)
    def health(self):
        self.client.get("/utils/health", name="GET /utils/health")

    @task(1)
    def me(self):
        self.client.get("/api/auth/me", name="GET /api/auth/me")
