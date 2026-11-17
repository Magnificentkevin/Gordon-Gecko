# SILAS platform (product context)

This is background for anyone loading the equity-desk skill. It is **not**
part of the trading loop. Do not start, scaffold, or resume the platform
work below unless the owner asks.

## What SILAS is

**SILAS** is Scheduled Intelligent Logistical Autonomous Services for
**All Business Cleaning** — B2B commercial-cleaning operations software,
not a consumer cleaning app and not a generic field-service CRM.

It is built to run the shift:

- Frontline staff authenticate on locked **Spark** tablets (kiosk mode,
  large touch targets, native camera, no OS chrome), walk the route the
  edge engine assigned, log completions and blockers, and keep working
  when building Wi-Fi does not.
- Facility managers get an admin triage dashboard (ranked incidents, one-
  click acknowledge or reroute, a VLA sync indicator).
- Enterprise clients can buy a read-only **Transparency Portal** SaaS
  add-on: proof-of-service ledger, facility heatmap, sanitized obstruction
  photos. It is not a second dispatcher.
- Legal, IT, and finance flows (on-device NDA / MSA / SaaS addendum, MDM,
  isolated SaaS billing) stay off the cleaning MSA.

The technical spine is an edge-first **Vision-Language-Action (VLA)**
stack: local path planning and safety on-device (for example TFLite
routing, encrypted local cache, TLS northbound). The cloud is for sync,
billing, and the portal. Facility maps and telemetry are not supposed to
be ingested into public models.

All Business Cleaning is the first design partner. Figures used in sales
copy (portal price, crowdfunding tiers) are examples, not booked revenue.
A Legal LangGraph service (contract review + SOC 2-oriented audit
envelopes) has been the first software slice in some of the internal
repos; Spark Android source and MDM vendor selection are out of scope
for this skill.

## Paused plan: SILASGrok / SILASystem

A Turborepo scaffold for the broader product — **SILASGrok** — was
planned and is **paused**. Do not resume it, open PRs against it, or
provision infrastructure for it unless the owner explicitly restarts
that work.

Intended shape, for when it is unpaused:

- Monorepo: `github.com/Magnificentkevin/SILASystem`
- Apps: a NestJS or Fastify API, a Next.js web client (admin / portal),
  an Expo field tablet app (Spark-class UI)
- Data: Prisma on PostgreSQL with PostGIS, Redis, object storage for
  photos
- Local fabric: Docker Compose
- Concerns already named elsewhere in the product work: identity, route
  assignment, offline cache and sync, the Transparency Portal as a
  billed add-on, MDM kiosk constraints, and keeping cleaning-contract
  liability off the SaaS addendum

Until the owner says otherwise, this skill's runnable path is the
**equity desk only**.
