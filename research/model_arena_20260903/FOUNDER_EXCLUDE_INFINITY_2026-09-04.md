# Founder exclude: infinity_parser2_pro

- Decision time: 2026-09-04 21:04:18 UTC+09:00
- Decision: exclude `infinity_parser2_pro` from TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1 Full Run
- Reason: H100×2 (or A100 80GB×2) burn (~$7/h per pod; 2 replicas ~$14/h); soft-cap pressure
- Actions:
  - Removed from `supervise_full.py` SLICES / CEILING / EXTRA
  - Terminated live pods: ['28lsx9o8s2nhkt', 'n2s1355rfi96s1']
  - Stopped infinity-only controller drivers: [32712, 44812, 33520, 35424]
  - Did NOT TaskStop supervisor tree; other model drivers left alone
- Queue: SUCCESS rows kept; PENDING/RUNNING left as-is (no further work)
- Benchmark report must mark infinity as FOUNDER_EXCLUDED / incomplete-excluded, not freeze with --allow-incomplete for other models
