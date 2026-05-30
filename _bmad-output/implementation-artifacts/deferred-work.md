# Deferred Work

## From spec-quick-wins (2026-05-28)

- `app.py:312` — `mc_status`: unguarded `instance.network_interfaces[0].access_configs[0].nat_i_p` — if VM is RUNNING but has no external access config, raises IndexError. Pre-existing issue, not introduced by quick-wins change.
