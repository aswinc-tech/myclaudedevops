# Compliance and safety boundaries

## What this project will not do

- **Scrape or drive the IRCTC website or app**, solve or bypass CAPTCHAs, or spoof clients.
  IRCTC's terms forbid automated access. Railways actively blocks accounts linked to "automated
  software", and unauthorised ticket procurement can attract penalties under Section 143 of the
  Railways Act. Bots are also the main cause of the unfairness users complain about. Building a
  faster bot makes the problem worse.
- **Use several accounts** or book more than the Tatkal per-PNR limit.
- **Bypass Aadhaar/OTP authentication.** The OTP always comes from the account holder.
- **Book or pay outside what the traveller approved.** The fare cap, the options and their order
  come from the approved plan.

## What it does to be fast, legitimately

- Front-loads every decision and all data entry before the window opens.
- Fires on the booking server's clock, not the local clock.
- Retries transient failures quickly with jitter, inside a hard deadline.
- Falls back across pre-approved alternatives with no human round-trip.
- Reconciles ambiguous payments instead of double-booking.

## Integration path

Wire `PartnerApiProvider` to an authorised IRCTC partner / B2B API under a contract. Partners are
subject to the same rules, such as the agent blackout in the first 30 minutes, so check that your
integration's booking channel is allowed for end-user Tatkal bookings at window-open.

## Credentials

- Read them from environment variables or a secret manager (Vault, AWS SSM, Doppler, 1Password).
  Never hardcode them, never pass them as tool arguments, never log them.
- `profile.json` holds passenger details only, not passwords. It is git-ignored.
