# Security / Privacy Notes

Prototype safeguards:
- Password hashing for demo accounts
- Signed short-lived tokens
- Role checks on authority endpoints
- Anonymous case IDs in operational views
- Audit log for key staff actions
- Sensitive questions can be skipped
- Synthetic data only
- No API keys stored in source

Before real deployment:
- Use a government-approved identity provider
- Enforce HTTPS and encryption at rest
- Replace SHA-256 demo password hashing with a modern password KDF such as Argon2/bcrypt
- Add CSRF/session protections where relevant
- Implement formal RBAC/ABAC and least privilege
- Conduct threat modelling and security audit
- Verify all support/emergency resources locally
- Implement retention/deletion policies and formal consent
