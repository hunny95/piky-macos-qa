# Incident Notes

QA fixture for PIKY. Invented content.

## Timeline

- 09:12 Checkout error rate rises from 0.4% to 6.1%.
- 09:20 Rollback of the payment form starts.
- 09:31 Error rate is back under 0.5%.

## What we know

1. Only the card form was affected; wallets kept working.
2. The first alert fired eight minutes after the deploy.

```text
POST /checkout 502 upstream timed out
```
