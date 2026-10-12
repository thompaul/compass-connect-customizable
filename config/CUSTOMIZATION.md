# Compass Connect Customisation Guide

This guide documents which parts of a Compass Connect deployment can be customised.
All options are defined in [`config/default.json`](default.json), which is the source of truth for available settings.

The configuration is organized into the following sections:

- **branding** — Application name, logos, colors, illustrations, and SEO metadata
- **auth** — Authentication behavior
- **cv** — CV feature availability
- **skillsReport** — Skills report branding, formats, and content
- **i18n** — Language and locale settings
- **analytics** — Google Analytics 4 and Google Tag Manager integration
- **faq** — Tutorial video URL
- **sensitiveData** — User data collection fields

Only options exposed in these sections are customizable. Core application logic, workflows, and page layouts are fixed.

## What you inherit if you set nothing

Every value below is optional, and nothing you leave unset belongs to another organisation.
A deployment that configures nothing calls itself Compass Connect, shows the product's own
marks, credits no funders, offers no contact address, reports to no analytics property, and
says plainly on its legal pages that it has not published any. That is deliberate: the
alternative is a deployment that looks finished while presenting itself as somebody else.

The one consequence worth knowing before you deploy: **your privacy policy and terms of use
are yours to write.** Until you supply them, both pages tell your users so.

## App Name & Tab Title

- `branding.appName` — name displayed throughout the application
- `branding.country` — country name shown in dashboard (e.g. "opportunities in Kenya"); defaults to "your country" when unset
- `branding.browserTabTitle` — text shown in the browser tab

## SEO Metadata

- `branding.metaDescription` — search engine description
- `branding.seo.name` — site name for search results
- `branding.seo.url` — public application URL
- `branding.seo.image` — image used for social sharing
- `branding.seo.description` — detailed SEO description

## Logos & Icons

Place assets in `frontend-new/public/` and reference them as `/filename.ext`,
or use a full URL to an externally hosted asset.

- `branding.assets.logo` — main logo
- `branding.assets.darkLogo` — logo variant used on light backgrounds
- `branding.assets.favicon` — browser tab icon
- `branding.assets.appIcon` — app icon (mobile / PWA)
- `branding.assets.chatAvatar` — AI assistant avatar shown in the chat interface

Unset, each of these falls back to the Compass Connect mark of the same kind, which ships in
the bundle. Nothing falls back to a partner's logo.

## Footer

- `branding.partnerLogos` — the funders and partners credited in the footer, as a list of
  entries taking `src`, `alt`, and optional `width` / `height`. Unset, the footer credits
  nobody: a deployment shows the organisations it names and no others.
- `branding.contactEmail` — the address behind the footer's "Contact" link. Unset, the link
  is not shown, rather than pointing your users at somebody else's inbox.
- `branding.footerAttribution` — one line naming whoever runs and funds this deployment, for
  example "Offered by the Ministry of Labour in partnership with …". Unset, the footer
  credits Compass Connect. This line is plain text and is not translated; if you serve
  several languages and need it translated, leave it unset for now.

## Illustrations

`branding.illustrations` controls the images shown across key pages.
Each value can be a plain path (`"/image.ext"`) or an object with `src`, `width`, and `height`
when you also want to control the display size.

- `loginHero` — large hero image on the login page
- `loginFeature1`, `loginFeature2`, `loginFeature3` — three feature images on the login page
- `homeHero` — hero image on the home page
- `homeHeroIllustrationPosition` — `center` or `edge`, controls the hero alignment
- `careerReadinessHero` — hero image on the career readiness page
- `authShapesBackground` — decorative background pattern on auth pages
- `dashboardShapesBackground` — decorative background pattern on the dashboard

## Colors

The application has seven brand colors. Each controls a specific region of the UI.

<img src="theme-colors.jpg" width="480" alt="Compass Connect brand colors" />

All color keys live under `branding.theme` in the config file.
colors are defined as space-separated RGB values, for example `"0 255 145"`.
This format lets the application generate transparency variants automatically.

- `brand-primary` — primary action buttons and key interactive elements
- `brand-secondary` — section headers and feature cards
- `brand-tertiary` — subtle backgrounds and lower-emphasis areas
- `brand-quaternary` — specific card backgrounds
- `brand-accent` — tag chips and inline highlights
- `brand-neutral` — navigation bar
- `brand-highlight` — skill tags and programme chips

Each color supports four variants by appending a suffix:
`(none)` for the main value, `-light`, `-dark`, and `-contrast-text`.
If only the main value is set the others are derived automatically.

