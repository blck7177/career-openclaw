# Research Notes — Flex (job_4d36d8d6)
Generated: 2026-06-11

## Company Overview
Flex (getflex.com) is a New York-based fintech founded in 2019 that helps renters split their monthly rent into two smaller payments aligned with their pay schedule. Landlords and property managers receive full, on-time payment while renters gain payment flexibility. The product is a bank-issued unsecured line of credit (issued by Lead Bank or Column N.A., Member FDIC), regulated under the Truth in Lending Act.
Source: https://www.cbinsights.com/company/flex-2, https://getflex.com/

Revenue model: renters pay a monthly membership fee of $14.99 plus 1% of the rent amount. Flex has facilitated over $12 billion in on-time rent payments, supports over 1 million renters, and is available in more than 8 million units nationwide via 2,000+ property management companies.
Source: https://www.fintechcouncil.org/press-releases/flex-joins-the-american-fintech-council-afc-to-improve-housing-security-and-financial-stability-for-renters

## Relevant Division / Team
The Risk Platform Engineering team is one of several backend engineering units at Flex. Per a FinPlatform Backend job listing that describes the org, Flex engineering is divided into:
- **Risk Platform Engineering**: develops platforms and APIs that mitigate credit and fraud risk, using rules engines, ML, and event data systems
- **Core Platform Engineering**: maintains backend infrastructure for Payments, Billing, Identity, and Partner Integrations
- **Partner Integrations Engineering**: owns backend services connecting Flex to financial partners and payment networks

The Risk Platform team's stated mission is to "enhance Flex app accessibility for customers while safeguarding against improper use and unauthorized access." Key systems owned:
- Core rules engine (enterprise decision management lifecycle: business rule management, analytics, process management, ML/AI)
- Event data stream ingestion for near real-time fraud rules setup
- A/B testing and experimentation capabilities using greedy algorithms for fraud detection

The team is led by a Senior Engineering Manager who also oversees Data Infrastructure and Analytics Infrastructure, suggesting Risk Platform is closely coupled with data infra at Flex.
Source: https://job-boards.greenhouse.io/flex/jobs/4661298005, https://www.builtinnyc.com/job/staff-software-engineer-risk-engineering/4786429, https://theorg.com/org/getflex/org-chart/yaoquan-eric-ye

## Business Model / Domain Context
Flex's core business risk: extending credit to renters (not all creditworthy by traditional metrics) while ensuring on-time payment to landlords. The Risk Platform team therefore sits at the intersection of Flex's revenue model and its consumer risk exposure. Credit risk and fraud risk are existential concerns — if credit decisions are poor or fraud is unchecked, Flex absorbs the loss as the credit issuer.

The rules engine and ML systems the team builds directly govern which renters get approved, what payment plans are extended, and how misuse is detected in real time. This is not a monitoring/reporting role — it is a platform-building role that directly shapes credit policy execution and fraud prevention at scale.
Source: https://getflex.com/resources/what-responsible-flexibility-should-look-like

## Research Gaps
- Exact team headcount for Risk Platform Engineering is not publicly available.
- Specific ML/model types in use (scorecard, gradient boosting, LLM-based, etc.) not disclosed.
- Whether the A/B experimentation system is internally built or uses a third-party platform is unclear.
