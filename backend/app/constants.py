"""Values shared by several modules."""

# Must match the dropdown in frontend/src/LoginPage.tsx (read-only reference).
POSITIONS = [
    "Security Analyst",
    "Senior Analyst",
    "SOC Manager",
    "Threat Intelligence Lead",
    "Compliance Officer",
    "Platform Engineer",
    "CISO / CTO",
]

# Must match the CHECK constraint on profiles.role in schema.sql.
ROLES = ("analyst", "manager", "admin")

# Role every self-registered account gets. Promotion to manager/admin is done
# by an administrator (SQL Editor), never through the public API.
DEFAULT_ROLE = "analyst"