After changing colors, verify text contrast meets WCAG AA
(4.5 : 1 for body text, 3 : 1 for large text) using the
[WebAIM Contrast Checker](https://webaim.org/resources/contrastchecker/).

## Languages & Translations

### Enabling Languages

- `i18n.ui.defaultLocale` — language that loads by default
- `i18n.ui.supportedLocales` — list of languages shown in the language switcher
- `i18n.conversation.default_locale` — default language for the AI conversation
- `i18n.conversation.available_locales` — languages available for the AI conversation

### Adding or Translating a Language

To add a new language or update existing translations, see the [Language Guide](../add-a-new-language.md).

## Localizing for Your National Context

Beyond UI translations, Compass Connect can be adapted to fit your program's labor market realities and educational context. Each major module has configurable options and specific information requirements from the implementing team.

### Build Your Profile (Skills Elicitation Agent)

The core Compass agent can be optimized for efficient, context-relevant skills elicitation:

- **Skills taxonomy** — Choose or build a localized taxonomy that best fits your labor market realities (e.g., the KESCO taxonomy in Kenya, national occupation standards in Zambia).
- **Employment types** — Configure and sequence the types of work/employment most relevant to ask your users.
- **Probing depth** — Adapt the extent to which the agent probes into tasks under a work experience.
- **Job preferences** — Turn on/off asking about job preferences.
- **CV upload & skills report** — Turn on/off CV upload and change skills report formatting options (see [CV Upload](#cv-upload) and [Skills Report](#skills-report)).

> **Information required**: National occupational taxonomy or standards to enable a localized skills taxonomy behind the agent.
>
> **Effort**: High — taxonomy localization requires dedicated research capacity.

### Career Readiness Learning Modules

The Job Readiness Learning Modules are designed for easy content and tutoring method adaptation:

- **Tutoring style** — Adapt system prompts to change tutoring styles (default is Scaffolded Socratic tutoring).
- **Module progression** — Turn on/off sequential module progression dependent on "passing".
- **Quizzes** — Turn on/off quiz-based end-of-module assessments.
- **Open support mode** — Turn on/off "Open support mode" post quiz completion.
- **Module content** — Change or add topics and lesson plans to the module list.

> **Information required**: Existing educational materials and curricula on practical or soft skills training for job readiness (e.g., in Zambia, TEVETA's Entrepreneurship course curriculum was used as content for one module).
>
> **Effort**: Low — module content is easily inserted once material is available.

### Career Explorer

The Career Explorer is optimized for adapting sectoral background content and what to spotlight:

- **Sectors** — Remove or change the sectors a user can explore, for more or less specialized guidance.
- **Priority sectors** — Choose which national priority sectors the agent nudges users to explore.
- **Sectoral data** — Ground the agent's context in nationally sourced and vetted sectoral data, training pathways, and career options.
- **Question guardrails** — Guardrail the types of user questions the agent should attempt to answer.
- **General knowledge** — Turn on/off whether the LLM uses general knowledge to answer questions.

> **Information required**: Labor market background documents (key economic sectors, national priorities, job concentration trends); national labor force survey microdata and reports; program offerings (training institutions and pathways available to users).
>
> **Effort**: Medium — may require dedicated research capacity depending on the quality of materials available.

### Job Matching

The Job Matching pipeline scrapes, classifies, and surfaces jobs to users:

- **Job sources** — Choose which job boards and aggregation sources to scrape from (e.g., gozambia.com in Zambia, or jobs provided directly by the implementing partner in Argentina).
- **Informal sources** — Explore sourcing jobs from non-traditional, informal sources such as social media channels (high development overhead).
- **Job detail columns** — Hide or unhide columns on job details visible to users.

> **Information required**: Preferred job boards and aggregation sources.
>
> **Effort**: Low.

### User Onboarding & Platform Access

- **Data collection fields** — Configure which user information fields the project wants to collect (see [Data Collection Fields](#data-collection-fields)).
- **Administrative integration** — Optionally integrate with a pre-existing administrative database of users.
- **FAQ and tutorials** — Provide non-technical onboarding guides and video tutorials accessible on the platform/FAQ (see [FAQ Video](#faq-video)).

> **Effort**: Low to medium — mostly configurable changes unless integration with an admin platform is required.

### Localization Effort Summary

| Module | Information required from implementing team | Effort |
|---|---|---|
| User Onboarding & Access | User data fields to collect; optional pre-existing admin user database; onboarding guides and tutorial videos | Low–Medium |
| Build Your Profile | National occupational taxonomy or standards for localized skills taxonomy | High |
| Career Readiness Modules | Existing curricula on job-readiness and soft skills training | Low |
| Career Explorer | Labor market background docs, labor force surveys, program and institution listings | Medium |
| Job Matching | Preferred job boards and scraping sources | Low |

## Authentication

- `auth.disableLoginCode` — remove the login code requirement
- `auth.disableRegistrationCode` — remove the registration code requirement
- `auth.disableRegistration` — make the app login-only (hides the register flow entirely)
- `auth.disableSocialAuth` — hide social login options such as Google sign-in

## Legal Documents

**A deployment that has not published legal documents says so.** Both pages render an explicit
notice telling the reader that the organisation running this deployment has not published a
privacy policy or terms of use, and to contact that organisation before providing personal
information. Nothing falls back to another party's documents: a privacy policy names the
organisation accountable for a user's data, and showing one belonging to a party that never
receives that data is a misstatement rather than a placeholder.

Supplying your own currently requires a frontend build, because the documents are compiled
into the bundle:

1. Add two Markdown files to `frontend-new/src/legal/documents/`, each with a `title` in its
   YAML frontmatter. `{{appName}}` in the body is replaced with `branding.appName`.
2. Register them in `frontend-new/src/legal/legalDocumentLoader.ts` under
   `documentsByProductName`, keyed by your `branding.appName` in lower case.

That is a build-time step in the product repository, which is the opposite of how everything
else on this page works. Loading these at runtime from your own deployment's assets — so a
partner supplies them the same way they supply a logo — is the change that retires the
registry, and the two entries in it today are the deployments that predate configurable legal
content.

## Features

### CV Upload

`cv.enabled` controls whether CV functionality is available in the application.
Set to `true` to enable or `false` to disable.
When disabled, all CV-related UI elements are hidden and CV APIs are not registered.

### Skills Report

- `skillsReport.logos` — one or more logos displayed in generated reports (supports separate sizing for DOCX and PDF). Unset, the report carries your deployment's own logo and nothing else
- `skillsReport.downloadFormats` — available download formats: `pdf`, `docx`, or both
- `skillsReport.report.summary.show` — show or hide the summary section
- `skillsReport.report.experienceDetails.title` — show or hide the experience title
- `skillsReport.report.experienceDetails.companyName` — show or hide the company name
- `skillsReport.report.experienceDetails.dateRange` — show or hide the date range
- `skillsReport.report.experienceDetails.location` — show or hide the location

## Analytics

Compass Connect supports Google Analytics 4 (GA4) via Google Tag Manager (GTM).

Tracking is **off by default and no identifiers are shipped**. Supply your own before
enabling it — an inherited container id sends your users' behaviour to whoever owns that
property, and nothing in the interface would show it.

- `analytics.enabled` — enable or disable tracking in the frontend
- `analytics.gtmContainerId` — GTM container ID (for example `GTM-XXXXXXX`)
- `analytics.ga4PropertyId` — GA4 property ID
- `analytics.ga4MeasurementId` — GA4 measurement ID (for example `G-XXXXXXX`)

For full setup, see the [Analytics Setup Guide](ANALYTICS_SETUP.md).

## Data Collection Fields

`sensitiveData.fields` configures the personal data form shown to users after registration.
Each field supports visibility, required/optional, type (free text or choices), validation, and per-language labels.

For the full schema and examples, see the
[Sensitive Data Fields Configuration Guide](../frontend-new/sensitive-data-fields-config.md).

## FAQ Video

`faq.tutorialVideoUrl` — URL of the tutorial video embedded in the FAQ page.

## Writing your own configuration file

1. Create a file named for your deployment — `config/horizonte.json`, say. Do **not** copy
   `default.json`; a copy is a fork, and it stops you inheriting anything the product improves.
2. Put in it only what differs from the defaults. Your file is layered over `default.json`,
   key by key:
   - objects merge, so changing one theme colour is one line, not thirty;
   - arrays and plain values replace, so `partnerLogos` is exactly the list you give;
   - `null` removes something the defaults provide.
3. Keep it with your deployment, not in this repository. A real deployment's configuration
   committed here is how `njira.json` came to exist, and why it has been removed.

```json
{
  "branding": {
    "appName": "Horizonte",
    "country": "Mozambique",
    "theme": { "brand-primary": "27 79 114" },
    "assets": { "logo": "/horizonte-logo.svg" },
    "contactEmail": "ola@horizonte.example"
  },
  "i18n": { "ui": { "defaultLocale": "pt-MZ", "supportedLocales": ["pt-MZ", "en-US"] } }
}
```

## Applying it to a deployment

Merge it into the environment file the deployment pipeline uploads:

```bash
python3 config/inject-config.py \
  --config /path/to/horizonte.json \
  --deployment-env /path/to/config-dir/.env.<realm>.<env>
```

That file also holds your infrastructure — database URIs, project ids, OAuth credentials —
which are **not** customisation and are not in your configuration file. The injector upserts:
lines it does not own are left exactly as they are, comments and all. Run it as often as you
like; it is the configuration that is authoritative, not the env file.

Then upload and deploy as usual (`setup_env.py`, then `prepare.py`). Your branding change
costs a redeploy, not a rebuild.

Two things it refuses rather than letting them fail later:

- **A variable the deployment does not know.** The pipeline validates against
  `iac/templates/env.template` and reads what the template lists, so a mapping the template
  does not carry would reach nothing at all. You are told which one, by name, here.
- **A value an environment file cannot carry.** A line break has nowhere to go. Values
  containing `#` or significant whitespace are quoted for you — without that,
  `Ranked #1 by the Ministry` arrives in the browser as `Ranked`.

## Applying it locally

The same file drives a local development environment, writing the backend `.env` and the
frontend's `public/data/env.js`:

```bash
cd config
python3 inject-config.py --config horizonte.json
python3 inject-config.py --config horizonte.json --namespaces branding auth
```

Restart the frontend and backend to pick up the new values.

## Configuration Reference

Refer to [default.json](default.json) for the complete configuration structure and all supported options.

## Important Notes

- If a configuration value is missing or contains a typo, the application will fall back to its default value
- If changes do not appear after deployment, verify the injected environment variables
- Configuration keys must match the structure in **default.json** exactly
