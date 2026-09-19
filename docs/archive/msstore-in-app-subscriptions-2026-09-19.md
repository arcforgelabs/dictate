# Microsoft Store in-app subscriptions

This note records the current Microsoft Store policy position for adding a paid
subscription button inside the free Dictate Windows app.

Research date: 2026-06-25.

## Conclusion

Dictate can be listed as a free non-game Windows PC app and still offer a paid
subscription for hosted/frontier model access inside the app.

Microsoft Store policy does not prohibit a buy or subscribe button in a free
non-game PC app. For non-game products made available on PC devices, Microsoft
allows either:

- the Microsoft Store in-product purchase API, or
- a secure third-party purchase API.

This covers in-app purchases and subscriptions for digital items or services
that are consumed or used inside the product. Paid hosted AI model access should
be treated as a digital service used inside Dictate.

## Practical requirements

If Dictate adds a subscription for hosted/frontier model access:

- The free base app must remain accurately represented as free.
- The Store listing and Partner Center answers must disclose in-app purchases or
  subscriptions, including the type of purchase and price range.
- The app UI must make it clear when the user is initiating a purchase option.
- If using a secure third-party purchase API such as Stripe or Paddle, Dictate
  must identify the commerce transaction provider at transaction time,
  authenticate the user, obtain confirmation, and disclose the third-party
  purchase API use in Partner Center.
- Any payment card handling must meet current PCI DSS requirements. Prefer using
  a hosted checkout or payment provider UI rather than collecting card details
  directly in Dictate.
- If an active subscription is discontinued, Dictate must continue to provide
  the purchased digital goods or services until the subscription period expires.
- Subscription changes may add value but must not remove value for users who
  previously purchased the subscription.

## Generative AI disclosure

Because paid hosted/frontier access would provide live generative AI behavior,
Dictate must also keep the Microsoft Store generative AI requirements in view:

- disclose the use of live generative AI in Store metadata,
- note the use of live generative AI in Partner Center,
- ensure dynamic AI-created content complies with Store policies, and
- provide a way for users to report inappropriate content to the developer.

## Policy references

Primary source:

- Microsoft Store Policies, version 7.19, section 10.8 Financial Transactions:
  https://learn.microsoft.com/en-us/windows/apps/publish/store-policies#108-financial-transactions

Specific policy points from that page:

- Section 10.8.1: games and Xbox products must use Microsoft Store in-product
  purchase APIs for digital goods and services. Non-game products on PC devices
  may use either a secure third-party purchase API or the Microsoft Store
  in-product purchase API for in-app purchases of digital items or services used
  within the product.
- Section 10.8.2: when a secure third-party purchase API is allowed or required,
  the product must identify the transaction provider, authenticate the user,
  obtain confirmation, meet PCI DSS requirements when handling card data, and
  note third-party purchase API use in Partner Center.
- Section 10.8.4: product metadata must provide information about in-product
  purchase types and price ranges, must not mislead customers, and must make it
  clear to users that they are initiating a purchase option.
- Section 10.8.6: non-game PC products may use either a secure third-party
  purchase API or Microsoft's recurring billing API for subscriptions of digital
  goods or services. Active subscriptions must be honored until expiry, and
  subscription value must not be reduced for existing purchasers.
- Microsoft Store generative AI policy points on the same page require
  disclosure of live generative AI in metadata and Partner Center, policy
  compliance for dynamic AI content, and a user reporting path.

Related user-facing Microsoft Store reference:

- Make an in-app purchase in Microsoft Store:
  https://support.microsoft.com/en-us/accounts-billing/make-an-in-app-purchase-in-microsoft-store

## Current Dictate stance

The current Store listing draft now reserves Dictate Pro for handled hosted
model access and optional encrypted cloud sync. Before stable Store submission,
confirm the live listing, Partner Center pricing answers, public privacy policy,
public terms, age rating answers, certification notes, and screenshots all match
the actual app.

When Dictate Pro is enabled, the listing must keep three user choices separate:

- Sign in to Dictate Pro for account, entitlement, and hosted-model access.
- Enable encrypted cloud sync only after explicit consent.
- Use hosted Pro transcription only when the user intentionally sends audio to a
  hosted model path.
