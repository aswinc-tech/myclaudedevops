# What Tatkal users struggle with (research notes, Nov 2026)

These notes come from a web search of news reports and public reviews. Trustpilot reviews are
unverified individual posts. Some sources date from 2025.

## Reported problems

1. **Site or app hangs or is unreachable at window-open.** One viral complaint said seats show as
   available until 10:00, then the site hangs. During the Diwali rush, users reported the site was
   unreachable until about 10:07. More outages hit Tatkal hours, including a report from July 2026.
   - https://www.freepressjournal.in/india/tatkal-booking-a-joke-irctc-faces-heat-over-tatkal-booking-glitches-after-thyrocare-chiefs-viral-complaint
   - https://www.business-standard.com/india-news/diwali-rush-irctc-website-crashes-before-tatkal-bookings-users-frustrated-125101700604_1.html
   - https://techstory.in/irctc-faces-third-outage-this-month-disrupting-tatkal-ticket-bookings-ahead-of-new-year/
   - https://www.outlookbusiness.com/news/irctc-outage-users-face-problem-in-ticket-bookings-due-to-technical-glitch-news-305472
2. **Sell-out within about a minute.** A LocalCircles survey reported by Business Standard found that
   7 in 10 respondents say tickets sell out within a minute, and many fail to get a Tatkal ticket.
   - https://www.business-standard.com/amp/india-news/irctc-tatkal-ticketing-error-indian-railways-agents-125060200354_1.html
3. **Repeated CAPTCHAs and failed transactions.** The Railway Minister announced a revamped site in
   response. I could not confirm whether it launched.
   - https://www.businesstoday.in/amp/india/story/fed-up-with-captcha-ashwini-vaishnaw-announces-new-irctc-website-by-july-15-536395-2026-06-11
   - https://swarajyamag.com/amp/story/infrastructure/students-complaint-to-railways-minister-ashwini-vaishnaw-triggers-30-day-deadline-for-revamped-irctc-website
4. **Payment deducted, no ticket.** Users report the money going out with no seat confirmed.
   - https://ca.trustpilot.com/review/irctc.com
5. **Bots and agents.** The most common allegation is that agents with special software get tickets
   before regular users get past the loading screen. The Ministry reports removing over 3 crore
   fake accounts and investigating suspicious PNRs.
   - https://odishatv.in/news/viral/irctc-tatkal-booking-woes-spark-outrage-app-crashes-but-how-agents-always-get-tickets-264345

## Rule changes that shape the design (announced 2025; check current notices)

- Tatkal on the IRCTC site and app is limited to Aadhaar-authenticated users, with OTP verification
  from 15 July 2025. That is why login is an OTP step with a human in the loop.
- Authorised agents are blocked for the first 30 minutes of each window (10:00–10:30 AC,
  11:00–11:30 non-AC).
- Railways reported blocking crores of suspicious user IDs linked to automated software.
  - https://www.freepressjournal.in/india/indian-railways-makes-aadhaar-otp-verification-mandatory-for-tatkal-ticket-bookings-from-july-2025
  - https://thesouthfirst.com/news/from-1-july-aadhaar-authentication-mandatory-for-tatkal-bookings-on-irctc-website-and-app
  - https://www.newsonair.gov.in/railways-announces-new-rules-for-tatkal-tickets-aadhaar-based-otp-authentication-must-from-july-1
  - https://indianrailways.gov.in/railwayboard/uploads/directorate/traffic_comm/Comm_Cir_2025/CC%2008%20of%202025.pdf
