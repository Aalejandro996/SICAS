from app import create_app


EXPECTED = {
    ("GET", "/api/v1/admin/roles"),
    ("GET", "/api/v1/admin/role-requests"),
    ("POST", "/api/v1/admin/role-requests"),
    ("POST", "/api/v1/admin/role-requests/<uuid:rid>/decision"),
    ("POST", "/api/v1/admin/users/<uuid:uid>/role-request"),
}

app = create_app()
actual = {(method, rule.rule) for rule in app.url_map.iter_rules() for method in rule.methods if method in {"GET", "POST"}}
missing = sorted(EXPECTED - actual)
if missing:
    raise SystemExit("Missing routes: " + ", ".join(f"{m} {r}" for m, r in missing))

print("Admin routes OK")
for method, rule in sorted(EXPECTED):
    print(f"{method} {rule}")
